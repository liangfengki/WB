"""
产品图批量背景替换 - Flask 服务器
集成授权码系统、后台管理、安全防护
"""

import os
import json
import asyncio
import threading
import uuid
import shutil
import tempfile
import zipfile
import hashlib
import time
import re
import secrets
import ipaddress
from datetime import datetime, timedelta
from functools import wraps
from flask import (
    Flask, request, jsonify, send_from_directory,
    send_file, g, make_response
)
from config.settings import settings

# 强制将临时目录指向 /tmp 以适配 Vercel 的只读文件系统
import tempfile
if settings._is_vercel:
    tempfile.tempdir = "/tmp"

from engine.batch import BatchProcessor
from utils.logger import logger
from db.database import db

app = Flask(__name__, static_folder=None)
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024

# 安全配置
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', secrets.token_hex(32))

# 常量
UPLOAD_DIR = os.path.abspath(settings.UPLOAD_DIR)
OUTPUT_BASE = os.path.abspath(settings.OUTPUT_DIR)
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_BASE, exist_ok=True)

# 仓库根目录（server.py 位于仓库根目录），用于路径逃逸校验
WORKSPACE_ROOT = os.path.dirname(os.path.abspath(__file__))

# 联系二维码相关常量
DEFAULT_QR_PATH = "IMG_0128.PNG"
CONTACT_QR_DIR = os.path.join(UPLOAD_DIR, "contact_qr")
os.makedirs(CONTACT_QR_DIR, exist_ok=True)

# 内存任务存储
tasks_store = {}

# 管理员会话存储 (token -> {username, expires_at})
admin_sessions = {}

# 速率限制（IP -> [timestamp, ...]）
rate_limit_store = {}


# ==================== 安全中间件 ====================

@app.before_request
def security_check():
    """请求前安全检查

    - 根路径 `/`、`/static/*`、`/favicon.ico` 放行（不走黑名单、不走通用限流）
      （Req 13.4 / Req 17.1）
    - 其余路径先做黑名单拦截（403），再做每 IP 每分钟 300 次的通用限流（429）
    """
    g.request_start = time.time()

    path = request.path or ""
    static_or_root = (
        path == "/"
        or path.startswith("/static/")
        or path == "/favicon.ico"
    )

    if static_or_root:
        return  # 白名单：放行，不做黑名单/限流

    ip = _get_client_ip()

    # 1. 黑名单检查（除 /static/* 与 / 以外的路径均生效）
    if db.is_blacklisted(ip):
        return jsonify({"error": "访问被拒绝"}), 403

    # 2. 通用速率限制（每 IP 每分钟 300 次）
    if not _check_rate_limit(ip, max_requests=300, window=60):
        return jsonify({"error": "请求过于频繁，请稍后再试"}), 429

    # 3. 安全响应头在 after_request 中统一处理


@app.after_request
def add_security_headers(response):
    """添加安全响应头"""
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    response.headers['Content-Security-Policy'] = "default-src 'self' 'unsafe-inline' 'unsafe-eval' https: data: blob:;"

    # 静态资源缓存
    if request.path.startswith('/assets/') or request.path.endswith(('.css', '.js', '.png', '.jpg', '.webp', '.woff2')):
        response.headers['Cache-Control'] = 'public, max-age=86400'

    return response


def _get_client_ip() -> str:
    """获取客户端真实 IP"""
    if request.headers.get('X-Forwarded-For'):
        return request.headers.get('X-Forwarded-For').split(',')[0].strip()
    if request.headers.get('X-Real-IP'):
        return request.headers.get('X-Real-IP')
    return request.remote_addr or '127.0.0.1'


def _check_rate_limit(key: str, max_requests: int = 60, window: int = 60) -> bool:
    """简单的速率限制检查"""
    now = time.time()
    if key not in rate_limit_store:
        rate_limit_store[key] = []

    # 清理过期记录
    rate_limit_store[key] = [t for t in rate_limit_store[key] if now - t < window]

    if len(rate_limit_store[key]) >= max_requests:
        return False

    rate_limit_store[key].append(now)
    return True


def _sanitize_path(path: str) -> str:
    """清理文件路径，防止路径遍历攻击"""
    # 移除路径分隔符和特殊字符
    path = os.path.basename(path)
    # 只允许字母、数字、中文、下划线、连字符、点号
    path = re.sub(r'[^\w\u4e00-\u9fff.\-]', '', path)
    return path


def _validate_session_id(session_id: str) -> bool:
    """校验 session_id 格式（8 位十六进制）"""
    return bool(re.match(r'^[0-9a-f]{8}$', session_id))


def _validate_task_id(task_id: str) -> bool:
    """校验 task_id 格式（12 位十六进制）"""
    return bool(re.match(r'^[0-9a-f]{12}$', task_id))


# ==================== 联系二维码工具函数 ====================

# PNG / JPEG magic number
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_JPEG_MAGIC = b"\xff\xd8\xff"

# 允许的 MIME 类型与大小上限
_QR_ALLOWED_MIME = {"image/png", "image/jpeg"}
_QR_MAX_BYTES = 5 * 1024 * 1024  # 5 MB


def resolve_current_qr_path() -> str:
    """解析当前联系二维码的磁盘绝对路径。

    优先使用 system_settings.contact_qr.path；相对路径以仓库根目录
    (WORKSPACE_ROOT) 为基拼接。结果必须满足 realpath 以 WORKSPACE_ROOT
    为前缀（防路径穿越），且文件确实存在；否则回退到
    WORKSPACE_ROOT/IMG_0128.PNG。两者都不可用时抛 FileNotFoundError。
    """
    workspace_real = os.path.realpath(WORKSPACE_ROOT)

    def _is_within_workspace(abs_path: str) -> bool:
        real = os.path.realpath(abs_path)
        return real == workspace_real or real.startswith(workspace_real + os.sep)

    # 1. 尝试读取 system_settings 记录
    try:
        setting = db.get_setting("contact_qr")
    except Exception:
        setting = None

    if setting:
        value = setting.get("value") or {}
        path_value = value.get("path") if isinstance(value, dict) else None
        if isinstance(path_value, str) and path_value.strip():
            raw_path = path_value.strip()
            if os.path.isabs(raw_path):
                candidate = raw_path
            else:
                candidate = os.path.join(WORKSPACE_ROOT, raw_path)
            try:
                if os.path.isfile(candidate) and _is_within_workspace(candidate):
                    return os.path.realpath(candidate)
            except OSError:
                pass  # realpath 失败则走回退

    # 2. 回退到默认 IMG_0128.PNG
    fallback = os.path.join(WORKSPACE_ROOT, DEFAULT_QR_PATH)
    if os.path.isfile(fallback) and _is_within_workspace(fallback):
        return os.path.realpath(fallback)

    raise FileNotFoundError("尚未配置联系二维码，且默认二维码不存在")


def cleanup_old_qr(dir_path: str, keep: int = 5) -> None:
    """保留指定目录下最近 keep 个文件（按 mtime 降序），其余删除。"""
    if not os.path.isdir(dir_path):
        return
    entries = []
    for name in os.listdir(dir_path):
        full = os.path.join(dir_path, name)
        try:
            if os.path.isfile(full):
                entries.append((os.path.getmtime(full), full))
        except OSError:
            continue
    # mtime 降序：保留最新的 keep 个
    entries.sort(key=lambda x: x[0], reverse=True)
    for _, path in entries[keep:]:
        try:
            os.remove(path)
        except OSError as exc:
            logger.warning(f"清理旧二维码失败 {path}: {exc}")


