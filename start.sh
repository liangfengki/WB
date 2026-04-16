#!/bin/bash
set -e

echo "=== Container Starting ===" >&2
echo "PORT=${PORT:-8000}" >&2
echo "Python: $(python3 --version)" >&2
echo "PWD: $(pwd)" >&2
echo "Disk:" >&2
df -h /app 2>&1 >&2 || true
echo "Memory:" >&2
free -m 2>&1 >&2 || cat /proc/meminfo 2>&1 >&2 || true

echo "=== Testing Import ===" >&2
python3 -u -c "
import sys, os
print(f'Python {sys.version}', flush=True)
print(f'Memory info:', flush=True)
try:
    import resource
    usage = resource.getrusage(resource.RUSAGE_SELF)
    print(f'  Peak RSS: {usage.ru_maxrss / 1024:.1f} MB', flush=True)
except: pass

print('Importing server...', flush=True)
try:
    import server
    print('SERVER IMPORTED OK', flush=True)
    import resource
    usage = resource.getrusage(resource.RUSAGE_SELF)
    print(f'  Peak RSS after import: {usage.ru_maxrss / 1024:.1f} MB', flush=True)
except Exception as e:
    print(f'IMPORT FAILED: {e}', flush=True)
    import traceback
    traceback.print_exc()
    sys.exit(1)
" 2>&1

echo "=== Starting Server ===" >&2
PORT=${PORT:-8000}
exec python3 -u -m gunicorn server:app \
    --bind 0.0.0.0:${PORT} \
    --timeout 600 \
    --workers 1 \
    --threads 4 \
    --graceful-timeout 600 \
    --keep-alive 5 \
    --log-level info \
    --error-logfile - \
    --access-logfile - \
    --preload 2>&1
