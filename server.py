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

# 内存任务存储
tasks_store = {}

# 管理员会话存储 (token -> {username, expires_at})
admin_sessions = {}

# 速率限制（IP -> [timestamp, ...]）
rate_limit_store = {}


# ==================== 安全中间件 ====================

@app.before_request
def security_check():
    """请求前安全检查"""
    g.request_start = time.time()
    
    # 放行静态资源和主页，不计入严格的 API 频率限制
    if request.path.startswith('/static/') or request.path.startswith('/assets/') or request.path == '/':
        return

    # 1. 黑名单检查
    ip = _get_client_ip()
    if db.is_blacklisted(ip):
        return jsonify({"error": "访问被拒绝"}), 403

    # 2. 速率限制（通用，每 IP 每分钟最多 300 次请求）
    if not _check_rate_limit(ip, max_requests=300, window=60):
        return jsonify({"error": "请求过于频繁，请稍后再试"}), 429

    # 3. 安全头
    # 在 after_request 中处理


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
    """校验 task_id 格式（支持多种长度）"""
    return bool(re.match(r'^[0-9a-fA-F\-]{8,36}$', task_id))


# ==================== 授权码装饰器 ====================

def require_license(f):
    """授权码验证装饰器 - 用于需要授权的 API"""
    @wraps(f)
    def decorated(*args, **kwargs):
        license_code = request.headers.get('X-License-Key')
        if not license_code and request.is_json:
            json_data = request.get_json(silent=True)
            if json_data:
                license_code = json_data.get('license_key', '')
        
        # 允许从 URL 参数获取授权码（用于图片预览）
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
    """全局错误处理 - 生产环境不暴露堆栈"""
    import traceback
    logger.error(f"服务器内部错误: {traceback.format_exc()}")

    # 生产环境只返回通用错误信息
    if os.getenv('FLASK_ENV') == 'development':
        return jsonify({
            "error": "服务器内部错误",
            "message": str(e),
            "trace": traceback.format_exc()
        }), 500

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


