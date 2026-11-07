FROM mwader/static-ffmpeg:7.1 AS ff
FROM python:3.12-slim
COPY --from=ff /ffmpeg /usr/local/bin/ffmpeg
COPY --from=ff /ffprobe /usr/local/bin/ffprobe
RUN apt-get update \
 && apt-get install -y --no-install-recommends fonts-dejavu-core libfribidi0 libharfbuzz0b libraqm0 \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY hub.py ghserver.py policy.py clients.py github_api.py manage.py ./
ENV PYTHONUNBUFFERED=1
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s \
  CMD python -c "import urllib.request as u;u.urlopen('http://127.0.0.1:8787/health',timeout=3)"
CMD ["python", "hub.py"]
