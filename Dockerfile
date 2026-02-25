FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends     ffmpeg     fonts-noto     fontconfig \ && fc-cache -fv \ && apt-get clean \ && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /tmp/anisub_uploads /tmp/anisub_outputs

ENV PORT=8080
EXPOSE 8080

CMD ["sh", "-c", "exec gunicorn --timeout 3600 --workers 1 --bind 0.0.0.0:${PORT} app:app"]