def save_uploaded_qr(file_storage) -> str:
    """校验并保存管理员上传的联系二维码，返回相对 WORKSPACE_ROOT 的路径。

    校验：
      - MIME 必须属于 {image/png, image/jpeg}
      - 文件大小 ≤ 5 MB
      - 字节流 magic-number 必须与 MIME 匹配
    写入：
      - uploads/contact_qr/<uuid4>.{png|jpg}
      - realpath 必须仍在 WORKSPACE_ROOT 内
      - 同步 db.set_setting('contact_qr', {...})
      - 清理旧文件只保留最近 5 个

    违规一律抛 ValueError，由路由层转 HTTP 400/413。
    """
    if file_storage is None:
        raise ValueError("未找到上传文件")

    mimetype = (getattr(file_storage, "mimetype", "") or "").lower()
    if mimetype not in _QR_ALLOWED_MIME:
        raise ValueError("仅支持 PNG / JPEG")

    # 读取字节流
    stream = getattr(file_storage, "stream", None)
    if stream is not None:
        try:
            stream.seek(0)
        except Exception:
            pass
    blob = file_storage.read()
    if not isinstance(blob, (bytes, bytearray)):
        raise ValueError("文件内容不是合法图片")

    # 大小校验（错误文案需明确包含「图片不能超过 5MB」以便调用方识别）
    if len(blob) > _QR_MAX_BYTES:
        raise ValueError("图片不能超过 5MB")

    # magic-number 二次校验
    if mimetype == "image/png":
        if not blob.startswith(_PNG_MAGIC):
            raise ValueError("文件内容不是合法图片")
        ext = ".png"
    else:  # image/jpeg
        if not blob.startswith(_JPEG_MAGIC):
            raise ValueError("文件内容不是合法图片")
        ext = ".jpg"

    # 落盘
    os.makedirs(CONTACT_QR_DIR, exist_ok=True)
    fname = uuid.uuid4().hex + ext
    disk_path = os.path.join(CONTACT_QR_DIR, fname)

    workspace_real = os.path.realpath(WORKSPACE_ROOT)
    target_real_dir = os.path.realpath(CONTACT_QR_DIR)
    if not (target_real_dir == workspace_real or target_real_dir.startswith(workspace_real + os.sep)):
        raise ValueError("上传目录非法")

    with open(disk_path, "wb") as fh:
        fh.write(blob)

    real_disk_path = os.path.realpath(disk_path)
    if not real_disk_path.startswith(target_real_dir + os.sep) and real_disk_path != target_real_dir:
        # 理论上不会触发；防御性校验
        try:
            os.remove(disk_path)
        except OSError:
            pass
        raise ValueError("上传路径非法")

    rel_path = os.path.relpath(real_disk_path, WORKSPACE_ROOT)
    # 统一使用正斜杠，避免跨平台差异（本仓库运行在 POSIX，但保险起见）
    rel_path_posix = rel_path.replace(os.sep, "/")

    db.set_setting(
        "contact_qr",
        {"path": rel_path_posix, "updated_at": datetime.now().isoformat()},
    )

    cleanup_old_qr(CONTACT_QR_DIR, keep=5)

    return rel_path_posix


# ==================== 授权码装饰器 ====================

def require_license(f):
    """授权码验证装饰器 - 用于需要授权的 API"""
    @wraps(f)
    def decorated(*args, **kwargs):
        license_code = request.headers.get('X-License-Key', '')
        if not license_code and request.content_type and 'application/json' in request.content_type:
            data = request.get_json(silent=True)
            if data:
                license_code = data.get('license_key', '')
        # 允许通过 query string 传递授权码，方便 <img src="..."> 等无法设置 header 的场景
        if not license_code:
            license_code = request.args.get('license_key', '')

        if not license_code:
            return jsonify({"error": "请提供授权码", "code": "LICENSE_REQUIRED"}), 401

        ip = _get_client_ip()
        result = db.verify_license(license_code, ip)

        if not result["valid"]:
            return jsonify({
                "error": result["reason"],
                "code": "LICENSE_INVALID"
            }), 403

        # 记录使用
        db.record_usage(
            code=license_code,
            action=f.__name__,
            ip_address=ip,
            user_agent=request.headers.get('User-Agent', ''),
        )

        g.license_code = license_code
        g.license_info = result["info"]

        return f(*args, **kwargs)
    return decorated


def require_admin(f):
    """管理员验证装饰器"""
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get('Authorization', '').replace('Bearer ', '')
        if not token or not _verify_admin_session(token):
            return jsonify({"error": "未授权访问"}), 401
        g.admin_user = admin_sessions.get(token, {}).get('username', '')
        return f(*args, **kwargs)
    return decorated


def _create_admin_session(username: str) -> str:
    """创建管理员会话"""
    token = secrets.token_hex(32)
    admin_sessions[token] = {
        "username": username,
        "expires_at": (datetime.now() + timedelta(hours=24)).isoformat(),
    }
    return token


def _verify_admin_session(token: str) -> bool:
    """验证管理员会话"""
    if token not in admin_sessions:
        return False
    session = admin_sessions[token]
    expires = datetime.fromisoformat(session["expires_at"])
    if datetime.now() > expires:
        del admin_sessions[token]
        return False
    return True


# ==================== 错误处理 ====================

@app.errorhandler(Exception)
def handle_exception(e):
    """全局错误处理 - 统一 500 响应，不泄露内部细节

    Req 24.1 / 24.2 / 24.3 / 24.4：
      - 捕获所有未被路由函数自身捕获的异常（含 sqlite3.OperationalError）
      - 响应体只返回通用文案，不泄露堆栈 / DB 路径 / 文件系统绝对路径
      - 使用 logger.exception 将堆栈写入服务端日志供运维排查
    """
    logger.exception(f"未捕获的服务器内部错误: {type(e).__name__}: {e}")
    return jsonify({"error": "服务器内部错误，请稍后重试"}), 500


@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "资源不存在"}), 404


@app.errorhandler(413)
def request_too_large(e):
    return jsonify({"error": "上传文件过大，最大支持 500MB"}), 413


# ==================== 异步任务辅助 ====================

def run_async_in_thread(coro):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def progress_callback(task_id, filename, status, completed, total, detail):
    if task_id in tasks_store:
        tasks_store[task_id]["progress"] = {
            "completed": completed,
            "total": total,
            "percent": int((completed / total) * 100) if total > 0 else 0,
            "current_file": filename,
            "status": status,
            "detail": detail,
        }
        if "log" not in tasks_store[task_id]:
            tasks_store[task_id]["log"] = []
        tasks_store[task_id]["log"].append({
            "time": datetime.now().strftime("%H:%M:%S"),
            "file": filename,
            "status": status,
            "detail": detail,
        })
        if len(tasks_store[task_id]["log"]) > 200:
            tasks_store[task_id]["log"] = tasks_store[task_id]["log"][-200:]


