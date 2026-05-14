# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Product image background replacement tool using AI APIs (Yunwu/Seedream). Supports two modes: CLI batch processing and Flask web server with license management.

## Commands

```bash
# Install dependencies
pip3 install -r requirements.txt

# CLI mode - batch process images in input/ folder
python3 main.py "背景提示词"

# Web server (port 5010)
./start.sh
# or
python3 server.py

# Run tests
python3 -m pytest tests/
```

## Architecture

**Entry Points:**
- `main.py` - CLI batch processor
- `server.py` - Flask web server (serves `index.html` and `admin.html`)

**Core Modules:**
- `engine/batch.py` - BatchProcessor: orchestrates concurrent image processing with asyncio
- `engine/pairing.py` - PairingEngine: matches source images with reference backgrounds (xhs_multi mode)
- `engine/prompt_builder.py` - Constructs AI prompts for different modes
- `api/seedream.py` - Yunwu/Seedream API client (despite the filename)
- `config/settings.py` - Singleton Settings class, loads from .env

**Processing Pipeline:**
1. `processor/image.py` - Image preprocessing (resize to 1024x1024)
2. `processor/ocr.py` - EasyOCR text extraction and overlay
3. `processor/product_recognizer.py` - AI-powered product type recognition
4. API call to generate new background
5. OCR text overlay on output

**Database:**
- `db/database.py` - SQLite (WAL mode) for license_keys, usage_logs, blacklist, daily_stats
- Thread-safe with per-thread connections
- DB file: `data/app.db`

**Processing Modes:**
- `wb` - Wildberries product images (default)
- `xhs_multi` - Xiaohongshu multi-image mode (source + reference pairing)

## Key Constraints

- **Single worker only**: `--workers 1` is mandatory for gunicorn (in-memory session/rate-limit stores)
- **Vercel deployment**: Uses `/tmp` for all file I/O (read-only filesystem)
- **API keys**: Multiple keys supported via comma-separated `YUNWU_API_KEYS` env var
- **Concurrency**: Controlled by `CONCURRENCY` setting (default 3), uses asyncio Semaphore
