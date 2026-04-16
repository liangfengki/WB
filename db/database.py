"""
SQLite 数据库管理模块
- 授权码表 (license_keys)
- 用户使用记录表 (usage_logs)
- 黑名单表 (blacklist)
- 每日统计表 (daily_stats)
"""

import os
import sqlite3
import threading
import uuid
import hashlib
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from contextlib import contextmanager


DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "app.db")


def _ensure_db_dir():
    """确保数据库目录存在"""
    db_dir = os.path.dirname(DB_PATH)
    os.makedirs(db_dir, exist_ok=True)


class Database:
    """线程安全的 SQLite 数据库管理器"""

    DEFAULT_DAILY_LIMITS = {
        "trial": 10,
        "monthly": 100,
        "yearly": 200,
        "lifetime": 999,
    }

    def __init__(self, db_path: str = None):
        self.db_path = db_path or DB_PATH
        _ensure_db_dir()
        self._local = threading.local()
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        """获取当前线程的数据库连接"""
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(self.db_path, timeout=30)
            self._local.conn.row_factory = sqlite3.Row
            self._local.conn.execute("PRAGMA journal_mode=WAL")
            self._local.conn.execute("PRAGMA foreign_keys=ON")
        return self._local.conn

    @contextmanager
    def _cursor(self):
        """获取游标的上下文管理器"""
        conn = self._get_conn()
        cursor = conn.cursor()
        try:
            yield cursor
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    def _init_db(self):
        """初始化数据库表结构"""
        with self._cursor() as cur:
            # 授权码表
            cur.execute("""
                CREATE TABLE IF NOT EXISTS license_keys (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    code TEXT UNIQUE NOT NULL,
                    type TEXT NOT NULL DEFAULT 'trial',
                    status TEXT NOT NULL DEFAULT 'active',
                    max_daily_uses INTEGER NOT NULL DEFAULT 50,
                    total_uses INTEGER NOT NULL DEFAULT 0,
                    expires_at TEXT,
                    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                    activated_at TEXT,
                    remark TEXT,
                    created_by TEXT DEFAULT 'system'
                )
            """)

            # 用户使用记录表
            cur.execute("""
                CREATE TABLE IF NOT EXISTS usage_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    license_code TEXT NOT NULL,
                    ip_address TEXT,
                    user_agent TEXT,
                    action TEXT NOT NULL,
                    detail TEXT,
                    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
                )
            """)

            # 黑名单表
            cur.execute("""
                CREATE TABLE IF NOT EXISTS blacklist (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ip_address TEXT UNIQUE,
                    reason TEXT,
                    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
                )
            """)

            # 每日统计表
            cur.execute("""
                CREATE TABLE IF NOT EXISTS daily_stats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    stat_date TEXT NOT NULL,
                    license_code TEXT NOT NULL,
                    use_count INTEGER NOT NULL DEFAULT 0,
                    unique_ips INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                    updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                    UNIQUE(stat_date, license_code)
                )
            """)

            # 管理员表
            cur.execute("""
                CREATE TABLE IF NOT EXISTS admins (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
                )
            """)

            # 创建索引
            cur.execute("CREATE INDEX IF NOT EXISTS idx_license_code ON license_keys(code)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_usage_license ON usage_logs(license_code)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_usage_created ON usage_logs(created_at)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_blacklist_ip ON blacklist(ip_address)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_daily_stat_date ON daily_stats(stat_date)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_daily_license ON daily_stats(license_code)")

            # 创建默认管理员
            cur.execute("SELECT COUNT(*) as cnt FROM admins")
            if cur.fetchone()["cnt"] == 0:
                default_hash = hashlib.sha256("QAZplm0528..".encode()).hexdigest()
                cur.execute(
                    "INSERT INTO admins (username, password_hash) VALUES (?, ?)",
                    ("liangfengki", default_hash),
                )

    # ========== 授权码管理 ==========

    def get_default_daily_limit(self, code_type: str) -> int:
        """获取不同授权码类型的默认每日限额"""
        return self.DEFAULT_DAILY_LIMITS.get(code_type, 50)

    def generate_license_code(self, prefix: str = "WB") -> str:
        """生成 WB- 前缀的 12 位 UUID 授权码
        
        格式: WB-XXXXXXXXXXXX (WB- + 12位十六进制)
        """
        unique_id = uuid.uuid4().hex[:12].upper()
        return f"{prefix}-{unique_id}"

    def create_license(
        self,
        code_type: str = "trial",
        max_daily_uses: Optional[int] = None,
        expires_days: Optional[int] = None,
        remark: str = "",
        created_by: str = "admin",
    ) -> Dict[str, Any]:
        """创建授权码
        
        Args:
            code_type: 类型 - trial(试用), monthly(月付), yearly(年付), lifetime(永久)
            max_daily_uses: 每日最大使用次数，未传时按授权码类型使用默认值
            expires_days: 有效天数，None 表示永不过期
            remark: 备注
            created_by: 创建者
        
        Returns:
            创建的授权码信息
        """
        code = self.generate_license_code()

        if max_daily_uses is None or max_daily_uses <= 0:
            max_daily_uses = self.get_default_daily_limit(code_type)

        # 根据类型设置默认参数
        if code_type == "trial":
            expires_days = expires_days or 7
        elif code_type == "monthly":
            expires_days = expires_days or 30
        elif code_type == "yearly":
            expires_days = expires_days or 365
        elif code_type == "lifetime":
            expires_days = None

        expires_at = None
        if expires_days:
            expires_at = (
                datetime.now() + timedelta(days=expires_days)
            ).strftime("%Y-%m-%d %H:%M:%S")

        with self._cursor() as cur:
            cur.execute(
                """INSERT INTO license_keys 
                   (code, type, status, max_daily_uses, expires_at, remark, created_by)
                   VALUES (?, ?, 'active', ?, ?, ?, ?)""",
                (code, code_type, max_daily_uses, expires_at, remark, created_by),
            )
            cur.execute("SELECT * FROM license_keys WHERE code = ?", (code,))
            row = cur.fetchone()

        return dict(row) if row else {}

    def verify_license(
        self,
        code: str,
        ip_address: str = "",
        check_daily_limit: bool = True,
    ) -> Dict[str, Any]:
        """验证授权码是否有效
        
        Args:
            code: 授权码
            ip_address: 客户端 IP
            check_daily_limit: 是否检查每日配额
        
        Returns:
            {"valid": bool, "reason": str, "info": dict}
        """
        # 先检查黑名单
        if ip_address and self.is_blacklisted(ip_address):
            return {"valid": False, "reason": "IP已被列入黑名单", "info": {}}

        with self._cursor() as cur:
            cur.execute("SELECT * FROM license_keys WHERE code = ?", (code,))
            row = cur.fetchone()

        if not row:
            return {"valid": False, "reason": "授权码不存在", "info": {}}

        info = dict(row)

        if info["status"] != "active":
            return {"valid": False, "reason": f"授权码状态为{info['status']}", "info": info}

        # 检查过期
        if info["expires_at"]:
            expires = datetime.strptime(info["expires_at"], "%Y-%m-%d %H:%M:%S")
            if datetime.now() > expires:
                # 自动标记为过期
                self._update_license_status(code, "expired")
                return {"valid": False, "reason": "授权码已过期", "info": info}

        # 检查每日使用次数
        if check_daily_limit:
            today = datetime.now().strftime("%Y-%m-%d")
            today_uses = self._get_daily_use_count(code, today)
            if today_uses >= info["max_daily_uses"]:
                return {
                    "valid": False,
                    "reason": f"今日使用次数已达上限({today_uses}/{info['max_daily_uses']})",
                    "info": info,
                }

        return {"valid": True, "reason": "验证通过", "info": info}

    def record_usage(
        self,
        code: str,
        action: str,
        ip_address: str = "",
        user_agent: str = "",
        detail: str = "",
        count_quota: bool = False,
    ) -> None:
        """记录使用日志；可选是否计入配额统计"""
        now = datetime.now()
        today = now.strftime("%Y-%m-%d")
        created_at = now.strftime("%Y-%m-%d %H:%M:%S")

        with self._cursor() as cur:
            # 记录日志
            cur.execute(
                """INSERT INTO usage_logs 
                   (license_code, ip_address, user_agent, action, detail, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (code, ip_address, user_agent, action, detail, created_at),
            )

            if count_quota:
                # 更新总使用次数
                cur.execute(
                    "UPDATE license_keys SET total_uses = total_uses + 1 WHERE code = ?",
                    (code,),
                )

                # 更新每日统计
                cur.execute(
                    """INSERT INTO daily_stats (stat_date, license_code, use_count, updated_at)
                       VALUES (?, ?, 1, ?)
                       ON CONFLICT(stat_date, license_code) DO UPDATE SET
                           use_count = use_count + 1,
                           updated_at = ?""",
                    (today, code, created_at, created_at),
                )

                # 更新独立 IP 数
                cur.execute(
                    """UPDATE daily_stats SET unique_ips = (
                           SELECT COUNT(DISTINCT ip_address) FROM usage_logs
                           WHERE license_code = ? AND DATE(created_at) = ?
                       ) WHERE stat_date = ? AND license_code = ?""",
                    (code, today, today, code),
                )

            # 激活授权码（首次使用）
            cur.execute(
                "UPDATE license_keys SET activated_at = ? WHERE code = ? AND activated_at IS NULL",
                (created_at, code),
            )

    def _get_daily_use_count(self, code: str, date_str: str) -> int:
        """获取某日使用次数"""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT use_count FROM daily_stats WHERE stat_date = ? AND license_code = ?",
            (date_str, code),
        ).fetchone()
        return row["use_count"] if row else 0

    def _update_license_status(self, code: str, status: str):
        """更新授权码状态"""
        with self._cursor() as cur:
            cur.execute(
                "UPDATE license_keys SET status = ? WHERE code = ?", (status, code)
            )

    def get_license(self, code: str) -> Optional[Dict[str, Any]]:
        """获取授权码信息"""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM license_keys WHERE code = ?", (code,)
        ).fetchone()
        return dict(row) if row else None

    def list_licenses(
        self,
        status: Optional[str] = None,
        code_type: Optional[str] = None,
        page: int = 1,
        per_page: int = 20,
    ) -> Dict[str, Any]:
        """分页获取授权码列表"""
        conn = self._get_conn()
        conditions = []
        params = []

        if status:
            conditions.append("status = ?")
            params.append(status)
        if code_type:
            conditions.append("type = ?")
            params.append(code_type)

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        # 总数
        total = conn.execute(
            f"SELECT COUNT(*) as cnt FROM license_keys {where}", params
        ).fetchone()["cnt"]

        # 分页数据
        offset = (page - 1) * per_page
        rows = conn.execute(
            f"SELECT * FROM license_keys {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
            params + [per_page, offset],
        ).fetchall()

        return {
            "items": [dict(r) for r in rows],
            "total": total,
            "page": page,
            "per_page": per_page,
            "total_pages": (total + per_page - 1) // per_page,
        }

    def batch_create_licenses(
        self,
        count: int,
        code_type: str = "trial",
        max_daily_uses: int = 50,
        expires_days: Optional[int] = None,
        remark: str = "",
        created_by: str = "admin",
    ) -> List[Dict[str, Any]]:
        """批量创建授权码"""
        results = []
        for _ in range(count):
            license_info = self.create_license(
                code_type=code_type,
                max_daily_uses=max_daily_uses,
                expires_days=expires_days,
                remark=remark,
                created_by=created_by,
            )
            results.append(license_info)
        return results

    def revoke_license(self, code: str) -> bool:
        """吊销授权码"""
        with self._cursor() as cur:
            cur.execute(
                "UPDATE license_keys SET status = 'revoked' WHERE code = ?", (code,)
            )
            return cur.rowcount > 0

    def delete_license(self, code: str) -> bool:
        """删除授权码"""
        with self._cursor() as cur:
            cur.execute("DELETE FROM license_keys WHERE code = ?", (code,))
            return cur.rowcount > 0

    # ========== 黑名单管理 ==========

    def add_to_blacklist(self, ip_address: str, reason: str = "") -> bool:
        """添加 IP 到黑名单"""
        try:
            with self._cursor() as cur:
                cur.execute(
                    "INSERT OR IGNORE INTO blacklist (ip_address, reason) VALUES (?, ?)",
                    (ip_address, reason),
                )
                return cur.rowcount > 0
        except sqlite3.IntegrityError:
            return False

    def remove_from_blacklist(self, ip_address: str) -> bool:
        """从黑名单移除 IP"""
        with self._cursor() as cur:
            cur.execute("DELETE FROM blacklist WHERE ip_address = ?", (ip_address,))
            return cur.rowcount > 0

    def is_blacklisted(self, ip_address: str) -> bool:
        """检查 IP 是否在黑名单中"""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT id FROM blacklist WHERE ip_address = ?", (ip_address,)
        ).fetchone()
        return row is not None

    def list_blacklist(self) -> List[Dict[str, Any]]:
        """获取黑名单列表"""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM blacklist ORDER BY created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    # ========== 统计查询 ==========

    def get_daily_stats(
        self, date_str: Optional[str] = None, days: int = 7
    ) -> List[Dict[str, Any]]:
        """获取每日统计数据"""
        conn = self._get_conn()
        if date_str:
            rows = conn.execute(
                """SELECT ds.*, lk.type, lk.status as license_status
                   FROM daily_stats ds
                   LEFT JOIN license_keys lk ON ds.license_code = lk.code
                   WHERE ds.stat_date = ?
                   ORDER BY ds.use_count DESC""",
                (date_str,),
            ).fetchall()
        else:
            start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
            rows = conn.execute(
                """SELECT ds.stat_date, 
                      SUM(ds.use_count) as total_uses,
                      SUM(ds.unique_ips) as total_ips,
                      COUNT(DISTINCT ds.license_code) as active_licenses
                   FROM daily_stats ds
                   WHERE ds.stat_date >= ?
                   GROUP BY ds.stat_date
                   ORDER BY ds.stat_date DESC""",
                (start_date,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_overview_stats(self) -> Dict[str, Any]:
        """获取总览统计"""
        conn = self._get_conn()
        today = datetime.now().strftime("%Y-%m-%d")

        total_licenses = conn.execute(
            "SELECT COUNT(*) as cnt FROM license_keys"
        ).fetchone()["cnt"]
        active_licenses = conn.execute(
            "SELECT COUNT(*) as cnt FROM license_keys WHERE status = 'active'"
        ).fetchone()["cnt"]
        today_uses = conn.execute(
            "SELECT COALESCE(SUM(use_count), 0) as cnt FROM daily_stats WHERE stat_date = ?",
            (today,),
        ).fetchone()["cnt"]
        total_uses = conn.execute(
            "SELECT COALESCE(SUM(total_uses), 0) as cnt FROM license_keys"
        ).fetchone()["cnt"]
        blacklist_count = conn.execute(
            "SELECT COUNT(*) as cnt FROM blacklist"
        ).fetchone()["cnt"]

        return {
            "total_licenses": total_licenses,
            "active_licenses": active_licenses,
            "today_uses": today_uses,
            "total_uses": total_uses,
            "blacklist_count": blacklist_count,
        }

    # ========== 管理员操作 ==========

    def verify_admin(self, username: str, password: str) -> bool:
        """验证管理员登录"""
        conn = self._get_conn()
        password_hash = hashlib.sha256(password.encode()).hexdigest()
        row = conn.execute(
            "SELECT id FROM admins WHERE username = ? AND password_hash = ?",
            (username, password_hash),
        ).fetchone()
        return row is not None

    def change_admin_password(self, username: str, old_password: str, new_password: str) -> bool:
        """修改管理员密码"""
        if not self.verify_admin(username, old_password):
            return False
        new_hash = hashlib.sha256(new_password.encode()).hexdigest()
        with self._cursor() as cur:
            cur.execute(
                "UPDATE admins SET password_hash = ? WHERE username = ?",
                (new_hash, username),
            )
            return True

    # ========== 使用日志 ==========

    def get_usage_logs(
        self,
        license_code: Optional[str] = None,
        page: int = 1,
        per_page: int = 50,
    ) -> Dict[str, Any]:
        """获取使用日志"""
        conn = self._get_conn()
        conditions = []
        params = []

        if license_code:
            conditions.append("license_code = ?")
            params.append(license_code)

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        total = conn.execute(
            f"SELECT COUNT(*) as cnt FROM usage_logs {where}", params
        ).fetchone()["cnt"]

        offset = (page - 1) * per_page
        rows = conn.execute(
            f"SELECT * FROM usage_logs {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
            params + [per_page, offset],
        ).fetchall()

        return {
            "items": [dict(r) for r in rows],
            "total": total,
            "page": page,
            "per_page": per_page,
        }

    # ========== 数据库备份 ==========

    def backup(self, backup_dir: str = None) -> str:
        """备份数据库
        
        Returns:
            备份文件路径
        """
        backup_dir = backup_dir or os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "data", "backups"
        )
        os.makedirs(backup_dir, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = os.path.join(backup_dir, f"app_backup_{timestamp}.db")

        # 使用 SQLite 内置备份
        src_conn = self._get_conn()
        dst_conn = sqlite3.connect(backup_path)
        src_conn.backup(dst_conn)
        dst_conn.close()

        # 清理超过 30 天的备份
        self._cleanup_old_backups(backup_dir, keep_days=30)

        return backup_path

    def _cleanup_old_backups(self, backup_dir: str, keep_days: int = 30):
        """清理旧备份"""
        cutoff = datetime.now() - timedelta(days=keep_days)
        for filename in os.listdir(backup_dir):
            if not filename.startswith("app_backup_") or not filename.endswith(".db"):
                continue
            filepath = os.path.join(backup_dir, filename)
            if os.path.getmtime(filepath) < cutoff.timestamp():
                os.remove(filepath)

    def close(self):
        """关闭数据库连接"""
        if hasattr(self._local, "conn") and self._local.conn:
            self._local.conn.close()
            self._local.conn = None


# 全局数据库实例
db = Database()
