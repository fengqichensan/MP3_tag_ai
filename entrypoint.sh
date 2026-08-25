#!/bin/sh
# 容器入口：默认启用 HTTPS（自签名证书，持久化到 CERT_DIR，重启不重签）。
# 设 ENABLE_HTTPS=0 可退回纯 HTTP。
set -e

CERT_DIR="${CERT_DIR:-/app/certs}"

if [ "${ENABLE_HTTPS:-1}" = "1" ]; then
  mkdir -p "$CERT_DIR"
  if [ ! -s "$CERT_DIR/cert.pem" ] || [ ! -s "$CERT_DIR/key.pem" ]; then
    echo "[entrypoint] 生成自签名证书 -> $CERT_DIR"
    openssl req -x509 -newkey rsa:2048 -sha256 -days 3650 -nodes \
      -keyout "$CERT_DIR/key.pem" -out "$CERT_DIR/cert.pem" \
      -subj "/CN=mp3-tag-ai" \
      -addext "subjectAltName=${CERT_SAN:-DNS:localhost, IP:192.168.2.155}"
    chmod 600 "$CERT_DIR/key.pem" "$CERT_DIR/cert.pem"
  fi
fi
# TLS_CERTFILE / TLS_KEYFILE 由镜像 ENV 提供（健康检查也依赖它们判断协议）

exec python app.py