def process_task(task_id, input_dir, output_dir, prompt, images_per_product, api_keys, auto_recognize, ref_bg_path=None, xhs_multi_mode=False, generations_per_source=1, user_prompt="", enable_color_harmonize=True, underwear_layering_mode=False, underwear_files=None, model_files=None):
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        tasks_store[task_id]["status"] = "processing"

        def cb(filename, status, completed, total, detail):
            progress_callback(task_id, filename, status, completed, total, detail)

        ref_bg_files = None
        if ref_bg_path and os.path.exists(ref_bg_path):
            ref_bg_files = []
            for f in sorted(os.listdir(ref_bg_path)):
                if f.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
                    ref_bg_files.append(os.path.join(ref_bg_path, f))

        processor = BatchProcessor(
            background_prompt=prompt,
            input_path=input_dir,
            output_path=output_dir,
            images_per_product=images_per_product,
            api_keys=api_keys,
            progress_callback=cb,
            auto_recognize=auto_recognize,
            ref_bg_path=ref_bg_path,
            ref_bg_files=ref_bg_files,
            xhs_multi_mode=xhs_multi_mode,
            underwear_layering_mode=underwear_layering_mode,
            underwear_files=underwear_files,
            model_files=model_files,
            generations_per_source=generations_per_source,
            user_prompt=user_prompt,
            enable_color_harmonize=enable_color_harmonize,
        )

        try:
            results = loop.run_until_complete(processor.process_all())
        finally:
            loop.close()

        success_count = sum(1 for r in results if r[0])
        failed_count = len(results) - success_count

        tasks_store[task_id]["status"] = "completed"
        tasks_store[task_id]["result"] = {
            "success": success_count,
            "failed": failed_count,
            "total": len(results),
            "output_dir": output_dir,
        }

        output_files = []
        for f in sorted(os.listdir(output_dir)):
            if f.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
                output_files.append(f)
        tasks_store[task_id]["output_files"] = output_files

        # Store pairings info for xhs_multi mode
        if xhs_multi_mode and results:
            pairings_info = []
            for success, source_filename, output_filenames in results:
                for out_file in output_filenames:
                    pairings_info.append({
                        "source": source_filename,
                        "output": out_file,
                        "status": "completed" if success else "failed",
                    })
            tasks_store[task_id]["pairings"] = pairings_info

        # Store pairings info for underwear_layering mode
        if underwear_layering_mode and results:
            pairings_info = []
            for success, source_filename, output_filenames in results:
                for out_file in output_filenames:
                    pairings_info.append({
                        "source": source_filename,
                        "output": out_file,
                        "status": "completed" if success else "failed",
                    })
            tasks_store[task_id]["pairings"] = pairings_info

        recognition_info = {}
        if hasattr(processor, 'recognition_results') and processor.recognition_results:
            for fname, rec in processor.recognition_results.items():
                recognition_info[fname] = {
                    "product_type": rec.get("product_type", "未知"),
                    "product_name": rec.get("product_name", "未知"),
                    "description": rec.get("description", ""),
                    "suitable_scenes": rec.get("suitable_scenes", []),
                }
        tasks_store[task_id]["recognition"] = recognition_info

        logger.info(f"任务 {task_id} 完成: 成功{success_count}, 失败{failed_count}")

    except Exception as e:
        logger.error(f"任务 {task_id} 失败: {str(e)}", exc_info=True)
        tasks_store[task_id]["status"] = "failed"
        tasks_store[task_id]["error"] = str(e)


# ==================== 前端页面 ====================

@app.route("/")
def index():
    """主页"""
    return send_file(os.path.join(os.path.dirname(__file__), "index.html"))


@app.route("/static/<path:filename>")
def serve_static(filename):
    """静态文件"""
    static_dir = os.path.join(os.path.dirname(__file__), "static")
    return send_file(os.path.join(static_dir, filename))


@app.route("/admin")
def admin_page():
    """后台管理页面"""
    return send_file(os.path.join(os.path.dirname(__file__), "admin.html"))


# ==================== 公开 API ====================

@app.route("/api/scenes", methods=["GET"])
def get_scenes():
    """获取预设场景列表"""
    return jsonify({"scenes": settings.SCENE_PRESETS})


@app.route("/api/proxy-sites", methods=["GET"])
def get_proxy_sites():
    """获取 API 中转站列表"""
    sites = [
        {"id": "yunwu", "name": "云雾AI", "description": "稳定高速的AI中转站", "base_url": "https://api.yunwu.ai/v1", "models": ["gemini-2.5-flash-preview-05-20", "gpt-4o", "claude-3-5-sonnet"]},
        {"id": "custom", "name": "自定义", "description": "填写你自己的 API 地址", "base_url": "", "models": []},
    ]
    return jsonify({"sites": sites})


@app.route("/api/session-files/<session_id>", methods=["GET"])
def get_session_files(session_id):
    """获取 session 已上传文件列表（仅顶层文件 = WB 产品图）"""
    if not _validate_session_id(session_id):
        return jsonify({"error": "无效的 session ID"}), 400
    upload_dir = os.path.join(UPLOAD_DIR, session_id)
    files = []
    if os.path.exists(upload_dir):
        for f in os.listdir(upload_dir):
            full_path = os.path.join(upload_dir, f)
            if os.path.isfile(full_path) and not f.startswith('.'):
                files.append({
                    "name": f,
                    "size": os.path.getsize(full_path),
                    "path": f"/api/preview/{session_id}/{f}"
                })
    return jsonify({"files": files})


@app.route("/api/license/verify", methods=["POST"])
def verify_license_api():
    """验证授权码（无需已验证的授权码）"""
    data = request.json or {}
    code = data.get("license_key", "").strip()

    if not code:
        return jsonify({"valid": False, "reason": "请输入授权码"})

    ip = _get_client_ip()
    result = db.verify_license(code, ip)
    return jsonify(result)


@app.route("/api/license/info", methods=["POST"])
def license_info():
    """获取授权码详情"""
    data = request.json or {}
    code = data.get("license_key", "").strip()

    if not code:
        return jsonify({"error": "请输入授权码"}), 400

    info = db.get_license(code)
    if not info:
        return jsonify({"error": "授权码不存在"}), 404

    # 不返回敏感信息
    return jsonify({
        "code": info["code"][:4] + "****" + info["code"][-4:],
        "type": info["type"],
        "status": info["status"],
        "max_daily_uses": info["max_daily_uses"],
        "total_uses": info["total_uses"],
        "expires_at": info["expires_at"],
        "activated_at": info["activated_at"],
    })


@app.route("/api/license/trial", methods=["POST"])
def request_trial():
    """自助试用已下线；保留端点返回 410 避免老前端 404（Req 1.4 / 1.5）"""
    return jsonify({
        "error": "自助试用已关闭，请扫码联系管理员获取授权码",
        "code": "TRIAL_DISABLED"
    }), 410


@app.route("/api/contact-qr", methods=["GET"])
def public_contact_qr():
    """公开的联系二维码接口 - 访客扫码联系管理员（Req 2.1 ~ 2.6）

    - 不走 require_license / require_admin；但仍受 before_request 的
      黑名单与通用限流保护。
    - 调用 resolve_current_qr_path() 获取当前二维码的磁盘绝对路径；
      以后缀推断 MIME（png / jpeg），并允许浏览器缓存 3600 秒。
    - 文件不存在时返回 404。
    """
    try:
        abs_path = resolve_current_qr_path()
    except FileNotFoundError:
        return jsonify({"error": "尚未配置联系二维码"}), 404

    ext = os.path.splitext(abs_path)[1].lower()
    if ext in (".jpg", ".jpeg"):
        mimetype = "image/jpeg"
    else:
        # 默认按 PNG 处理（包含 .png 以及未知扩展名）
        mimetype = "image/png"

    return send_file(abs_path, mimetype=mimetype, max_age=3600)


