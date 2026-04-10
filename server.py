import os
import json
import asyncio
import threading
import uuid
import shutil
import tempfile
import zipfile
from datetime import datetime
from flask import Flask, request, jsonify, send_from_directory, send_file
from config.settings import settings

# 强制将临时目录指向 /tmp 以适配 Vercel 的只读文件系统
import tempfile
if settings._is_vercel:
    tempfile.tempdir = "/tmp"

from engine.batch import BatchProcessor
from utils.logger import logger

app = Flask(__name__, static_folder=None)

@app.errorhandler(Exception)
def handle_exception(e):
    import traceback
    logger.error(f"服务器内部错误: {traceback.format_exc()}")
    return jsonify({
        "error": "服务器内部错误",
        "message": str(e),
        "trace": traceback.format_exc()
    }), 500

app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024

UPLOAD_DIR = os.path.abspath(settings.UPLOAD_DIR)
OUTPUT_BASE = os.path.abspath(settings.OUTPUT_DIR)
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_BASE, exist_ok=True)

tasks_store = {}


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


def process_task(task_id, input_dir, output_dir, prompt, images_per_product, api_keys, auto_recognize):
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


@app.route("/")
def index():
    return send_file(os.path.join(os.path.dirname(__file__), "index.html"))


@app.route("/api/scenes", methods=["GET"])
def get_scenes():
    return jsonify({"scenes": settings.SCENE_PRESETS})


@app.route("/api/upload", methods=["POST"])
def upload_files():
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
            safe_name = os.path.basename(f.filename)
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
def delete_uploaded_file(session_id, filename):
    safe_name = os.path.basename(filename)
    file_path = os.path.join(UPLOAD_DIR, session_id, safe_name)
    if os.path.exists(file_path):
        try:
            os.remove(file_path)
            return jsonify({"success": True, "message": "删除成功"})
        except Exception as e:
            return jsonify({"error": f"删除失败: {str(e)}"}), 500
    return jsonify({"error": "文件不存在"}), 404

@app.route("/api/output/<task_id>/<filename>", methods=["DELETE"])
def delete_output_file(task_id, filename):
    safe_name = os.path.basename(filename)
    file_path = os.path.join(OUTPUT_DIR, task_id, safe_name)
    if os.path.exists(file_path):
        try:
            os.remove(file_path)
            return jsonify({"success": True, "message": "删除成功"})
        except Exception as e:
            return jsonify({"error": f"删除失败: {str(e)}"}), 500
    return jsonify({"error": "文件不存在"}), 404

@app.route("/api/upload-preview", methods=["POST"])
def upload_preview():
    if "files" not in request.files:
        return jsonify({"error": "未找到上传文件"}), 400

    files = request.files.getlist("files")
    if not files:
        return jsonify({"error": "没有选择文件"}), 400

    session_id = request.form.get("session_id")
    if not session_id:
        session_id = str(uuid.uuid4())[:8]
        
    upload_dir = os.path.join(UPLOAD_DIR, session_id)
    os.makedirs(upload_dir, exist_ok=True)

    saved = []
    
    # 获取现有文件
    existing_files = []
    if os.path.exists(upload_dir):
        for f in os.listdir(upload_dir):
            if os.path.isfile(os.path.join(upload_dir, f)) and not f.startswith('.'):
                existing_files.append(f)
                
    for f in files:
        if f.filename:
            safe_name = os.path.basename(f.filename)
            save_path = os.path.join(upload_dir, safe_name)
            f.save(save_path)
            
    # 重新扫描整个目录获取所有文件
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
def preview_image(session_id, filename):
    upload_dir = os.path.join(UPLOAD_DIR, session_id)
    return send_from_directory(upload_dir, filename)


@app.route("/api/process", methods=["POST"])
def start_process():
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

    if not api_keys:
        return jsonify({"error": "请提供 API Key"}), 400
        
    output_name = data.get("output_name", datetime.now().strftime("output_%Y%m%d_%H%M%S"))
    auto_recognize = data.get("auto_recognize", False)

    if not input_dir or not os.path.exists(input_dir):
        return jsonify({"error": "输入目录不存在，请先上传文件"}), 400

    if not prompt.strip() and not auto_recognize:
        return jsonify({"error": "请输入场景描述或开启自动识别"}), 400

    if not api_keys:
        return jsonify({"error": "请提供至少一个 API Key"}), 400

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
    }

    # 如果是 Vercel 环境，使用同步阻塞处理（Vercel不支持后台线程，且函数最长执行时间通过配置延长）
    # 否则使用异步线程处理，不阻塞主进程
    if os.getenv("VERCEL") == "1" or os.getenv("AWS_EXECUTION_ENV"):
        try:
            process_task(task_id, input_dir, output_dir, prompt, images_per_product, api_keys, auto_recognize)
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
            args=(task_id, input_dir, output_dir, prompt, images_per_product, api_keys, auto_recognize),
            daemon=True,
        )
        thread.start()

        return jsonify({"task_id": task_id, "status": "pending"})


@app.route("/api/task/<task_id>", methods=["GET"])
def get_task_status(task_id):
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
def get_task_log(task_id):
    if task_id not in tasks_store:
        return jsonify({"error": "任务不存在"}), 404

    task = tasks_store[task_id]
    return jsonify({"log": task.get("log", [])})


@app.route("/api/output/<task_id>/<filename>")
def get_output_image(task_id, filename):
    if task_id not in tasks_store:
        return jsonify({"error": "任务不存在"}), 404

    output_dir = tasks_store[task_id].get("output_dir", "")
    if not output_dir or not os.path.exists(output_dir):
        return jsonify({"error": "输出目录不存在"}), 404

    return send_from_directory(output_dir, filename)


@app.route("/api/download/<task_id>", methods=["GET"])
def download_results(task_id):
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
def get_history():
    results = []
    for task_id, task in tasks_store.items():
        results.append({
            "task_id": task_id,
            "status": task["status"],
            "created_at": task.get("created_at", ""),
            "output_files": task.get("output_files", []),
            "result": task.get("result"),
        })
    return jsonify({"tasks": results})


@app.route("/api/check-api", methods=["POST"])
def check_api():
    data = request.json or {}
    api_key_input = data.get("api_key", "")
    api_keys = [k.strip() for k in api_key_input.split(",") if k.strip()] if api_key_input else settings.YUNWU_API_KEYS
    
    if not api_keys:
        return jsonify({"valid": False, "message": "API Key未设置"})
    return jsonify({"valid": True, "message": "API Key已配置"})


if __name__ == "__main__":
    logger.info("启动产品图批量背景替换服务器...")
    logger.info(f"上传目录: {UPLOAD_DIR}")
    logger.info(f"输出目录: {OUTPUT_BASE}")
    app.run(host="0.0.0.0", port=5010, debug=False)