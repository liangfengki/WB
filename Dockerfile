FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    libgl1 libglib2.0-0 libsm6 libxrender1 libxext6 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/uploads /app/output /app/logs /app/data

ENV PYTHONPATH=/app
ENV PORT=8000

EXPOSE 8000

CMD python3 -u -c "
import os, sys
port = int(os.environ.get('PORT', '8000'))
print(f'STARTING on port {port}', flush=True)
try:
    import server
    print('IMPORT OK', flush=True)
    server.app.run(host='0.0.0.0', port=port, debug=False)
except Exception as e:
    print(f'STARTUP ERROR: {e}', flush=True)
    import traceback; traceback.print_exc()
    sys.exit(1)
"