# ==================== 授权 API（需要授权码） ====================

@app.route("/api/upload", methods=["POST"])
@require_license
def upload_files():
    """批量上传文件"""
    if "files" not in request.files:
        return jsonify({"error": "未找到上传文件"}), 400

    files = request.files.getlist("files")
    if not files:
        return jsonify({"error": "没有选择文件"}), 400

    session_id = str(uuid.uuid4())[:8]
    upload_dir = os.path.join(UPLOAD_DIR, session_id)
    os.makedirs(upload_dir, exist_ok=True)

    saved = []
    for f in files:
        if f.filename:
            safe_name = _sanitize_path(f.filename)
            if not safe_name:
                continue
            save_path = os.path.join(upload_dir, safe_name)
            f.save(save_path)
            saved.append(safe_name)

    return jsonify({
        "session_id": session_id,
        "files": saved,
        "count": len(saved),
        "input_dir": upload_dir,
    })


@app.route("/api/upload/<session_id>/<filename>", methods=["DELETE"])
@app.route("/api/upload/<session_id>/<scope>/<filename>", methods=["DELETE"])
@require_license
def delete_uploaded_file(session_id, filename, scope=None):
    """删除已上传文件"""
    if not _validate_session_id(session_id):
        return jsonify({"error": "无效的会话ID"}), 400

    if scope and scope not in {"xhs_source", "underwear", "underwear_model"}:
        return jsonify({"error": "无效的 scope"}), 400

    safe_name = _sanitize_path(filename)
    if not safe_name:
        return jsonify({"error": "无效的文件名"}), 400

    file_path = os.path.join(UPLOAD_DIR, session_id, scope, safe_name) if scope else os.path.join(UPLOAD_DIR, session_id, safe_name)

    # 安全校验：确保路径在 UPLOAD_DIR 下
    real_path = os.path.realpath(file_path)
    if not real_path.startswith(os.path.realpath(UPLOAD_DIR)):
        return jsonify({"error": "非法路径"}), 403

    if os.path.exists(real_path):
        try:
            os.remove(real_path)
            return jsonify({"success": True, "message": "删除成功"})
        except Exception as e:
            return jsonify({"error": f"删除失败: {str(e)}"}), 500
    return jsonify({"error": "文件不存在"}), 404


@app.route("/api/upload-preview", methods=["POST"])
@require_license
def upload_preview():
    """上传并预览文件"""
    if "files" not in request.files:
        return jsonify({"error": "未找到上传文件"}), 400

    files = request.files.getlist("files")
    if not files:
        return jsonify({"error": "没有选择文件"}), 400

    session_id = request.form.get("session_id", "")
    if session_id and not _validate_session_id(session_id):
        return jsonify({"error": "无效的会话ID"}), 400

    if not session_id:
        session_id = str(uuid.uuid4())[:8]

    # scope 用于隔离不同模式的上传目录；默认 wb 落顶层，xhs 人物图落子目录
    scope = request.form.get("scope", "").strip()
    if scope and scope not in {"xhs_source", "underwear", "underwear_model"}:
        return jsonify({"error": "无效的 scope"}), 400

    session_root = os.path.join(UPLOAD_DIR, session_id)
    upload_dir = os.path.join(session_root, scope) if scope else session_root
    os.makedirs(upload_dir, exist_ok=True)

    for f in files:
        if f.filename:
            safe_name = _sanitize_path(f.filename)
            if not safe_name:
                continue
            save_path = os.path.join(upload_dir, safe_name)
            f.save(save_path)

    # 扫描目录获取当前 scope 下的所有文件
    preview_prefix = f"/api/preview/{session_id}/{scope}/" if scope else f"/api/preview/{session_id}/"
    all_files = []
    for f in os.listdir(upload_dir):
        full_path = os.path.join(upload_dir, f)
        if os.path.isfile(full_path) and not f.startswith('.'):
            file_size = os.path.getsize(full_path)
            all_files.append({
                "name": f,
                "size": file_size,
                "path": f"{preview_prefix}{f}"
            })

    return jsonify({
        "session_id": session_id,
        "input_dir": upload_dir,
        "files": all_files,
        "count": len(all_files),
        "scope": scope or "",
    })


@app.route("/api/upload-reference", methods=["POST"])
@require_license
def upload_reference():
    """上传参考背景图"""
    if "files" not in request.files:
        return jsonify({"error": "未找到上传文件"}), 400

    files = request.files.getlist("files")
    if not files:
        return jsonify({"error": "没有选择文件"}), 400

    session_id = request.form.get("session_id", "")
    if session_id and not _validate_session_id(session_id):
        return jsonify({"error": "无效的会话ID"}), 400

    if not session_id:
        session_id = str(uuid.uuid4())[:8]

    ref_dir = os.path.join(UPLOAD_DIR, session_id, "reference")
    os.makedirs(ref_dir, exist_ok=True)

    for f in files:
        if f.filename:
            safe_name = _sanitize_path(f.filename)
            if not safe_name:
                continue
            save_path = os.path.join(ref_dir, safe_name)
            f.save(save_path)

    all_files = []
    for f in os.listdir(ref_dir):
        full_path = os.path.join(ref_dir, f)
        if os.path.isfile(full_path) and not f.startswith('.'):
            file_size = os.path.getsize(full_path)
            all_files.append({
                "name": f,
                "size": file_size,
                "path": f"/api/preview-ref/{session_id}/{f}"
            })

    return jsonify({
        "session_id": session_id,
        "ref_dir": ref_dir,
        "files": all_files,
        "count": len(all_files)
    })


@app.route("/api/preview-ref/<session_id>/<filename>")
@require_license
def preview_ref_image(session_id, filename):
    """预览参考背景图"""
    if not _validate_session_id(session_id):
        return jsonify({"error": "无效的会话ID"}), 400

    safe_name = _sanitize_path(filename)
    if not safe_name:
        return jsonify({"error": "无效的文件名"}), 400

    ref_dir = os.path.join(UPLOAD_DIR, session_id, "reference")

    real_path = os.path.realpath(os.path.join(ref_dir, safe_name))
    if not real_path.startswith(os.path.realpath(UPLOAD_DIR)):
        return jsonify({"error": "非法路径"}), 403

    return send_from_directory(ref_dir, safe_name)


@app.route("/api/preview/<session_id>/<filename>")
@app.route("/api/preview/<session_id>/<scope>/<filename>")
@require_license
def preview_image(session_id, filename, scope=None):
    """预览已上传图片"""
    if not _validate_session_id(session_id):
        return jsonify({"error": "无效的会话ID"}), 400

    if scope and scope not in {"xhs_source", "underwear", "underwear_model"}:
        return jsonify({"error": "无效的 scope"}), 400

    safe_name = _sanitize_path(filename)
    if not safe_name:
        return jsonify({"error": "无效的文件名"}), 400

    upload_dir = os.path.join(UPLOAD_DIR, session_id, scope) if scope else os.path.join(UPLOAD_DIR, session_id)

    # 安全校验
    real_path = os.path.realpath(os.path.join(upload_dir, safe_name))
    if not real_path.startswith(os.path.realpath(UPLOAD_DIR)):
        return jsonify({"error": "非法路径"}), 403

    return send_from_directory(upload_dir, safe_name)


