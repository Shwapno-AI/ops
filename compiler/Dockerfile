FROM python:3.13-slim

# LibreOffice checks template formulas and opens older template formats.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libreoffice-calc \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_ROOT_USER_ACTION=ignore \
    HOME=/tmp \
    DATA_DIR=/data \
    PORT=3000

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY excelcompiler ./excelcompiler
COPY webapp ./webapp
COPY examples ./examples
COPY start.sh .

RUN useradd --uid 1000 --no-create-home app && mkdir -p /data && chown app:app /data && chmod +x start.sh

EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import os,urllib.request as u; u.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/healthz', timeout=4)"

ENTRYPOINT ["./start.sh"]
