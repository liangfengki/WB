# 产品图批量背景替换工具

基于豆包 Seedream API 的电商产品图批量背景替换工具，自动保留产品本体和原图文字。

## 使用方法

1. 复制 .env.example 为 .env 并配置你的火山方舟 API Key
2. 将待处理图片放入 input/ 文件夹
3. 运行工具：

```bash
python3 main.py "简约白色背景，柔和光影，电商产品摄影风格"
```

## 功能特性

- ✅ 批量处理 50-200 张图片
- ✅ 自动识别并保留原图文字
- ✅ 3并发异步处理，带失败重试
- ✅ 统一输出 1024x1024 电商标准尺寸
- ✅ 详细日志记录
- ✅ 断点续传支持

## 目录结构

```
input/          # 放入待处理图片
output/         # 处理结果输出
logs/           # 运行日志
config/         # 配置文件
api/            # Seedream API 客户端
processor/      # 图片和OCR处理
engine/         # 批量处理引擎
```

## 依赖安装

```bash
pip3 install -r requirements.txt
```

## 部署

生产部署通过 `Procfile` 启动：

```
web: gunicorn server:app --bind 0.0.0.0:$PORT --timeout 600 --workers 1 --graceful-timeout 600 --keep-alive 5
```

⚠️ **单 worker 是硬约束，勿改**：`--workers 1` 必须保留。后台管理的会话存储（`admin_sessions`）与登录/通用速率限制计数器都是进程内内存结构，多 worker 下无法跨进程共享，会导致管理员随机被登出、限流计数失真。若将来确有横向扩容需求，必须先把会话与限流迁移到 Redis 等外部存储，再讨论调整 worker 数。