@app.route("/api/process", methods=["POST"])
@require_license
def start_process():
    """启动批量处理任务"""
    data = request.json
    if not data:
        return jsonify({"error": "请提供处理参数"}), 400

    input_dir = data.get("input_dir")
    prompt = data.get("prompt", "")
    images_per_product = int(data.get("images_per_product", 3))
    mode = data.get("mode", "wb")

    ALLOWED_MODES = {"wb", "xhs_multi", "underwear_layering"}
    if mode not in ALLOWED_MODES:
        return jsonify({"error": f"不支持的 mode: {mode}"}), 400

    ref_bg_dir = data.get("ref_bg_dir", "")

    api_key_input = data.get("api_key", "")
    if api_key_input:
        api_keys = [k.strip() for k in api_key_input.split(",") if k.strip()]
    else:
        api_keys = settings.YUNWU_API_KEYS

    if not api_keys:
        return jsonify({"error": "请提供 API Key"}), 400

    # Default values for mode-specific parameters
    user_prompt = ""
    prompt_truncated = False
    generations_per_source = 1

    output_name = data.get("output_name", datetime.now().strftime("output_%Y%m%d_%H%M%S"))
    auto_recognize = data.get("auto_recognize", False)
    enable_color_harmonize = data.get("enable_color_harmonize", True)

    if mode != "underwear_layering" and (not input_dir or not os.path.exists(input_dir)):
        return jsonify({"error": "输入目录不存在，请先上传文件"}), 400

    if mode == "xhs_multi":
        # Parse xhs_multi specific parameters
        generations_per_source = min(max(int(data.get("generations_per_source", 1)), 1), 5)
        user_prompt = data.get("user_prompt", "")

        # Truncate user_prompt if needed
        from engine.prompt_builder import PromptBuilder
        user_prompt, prompt_truncated = PromptBuilder.truncate_user_prompt(user_prompt)

        # Validate ref_bg_dir exists and contains valid image files
        if not ref_bg_dir or not os.path.exists(ref_bg_dir):
            return jsonify({"error": "参考背景图目录不存在，请先上传参考背景图"}), 400

        valid_extensions = (".png", ".jpg", ".jpeg", ".webp")
        ref_files = [f for f in os.listdir(ref_bg_dir) if f.lower().endswith(valid_extensions) and os.path.isfile(os.path.join(ref_bg_dir, f))]
        if not ref_files:
            return jsonify({"error": "参考背景图目录中没有有效的图片文件"}), 400

        # Validate source image count <= 50
        source_files = [f for f in os.listdir(input_dir) if f.lower().endswith(valid_extensions) and os.path.isfile(os.path.join(input_dir, f))]
        if len(source_files) > 50:
            return jsonify({"error": "人物图数量超出限制（最多50张）"}), 400

        # Validate reference image count <= 20
        if len(ref_files) > 20:
            return jsonify({"error": "参考背景图数量超出限制（最多20张）"}), 400

        # Validate individual file sizes <= 20 MB
        max_file_size = 20 * 1024 * 1024  # 20 MB
        for f in source_files:
            file_path = os.path.join(input_dir, f)
            if os.path.getsize(file_path) > max_file_size:
                return jsonify({"error": f"文件 {f} 大小超出限制（最大20MB）"}), 400
        for f in ref_files:
            file_path = os.path.join(ref_bg_dir, f)
            if os.path.getsize(file_path) > max_file_size:
                return jsonify({"error": f"文件 {f} 大小超出限制（最大20MB）"}), 400

        prompt = "xhs_multi_mode"
        images_per_product = 1

    elif mode == "underwear_layering":
        # Parse underwear_layering specific parameters
        generations_per_source = min(max(int(data.get("generations_per_source", 1)), 1), 5)
        user_prompt = data.get("user_prompt", "")

        from engine.prompt_builder import PromptBuilder
        user_prompt, prompt_truncated = PromptBuilder.truncate_user_prompt(user_prompt)

        # Validate underwear and model directories
        underwear_dir = data.get("underwear_dir", "")
        model_dir = data.get("model_dir", "")

        if not underwear_dir or not os.path.exists(underwear_dir):
            return jsonify({"error": "内衣图目录不存在，请先上传内衣图"}), 400
        if not model_dir or not os.path.exists(model_dir):
            return jsonify({"error": "模特图目录不存在，请先上传模特图"}), 400

        valid_extensions = (".png", ".jpg", ".jpeg", ".webp")
        uw_files = [f for f in os.listdir(underwear_dir) if f.lower().endswith(valid_extensions) and os.path.isfile(os.path.join(underwear_dir, f))]
        md_files = [f for f in os.listdir(model_dir) if f.lower().endswith(valid_extensions) and os.path.isfile(os.path.join(model_dir, f))]

        if not uw_files:
            return jsonify({"error": "内衣图目录中没有有效的图片文件"}), 400
        if not md_files:
            return jsonify({"error": "模特图目录中没有有效的图片文件"}), 400

        # Validate counts
        if len(uw_files) > 20:
            return jsonify({"error": "内衣图数量超出限制（最多20张）"}), 400
        if len(md_files) > 20:
            return jsonify({"error": "模特图数量超出限制（最多20张）"}), 400

        # Validate file sizes
        max_file_size = 20 * 1024 * 1024
        for f in uw_files:
            fp = os.path.join(underwear_dir, f)
            if os.path.getsize(fp) > max_file_size:
                return jsonify({"error": f"内衣图 {f} 大小超出限制（最大20MB）"}), 400
        for f in md_files:
            fp = os.path.join(model_dir, f)
            if os.path.getsize(fp) > max_file_size:
                return jsonify({"error": f"模特图 {f} 大小超出限制（最大20MB）"}), 400

        prompt = "underwear_layering_mode"
        images_per_product = 1

        # Build file lists now while underwear_dir/model_dir are in scope
        _underwear_layering_mode = True
        _underwear_files = [os.path.join(underwear_dir, f) for f in sorted(os.listdir(underwear_dir)) if f.lower().endswith(valid_extensions)]
        _model_files = [os.path.join(model_dir, f) for f in sorted(os.listdir(model_dir)) if f.lower().endswith(valid_extensions)]

    else:
        if not prompt.strip() and not auto_recognize:
            return jsonify({"error": "请输入场景描述或开启自动识别"}), 400

    output_dir = os.path.join(OUTPUT_BASE, output_name)
    os.makedirs(output_dir, exist_ok=True)

    task_id = uuid.uuid4().hex[:12]
    task_entry = {
        "status": "pending",
        "progress": {"completed": 0, "total": 0, "percent": 0, "current_file": "", "status": "", "detail": ""},
        "log": [],
        "output_files": [],
        "output_dir": output_dir,
        "created_at": datetime.now().isoformat(),
        "auto_recognize": auto_recognize,
        "license_code": g.license_code,
        "mode": mode,
    }

    # Store xhs_multi specific fields
    if mode == "xhs_multi":
        task_entry["generations_per_source"] = generations_per_source
        task_entry["user_prompt"] = user_prompt
        task_entry["prompt_truncated"] = prompt_truncated

    # Store underwear_layering specific fields
    if mode == "underwear_layering":
        task_entry["user_prompt"] = user_prompt
        task_entry["prompt_truncated"] = prompt_truncated

    tasks_store[task_id] = task_entry

    # Determine ref_bg_path for process_task
    if mode == "xhs_multi":
        _ref_bg_path = ref_bg_dir
    else:  # wb, underwear_layering
        _ref_bg_path = None

    # Determine xhs_multi kwargs
    _xhs_multi_mode = (mode == "xhs_multi")
    _generations_per_source = generations_per_source if mode in ("xhs_multi", "underwear_layering") else 1
    _enable_color_harmonize = enable_color_harmonize if _xhs_multi_mode else True

    # Determine user_prompt (shared by xhs_multi and underwear_layering)
    _user_prompt = user_prompt if mode in ("xhs_multi", "underwear_layering") else ""

    # Determine underwear_layering kwargs (already set if mode == "underwear_layering")
    if mode != "underwear_layering":
        _underwear_layering_mode = False
        _underwear_files = None
        _model_files = None

    # Vercel 环境同步处理，否则异步线程
    if os.getenv("VERCEL") == "1" or os.getenv("AWS_EXECUTION_ENV"):
        try:
            process_task(task_id, input_dir, output_dir, prompt, images_per_product, api_keys, auto_recognize, _ref_bg_path, _xhs_multi_mode, _generations_per_source, _user_prompt, _enable_color_harmonize, _underwear_layering_mode, _underwear_files, _model_files)
            return jsonify({
                "task_id": task_id,
                "status": tasks_store[task_id]["status"],
                "result": tasks_store[task_id].get("result"),
                "output_files": tasks_store[task_id].get("output_files", []),
                "recognition": tasks_store[task_id].get("recognition", {}),
            })
        except Exception as e:
            return jsonify({"error": f"处理失败: {str(e)}"}), 500
    else:
        thread = threading.Thread(
            target=process_task,
            args=(task_id, input_dir, output_dir, prompt, images_per_product, api_keys, auto_recognize, _ref_bg_path, _xhs_multi_mode, _generations_per_source, _user_prompt, _enable_color_harmonize, _underwear_layering_mode, _underwear_files, _model_files),
            daemon=True,
        )
        thread.start()
        return jsonify({"task_id": task_id, "status": "pending"})