def process_task(task_id, input_dir, output_dir, prompt, images_per_product, api_keys, base_url, model, auto_recognize):
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        tasks_store[task_id]["status"] = "processing"

        def cb(filename, status, completed, total, detail):
            progress_callback(task_id, filename, status, completed, total, detail)

        processor = BatchProcessor(
            background_prompt=prompt,
            input_path=input_dir,
            output_path=output_dir,
            images_per_product=images_per_product,
            api_keys=api_keys,
            base_url=base_url,
            model=model,
            progress_callback=cb,
            auto_recognize=auto_recognize,
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
    """获取 session 已上传文件列表"""
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
    data = request.get_json(silent=True) or {}
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
    """申请试用授权码"""
    ip = _get_client_ip()

    # 速率限制：每 IP 每天只能申请 1 次试用
    if not _check_rate_limit(f"trial_{ip}", max_requests=1, window=86400):
        return jsonify({"error": "每天只能申请一次试用授权码"}), 429

    license_info = db.create_license(
        code_type="trial",
        expires_days=7,
        remark=f"试用申请 - IP: {ip}",
        created_by="auto",
    )

    return jsonify({
        "license_key": license_info["code"],
        "type": license_info["type"],
        "expires_at": license_info["expires_at"],
        "max_daily_uses": license_info["max_daily_uses"],
        "message": "试用授权码已生成，有效期 7 天",
    })


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
@require_license
def delete_uploaded_file(session_id, filename):
    """删除已上传文件"""
    if not _validate_session_id(session_id):
        return jsonify({"error": "无效的会话ID"}), 400

    safe_name = _sanitize_path(filename)
    if not safe_name:
        return jsonify({"error": "无效的文件名"}), 400

    file_path = os.path.join(UPLOAD_DIR, session_id, safe_name)

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

    upload_dir = os.path.join(UPLOAD_DIR, session_id)
    os.makedirs(upload_dir, exist_ok=True)

    for f in files:
        if f.filename:
            safe_name = _sanitize_path(f.filename)
            if not safe_name:
                continue
            save_path = os.path.join(upload_dir, safe_name)
            f.save(save_path)

    # 扫描目录获取所有文件
    all_files = []
    for f in os.listdir(upload_dir):
        full_path = os.path.join(upload_dir, f)
        if os.path.isfile(full_path) and not f.startswith('.'):
            file_size = os.path.getsize(full_path)
            all_files.append({
                "name": f,
                "size": file_size,
                "path": f"/api/preview/{session_id}/{f}"
            })

    return jsonify({
        "session_id": session_id,
        "input_dir": upload_dir,
        "files": all_files,
        "count": len(all_files)
    })


@app.route("/api/preview/<session_id>/<filename>")
@require_license
def preview_image(session_id, filename):
    """预览已上传图片"""
    if not _validate_session_id(session_id):
        return jsonify({"error": "无效的会话ID"}), 400

    safe_name = _sanitize_path(filename)
    if not safe_name:
        return jsonify({"error": "无效的文件名"}), 400

    upload_dir = os.path.join(UPLOAD_DIR, session_id)

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

    api_key_input = data.get("api_key", "")
    if api_key_input:
        api_keys = [k.strip() for k in api_key_input.split(",") if k.strip()]
    else:
        api_keys = settings.YUNWU_API_KEYS
    
    # 获取 baseUrl 参数
    base_url_input = data.get("base_url", "")

    if not api_keys:
        return jsonify({"error": "请提供 API Key"}), 400

    output_name = data.get("output_name", datetime.now().strftime("output_%Y%m%d_%H%M%S"))
    auto_recognize = data.get("auto_recognize", False)

    if not input_dir or not os.path.exists(input_dir):
        return jsonify({"error": "输入目录不存在，请先上传文件"}), 400

    if not prompt.strip() and not auto_recognize:
        return jsonify({"error": "请输入场景描述或开启自动识别"}), 400

    output_dir = os.path.join(OUTPUT_BASE, output_name)
    os.makedirs(output_dir, exist_ok=True)

    task_id = str(uuid.uuid4())[:12]
    tasks_store[task_id] = {
        "status": "pending",
        "progress": {"completed": 0, "total": 0, "percent": 0, "current_file": "", "status": "", "detail": ""},
        "log": [],
        "output_files": [],
        "output_dir": output_dir,
        "created_at": datetime.now().isoformat(),
        "auto_recognize": auto_recognize,
        "license_code": g.license_code,
    }

    # Vercel 环境同步处理，否则异步线程
    if os.getenv("VERCEL") == "1" or os.getenv("AWS_EXECUTION_ENV"):
        try:
            process_task(task_id, input_dir, output_dir, prompt, images_per_product, api_keys, base_url_input, data.get("model", ""), auto_recognize)
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
            args=(task_id, input_dir, output_dir, prompt, images_per_product, api_keys, base_url_input, data.get("model", ""), auto_recognize),
            daemon=True,
        )
        thread.start()
        return jsonify({"task_id": task_id, "status": "pending"})


@app.route("/api/task/<task_id>", methods=["GET"])
@require_license
def get_task_status(task_id):
    """查询任务状态"""
    # UUID v4 取前 12 位或 8 位都有可能，放宽限制为字母数字和横杠
    if not re.match(r'^[0-9a-fA-F\-]{8,36}$', task_id):
        return jsonify({"error": "无效的任务ID"}), 400

    if task_id not in tasks_store:
        return jsonify({"error": "任务不存在"}), 404

    task = tasks_store[task_id]
    return jsonify({
        "task_id": task_id,
        "status": task["status"],
        "progress": task.get("progress", {}),
        "result": task.get("result"),
        "error": task.get("error"),
        "output_files": task.get("output_files", []),
        "log": task.get("log", [])[-20:],
        "recognition": task.get("recognition", {}),
        "auto_recognize": task.get("auto_recognize", False),
    })


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

    if task_id not in tasks_store:
        return jsonify({"error": "任务不存在"}), 404

    safe_name = _sanitize_path(filename)
    if not safe_name:
        return jsonify({"error": "无效的文件名"}), 400

    output_dir = tasks_store[task_id].get("output_dir", "")
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
    """删除整个任务及所有输出文件"""
    if not _validate_task_id(task_id):
        return jsonify({"error": "无效的任务ID"}), 400

    output_dir = ""
    if task_id in tasks_store:
        output_dir = tasks_store[task_id].get("output_dir", "")
        # 从内存中移除
        del tasks_store[task_id]
    else:
        output_dir = os.path.join(OUTPUT_BASE, task_id)
        if not os.path.exists(output_dir):
             return jsonify({"error": "任务不存在"}), 404

    # 安全校验
    real_path = os.path.realpath(output_dir)
    if not real_path.startswith(os.path.realpath(OUTPUT_BASE)):
        return jsonify({"error": "非法路径"}), 403

    if os.path.exists(real_path):
        try:
            import shutil
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

    # 如果 task 不在内存 store 中，也允许直接通过文件夹路径删除缓存的历史文件
    output_dir = ""
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

    output_dir = ""
    if task_id in tasks_store:
        output_dir = tasks_store[task_id].get("output_dir", "")
    else:
        output_dir = os.path.join(OUTPUT_BASE, task_id)

    if not output_dir or not os.path.exists(output_dir):
        return jsonify({"error": "输出目录不存在"}), 404

    # 再次安全校验
    real_path = os.path.realpath(output_dir)
    if not real_path.startswith(os.path.realpath(OUTPUT_BASE)):
        return jsonify({"error": "非法路径"}), 403

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
    data = request.get_json(silent=True) or {}
    api_key_input = data.get("api_key", "")
    api_keys = [k.strip() for k in api_key_input.split(",") if k.strip()] if api_key_input else settings.YUNWU_API_KEYS

    if not api_keys:
        return jsonify({"valid": False, "message": "API Key未设置"})
    return jsonify({"valid": True, "message": "API Key已配置"})


