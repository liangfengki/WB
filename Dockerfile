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

EXPOSE 8080

CMD sh -c 'gunicorn server:app --bind 0.0.0.0:${PORT:-8080} --timeout 600 --workers 1 --threads 4 --graceful-timeout 600 --keep-alive 5 --log-level info --error-logfile - --access-logfile -'