@app.route("/api/task/<task_id>", methods=["GET"])
@require_license
def get_task_status(task_id):
    """查询任务状态"""
    if not _validate_task_id(task_id):
        return jsonify({"error": "无效的任务ID"}), 400

    if task_id not in tasks_store:
        return jsonify({"error": "任务不存在"}), 404

    task = tasks_store[task_id]
    response_data = {
        "task_id": task_id,
        "status": task["status"],
        "progress": task.get("progress", {}),
        "result": task.get("result"),
        "error": task.get("error"),
        "output_files": task.get("output_files", []),
        "log": task.get("log", [])[-20:],
        "recognition": task.get("recognition", {}),
        "auto_recognize": task.get("auto_recognize", False),
    }

    # Include xhs_multi specific fields if present
    if task.get("mode") == "xhs_multi":
        response_data["pairings"] = task.get("pairings", [])
        response_data["generations_per_source"] = task.get("generations_per_source", 1)
        response_data["prompt_truncated"] = task.get("prompt_truncated", False)

    # Include underwear_layering specific fields if present
    if task.get("mode") == "underwear_layering":
        response_data["pairings"] = task.get("pairings", [])
        response_data["prompt_truncated"] = task.get("prompt_truncated", False)

    return jsonify(response_data)


@app.route("/api/task/<task_id>/log", methods=["GET"])
@require_license
def get_task_log(task_id):
    """获取任务日志"""
    if not _validate_task_id(task_id):
        return jsonify({"error": "无效的任务ID"}), 400

    if task_id not in tasks_store:
        return jsonify({"error": "任务不存在"}), 404

    task = tasks_store[task_id]
    return jsonify({"log": task.get("log", [])})


@app.route("/api/output/<task_id>/<filename>")
@require_license
def get_output_image(task_id, filename):
    """获取输出图片"""
    if not _validate_task_id(task_id):
        return jsonify({"error": "无效的任务ID"}), 400

    safe_name = _sanitize_path(filename)
    if not safe_name:
        return jsonify({"error": "无效的文件名"}), 400

    # 允许在重启后通过目录名继续访问历史任务的输出
    if task_id in tasks_store:
        output_dir = tasks_store[task_id].get("output_dir", "")
    else:
        output_dir = os.path.join(OUTPUT_BASE, task_id)

    if not output_dir or not os.path.exists(output_dir):
        return jsonify({"error": "输出目录不存在"}), 404

    # 安全校验
    real_path = os.path.realpath(os.path.join(output_dir, safe_name))
    if not real_path.startswith(os.path.realpath(OUTPUT_BASE)):
        return jsonify({"error": "非法路径"}), 403

    return send_from_directory(output_dir, safe_name)


@app.route("/api/output/task/<task_id>", methods=["DELETE"])
@require_license
def delete_output_task(task_id):
    """删除整个任务及其所有输出文件"""
    if not _validate_task_id(task_id):
        return jsonify({"error": "无效的任务ID"}), 400

    if task_id in tasks_store:
        output_dir = tasks_store[task_id].get("output_dir", "")
        del tasks_store[task_id]
    else:
        output_dir = os.path.join(OUTPUT_BASE, task_id)
        if not os.path.exists(output_dir):
            return jsonify({"error": "任务不存在"}), 404

    real_path = os.path.realpath(output_dir)
    if not real_path.startswith(os.path.realpath(OUTPUT_BASE)):
        return jsonify({"error": "非法路径"}), 403

    if os.path.exists(real_path):
        try:
            shutil.rmtree(real_path)
            return jsonify({"success": True, "message": "删除成功"})
        except Exception as e:
            return jsonify({"error": f"删除失败: {str(e)}"}), 500

    return jsonify({"error": "文件夹不存在"}), 404


@app.route("/api/output/<task_id>/<filename>", methods=["DELETE"])
@require_license
def delete_output_file(task_id, filename):
    """删除输出文件"""
    if not _validate_task_id(task_id):
        return jsonify({"error": "无效的任务ID"}), 400

    safe_name = _sanitize_path(filename)
    if not safe_name:
        return jsonify({"error": "无效的文件名"}), 400

    # 允许通过文件夹路径删除已从内存中过期的历史任务文件
    if task_id in tasks_store:
        output_dir = tasks_store[task_id].get("output_dir", "")
    else:
        output_dir = os.path.join(OUTPUT_BASE, task_id)
        if not os.path.exists(output_dir):
            return jsonify({"error": "任务不存在"}), 404

    file_path = os.path.join(output_dir, safe_name)

    # 安全校验
    real_path = os.path.realpath(file_path)
    if not real_path.startswith(os.path.realpath(OUTPUT_BASE)):
        return jsonify({"error": "非法路径"}), 403

    if os.path.exists(real_path):
        try:
            os.remove(real_path)
            return jsonify({"success": True, "message": "删除成功"})
        except Exception as e:
            return jsonify({"error": f"删除失败: {str(e)}"}), 500
    return jsonify({"error": "文件不存在"}), 404


