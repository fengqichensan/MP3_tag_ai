FROM python:3.12-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends openssl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# 默认使用清华 TUNA 镜像，避免 NAS 直连 pypi.org 超时；可用 --build-arg PIP_INDEX_URL=... 覆盖
ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
RUN pip install --no-cache-dir -i "${PIP_INDEX_URL}" -r requirements.txt

COPY app.py ai_client.py tag_editor.py entrypoint.sh ./
COPY static/ static/

ENV HOST=0.0.0.0 \
    PORT=5000 \
    PYTHONUNBUFFERED=1

EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD python -c "import urllib.request, ssl, os, sys; ctx = ssl._create_unverified_context(); scheme = 'https' if os.environ.get('TLS_CERTFILE') else 'http'; r = urllib.request.urlopen(scheme + '://127.0.0.1:5000/', timeout=4, context=ctx); sys.exit(0 if r.status == 200 else 1)"

ENTRYPOINT ["sh", "/app/entrypoint.sh"]
