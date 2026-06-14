# alles — single-user personal everything-app. one container, sqlite on a volume.
FROM python:3.12-slim

WORKDIR /app

# build deps for the wheels that need C extensions (lxml for trafilatura, pillow)
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc libxml2-dev libxslt1-dev \
    && rm -rf /var/lib/apt/lists/*

# deps first so the layer caches across code changes
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PORT=8000
EXPOSE 8000

# data/ (sqlite db, vault, uploads, keys) should be a mounted volume so it survives
# rebuilds:  docker run -p 8000:8000 -v alles-data:/app/data alles
VOLUME ["/app/data"]

# fail the container build/health early if the install is broken
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health').read() else 1)" || exit 1

CMD ["python", "app.py"]