@app.route("/api/download/<task_id>", methods=["GET"])
@require_license
def download_results(task_id):
    """下载结果 ZIP 包"""
    if not _validate_task_id(task_id):
        return jsonify({"error": "无效的任务ID"}), 400

    if task_id not in tasks_store:
        return jsonify({"error": "任务不存在"}), 404

    output_dir = tasks_store[task_id].get("output_dir", "")
    if not output_dir or not os.path.exists(output_dir):
        return jsonify({"error": "输出目录不存在"}), 404

    temp_dir = tempfile.mkdtemp()
    zip_path = os.path.join(temp_dir, f"results_{task_id}.zip")

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in os.listdir(output_dir):
            if f.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
                zf.write(os.path.join(output_dir, f), f)

    return send_file(
        zip_path,
        as_attachment=True,
        download_name=f"results_{task_id}.zip",
        mimetype="application/zip",
    )


@app.route("/api/history", methods=["GET"])
@require_license
def get_history():
    """获取历史任务"""
    results = []
    for task_id, task in tasks_store.items():
        # 只返回当前授权码的任务
        if task.get("license_code") == g.license_code:
            results.append({
                "task_id": task_id,
                "status": task["status"],
                "created_at": task.get("created_at", ""),
                "output_files": task.get("output_files", []),
                "result": task.get("result"),
            })
    return jsonify({"tasks": results})


@app.route("/api/check-api", methods=["POST"])
@require_license
def check_api():
    """检查 API Key 是否有效"""
    data = request.json or {}
    api_key_input = data.get("api_key", "")
    api_keys = [k.strip() for k in api_key_input.split(",") if k.strip()] if api_key_input else settings.YUNWU_API_KEYS

    if not api_keys:
        return jsonify({"valid": False, "message": "API Key未设置"})
    return jsonify({"valid": True, "message": "API Key已配置"})


# ==================== 后台管理 API ====================

@app.route("/api/admin/login", methods=["POST"])
def admin_login():
    """管理员登录"""
    data = request.json or {}
    username = data.get("username", "").strip()
    password = data.get("password", "")

    if not username or not password:
        return jsonify({"error": "请输入用户名和密码"}), 400

    # 速率限制
    ip = _get_client_ip()
    if not _check_rate_limit(f"login_{ip}", max_requests=5, window=300):
        return jsonify({"error": "登录尝试次数过多，请5分钟后重试"}), 429

    if db.verify_admin(username, password):
        token = _create_admin_session(username)
        logger.info(f"管理员 {username} 登录成功 (IP: {ip})")
        return jsonify({"token": token, "username": username})
    else:
        logger.warning(f"管理员登录失败: {username} (IP: {ip})")
        return jsonify({"error": "用户名或密码错误"}), 401


@app.route("/api/admin/change-password", methods=["POST"])
@require_admin
def admin_change_password():
    """修改管理员密码"""
    data = request.json or {}
    old_password = data.get("old_password", "")
    new_password = data.get("new_password", "")

    if not old_password or not new_password:
        return jsonify({"error": "请输入旧密码和新密码"}), 400

    if len(new_password) < 8:
        return jsonify({"error": "新密码长度不能少于8位"}), 400

    if db.change_admin_password(g.admin_user, old_password, new_password):
        return jsonify({"success": True, "message": "密码修改成功"})
    return jsonify({"error": "旧密码错误"}), 400


# --- 授权码管理 ---

@app.route("/api/admin/licenses", methods=["GET"])
@require_admin
def admin_list_licenses():
    """获取授权码列表

    支持过滤参数：
      - ``status``：精确匹配授权码状态
      - ``type``：精确匹配授权码类型
      - ``keyword``：按 ``code`` 或 ``remark`` 模糊匹配（Req 8.2）
      - ``page`` / ``per_page``：分页
    """
    status = request.args.get("status")
    code_type = request.args.get("type")
    keyword = request.args.get("keyword")
    page = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", 20))

    result = db.list_licenses(
        status=status,
        code_type=code_type,
        page=page,
        per_page=per_page,
        keyword=keyword,
    )
    return jsonify(result)


@app.route("/api/admin/licenses", methods=["POST"])
@require_admin
def admin_create_license():
    """创建授权码（单个或批量）

    合法性校验（Req 9.1 / 9.4 / 9.5）：
      - ``type`` 必须属于 ``{trial, monthly, yearly, lifetime}``
      - ``max_daily_uses`` 必须 ≥ 1
      - ``count`` 必须 ≥ 1；大于 100 按表单约束截断为 100（Req 9.5）
    """
    ALLOWED_TYPES = {"trial", "monthly", "yearly", "lifetime"}

    data = request.json or {}
    code_type = data.get("type", "trial")

    try:
        count = int(data.get("count", 1))
    except (TypeError, ValueError):
        return jsonify({"error": "count 必须是整数"}), 400
    try:
        max_daily_uses = int(data.get("max_daily_uses", 50))
    except (TypeError, ValueError):
        return jsonify({"error": "max_daily_uses 必须是整数"}), 400

    if code_type not in ALLOWED_TYPES:
        return jsonify({"error": "授权码类型非法"}), 400
    if count < 1:
        return jsonify({"error": "count 必须 ≥ 1"}), 400
    if max_daily_uses < 1:
        return jsonify({"error": "max_daily_uses 必须 ≥ 1"}), 400

    # 与 admin.html 表单上限一致：一次最多创建 100 个
    count = min(count, 100)

    expires_days = data.get("expires_days")
    if expires_days is not None:
        try:
            expires_days = int(expires_days)
        except (TypeError, ValueError):
            return jsonify({"error": "expires_days 必须是整数"}), 400

    remark = data.get("remark", "")

    if count == 1:
        license_info = db.create_license(
            code_type=code_type,
            max_daily_uses=max_daily_uses,
            expires_days=expires_days,
            remark=remark,
            created_by=g.admin_user,
        )
        return jsonify(license_info), 201
    else:
        results = db.batch_create_licenses(
            count=count,
            code_type=code_type,
            max_daily_uses=max_daily_uses,
            expires_days=expires_days,
            remark=remark,
            created_by=g.admin_user,
        )
        return jsonify({"created": len(results), "licenses": results}), 201


@app.route("/api/admin/licenses/<code>/revoke", methods=["POST"])
@require_admin
def admin_revoke_license(code):
    """吊销授权码"""
    if db.revoke_license(code):
        return jsonify({"success": True, "message": "授权码已吊销"})
    return jsonify({"error": "授权码不存在"}), 404


@app.route("/api/admin/licenses/<code>", methods=["DELETE"])
@require_admin
def admin_delete_license(code):
    """删除授权码"""
    if db.delete_license(code):
        return jsonify({"success": True, "message": "授权码已删除"})
    return jsonify({"error": "授权码不存在"}), 404


# --- 统计信息 ---

@app.route("/api/admin/stats/overview", methods=["GET"])
@require_admin
def admin_stats_overview():
    """获取总览统计"""
    return jsonify(db.get_overview_stats())


@app.route("/api/admin/stats/daily", methods=["GET"])
@require_admin
def admin_stats_daily():
    """获取每日统计"""
    date = request.args.get("date")
    days = int(request.args.get("days", 7))
    return jsonify(db.get_daily_stats(date_str=date, days=days))


# --- 使用日志 ---