# ==================== 后台管理 API ====================

@app.route("/api/admin/login", methods=["POST"])
def admin_login():
    """管理员登录"""
    data = request.get_json(silent=True) or {}
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
    data = request.get_json(silent=True) or {}
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
    """获取授权码列表"""
    status = request.args.get("status")
    code_type = request.args.get("type")
    page = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", 20))

    result = db.list_licenses(status=status, code_type=code_type, page=page, per_page=per_page)
    return jsonify(result)


@app.route("/api/admin/licenses", methods=["POST"])
@require_admin
def admin_create_license():
    """创建授权码"""
    data = request.get_json(silent=True) or {}
    code_type = data.get("type", "trial")
    count = min(int(data.get("count", 1)), 100)  # 最多一次创建 100 个
    max_daily_uses = int(data.get("max_daily_uses", 50))
    expires_days = data.get("expires_days")
    remark = data.get("remark", "")

    if expires_days is not None:
        expires_days = int(expires_days)

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
    """获取使用日志"""
    license_code = request.args.get("license_code")
    page = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", 50))
    return jsonify(db.get_usage_logs(license_code=license_code, page=page, per_page=per_page))


# --- 黑名单管理 ---

@app.route("/api/admin/blacklist", methods=["GET"])
@require_admin
def admin_list_blacklist():
    """获取黑名单列表"""
    return jsonify(db.list_blacklist())


@app.route("/api/admin/blacklist", methods=["POST"])
@require_admin
def admin_add_blacklist():
    """添加 IP 到黑名单"""
    data = request.get_json(silent=True) or {}
    ip_address = data.get("ip_address", "").strip()
    reason = data.get("reason", "")

    if not ip_address:
        return jsonify({"error": "请输入 IP 地址"}), 400

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

@app.route("/api/admin/backup", methods=["POST"])
@require_admin
def admin_backup():
    """手动备份数据库"""
    try:
        backup_path = db.backup()
        return jsonify({"success": True, "message": "备份成功", "path": backup_path})
    except Exception as e:
        return jsonify({"error": f"备份失败: {str(e)}"}), 500


@app.route("/api/admin/backup/download", methods=["GET"])
@require_admin
def admin_backup_download():
    """下载数据库备份"""
    try:
        backup_path = db.backup()
        return send_file(
            backup_path,
            as_attachment=True,
            download_name=os.path.basename(backup_path),
            mimetype="application/octet-stream",
        )
    except Exception as e:
        return jsonify({"error": f"备份下载失败: {str(e)}"}), 500


# ==================== 启动入口 ====================

if __name__ == "__main__":
    logger.info("启动产品图批量背景替换服务器...")
    logger.info(f"上传目录: {UPLOAD_DIR}")
    logger.info(f"输出目录: {OUTPUT_BASE}")
    app.run(host="0.0.0.0", port=5010, debug=False)