@app.route("/api/admin/logs", methods=["GET"])
@require_admin
def admin_logs():
    """获取使用日志

    支持过滤参数：
      - ``license_code``：精确匹配
      - ``ip_address``：精确匹配（Req 11.2）
      - ``action``：精确匹配（Req 11.2）
      - ``date_from`` / ``date_to``：``created_at`` 闭区间（Req 11.2）
      - ``page`` / ``per_page``：分页
    """
    license_code = request.args.get("license_code")
    ip_address = request.args.get("ip_address")
    action = request.args.get("action")
    date_from = request.args.get("date_from")
    date_to = request.args.get("date_to")

    try:
        page = int(request.args.get("page", 1))
        per_page = int(request.args.get("per_page", 50))
    except (TypeError, ValueError):
        return jsonify({"error": "page / per_page 必须是整数"}), 400

    return jsonify(
        db.get_usage_logs(
            license_code=license_code,
            ip_address=ip_address,
            action=action,
            date_from=date_from,
            date_to=date_to,
            page=page,
            per_page=per_page,
        )
    )


# --- 黑名单管理 ---

@app.route("/api/admin/blacklist", methods=["GET"])
@require_admin
def admin_list_blacklist():
    """获取黑名单列表"""
    return jsonify(db.list_blacklist())


@app.route("/api/admin/blacklist", methods=["POST"])
@require_admin
def admin_add_blacklist():
    """添加 IP 到黑名单（校验合法 IPv4/IPv6，Req 13.2）"""
    data = request.json or {}
    ip_address = data.get("ip_address", "").strip()
    reason = data.get("reason", "")

    if not ip_address:
        return jsonify({"error": "请输入 IP 地址"}), 400

    try:
        ipaddress.ip_address(ip_address)
    except ValueError:
        return jsonify({"error": "IP 地址格式非法"}), 400

    if db.add_to_blacklist(ip_address, reason):
        return jsonify({"success": True, "message": f"已将 {ip_address} 加入黑名单"})
    return jsonify({"error": "该 IP 已在黑名单中"}), 400


@app.route("/api/admin/blacklist/<ip_address>", methods=["DELETE"])
@require_admin
def admin_remove_blacklist(ip_address):
    """从黑名单移除 IP"""
    if db.remove_from_blacklist(ip_address):
        return jsonify({"success": True, "message": f"已将 {ip_address} 移出黑名单"})
    return jsonify({"error": "该 IP 不在黑名单中"}), 404


# --- 数据库备份 ---

def _latest_backup_path() -> "str | None":
    """返回 data/backups/ 下最新的备份文件绝对路径，无则返回 None。"""
    backup_dir = os.path.join(WORKSPACE_ROOT, "data", "backups")
    if not os.path.isdir(backup_dir):
        return None
    files = []
    for name in os.listdir(backup_dir):
        if not name.startswith("app_backup_") or not name.endswith(".db"):
            continue
        full = os.path.join(backup_dir, name)
        try:
            if os.path.isfile(full):
                files.append(full)
        except OSError:
            continue
    if not files:
        return None
    return max(files, key=lambda p: os.path.getmtime(p))


@app.route("/api/admin/backup", methods=["POST"])
@require_admin
def admin_backup():
    """手动触发一次数据库备份，返回备份文件相对路径。"""
    try:
        backup_path = db.backup()
    except Exception as e:
        logger.exception("数据库备份失败")
        return jsonify({"error": f"备份失败: {str(e)}"}), 500

    # 返回相对路径，避免泄露服务器绝对路径
    try:
        rel = os.path.relpath(backup_path, WORKSPACE_ROOT)
    except ValueError:
        rel = backup_path
    return jsonify({"success": True, "message": "备份成功", "path": rel})


@app.route("/api/admin/backup/download", methods=["GET"])
@require_admin
def admin_backup_download():
    """下载最新一次已生成的数据库备份（不再重新生成）。

    - 若还没有任何备份：返回 404，提示先调用 ``POST /api/admin/backup``
    - 必须满足 realpath 以 ``WORKSPACE_ROOT`` 为前缀（Req 14.3）
    """
    path = _latest_backup_path()
    if not path:
        return jsonify({"error": "尚无备份，请先执行 POST /api/admin/backup"}), 404

    real = os.path.realpath(path)
    workspace_real = os.path.realpath(WORKSPACE_ROOT)
    if not (real == workspace_real or real.startswith(workspace_real + os.sep)):
        return jsonify({"error": "备份文件路径非法"}), 404

    if not os.path.isfile(real):
        return jsonify({"error": "备份文件不存在"}), 404

    return send_file(
        real,
        as_attachment=True,
        download_name=os.path.basename(real),
        mimetype="application/octet-stream",
    )


@app.route("/api/admin/licenses/<code>/extend", methods=["POST"])
@require_admin
def admin_extend_license(code):
    """延期授权码（Req 10.3 / 10.5 / 10.6 / 22.2）

    - ``extra_days`` 必须可解析为整数且位于 ``[1, 3650]``，否则 400
    - ``code`` 不存在或类型为 ``lifetime`` → 404
    - 成功 → 返回 ``db.extend_license`` 的完整更新行
    """
    data = request.get_json(silent=True) or {}
    raw = data.get("extra_days", None)
    # 拒绝布尔值（Python 中 True/False 是 int 的子类）
    if isinstance(raw, bool):
        return jsonify({"error": "extra_days 非法"}), 400
    try:
        extra_days = int(raw)
    except (TypeError, ValueError):
        return jsonify({"error": "extra_days 非法"}), 400
    if not (1 <= extra_days <= 3650):
        return jsonify({"error": "extra_days 必须在 [1, 3650] 之间"}), 400

    try:
        updated = db.extend_license(code, extra_days)
    except ValueError:
        return jsonify({"error": "extra_days 非法"}), 400

    if updated is None:
        return jsonify({"error": "授权码不存在或为永久授权"}), 404
    return jsonify(updated)


@app.route("/api/admin/contact-qr", methods=["POST"])
@require_admin
def admin_upload_contact_qr():
    """上传 / 替换联系二维码（Req 15.1 ~ 15.6）

    校验由 ``save_uploaded_qr`` 完成：
      - 未携带文件 → 400 ``未找到上传文件``
      - MIME 非 PNG/JPEG → 400
      - magic-number 不匹配 → 400
      - 体积 > 5 MB → 413
    成功 → 200 ``{success: true, path: <相对 workspace 路径>}``，且
    紧接着 ``GET /api/contact-qr`` 返回的字节与刚上传文件一致。
    """
    if "file" not in request.files:
        return jsonify({"error": "未找到上传文件"}), 400
    f = request.files["file"]
    try:
        rel_path = save_uploaded_qr(f)
    except ValueError as e:
        msg = str(e)
        # 体积超限映射到 413，其它校验失败映射到 400
        status = 413 if ("5MB" in msg or "5 MB" in msg) else 400
        return jsonify({"error": msg}), status
    return jsonify({"success": True, "path": rel_path})


@app.route("/api/admin/contact-qr/meta", methods=["GET"])
@require_admin
def admin_contact_qr_meta():
    """获取当前联系二维码元数据（Req 15.7）

    返回 ``{path, updated_at}``；``system_settings.contact_qr`` 不存在
    时两者皆为 ``None``。
    """
    setting = db.get_setting("contact_qr")
    if setting is None:
        return jsonify({"path": None, "updated_at": None})
    value = setting.get("value") or {}
    return jsonify({
        "path": value.get("path"),
        "updated_at": value.get("updated_at") or setting.get("updated_at"),
    })


# ==================== 启动入口 ====================

if __name__ == "__main__":
    logger.info("启动产品图批量背景替换服务器...")
    logger.info(f"上传目录: {UPLOAD_DIR}")
    logger.info(f"输出目录: {OUTPUT_BASE}")
    app.run(host="0.0.0.0", port=5010, debug=False)
