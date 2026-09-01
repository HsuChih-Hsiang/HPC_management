#!/bin/sh
# ============================================================
# 產生自簽憑證（僅在憑證不存在時）
#
# 正式環境的 TLS 是由前面的 WAF 終結的，瀏覽器看到的是 WAF 的憑證，
# 不會看到這一張。這張自簽憑證只負責「WAF → nginx」這一段內網連線，
# 所以不需要（也不可能）通過任何公開 CA 的驗證，
# 也因此整組 certbot / Let's Encrypt 續期流程都已經移除。
#
# 憑證放在具名 volume 上，容器重建時沿用同一張，
# 避免 WAF 每次部署都看到憑證換了。
# ============================================================
set -e

CERT_DIR=/etc/nginx/certs
CERT_FILE="$CERT_DIR/selfsigned.crt"
KEY_FILE="$CERT_DIR/selfsigned.key"
CN="${DOMAIN:-localhost}"

mkdir -p "$CERT_DIR"

if [ -s "$CERT_FILE" ] && [ -s "$KEY_FILE" ]; then
    echo "[cert] 已存在自簽憑證，沿用 $CERT_FILE"
    exit 0
fi

echo "[cert] 產生自簽憑證 (CN=$CN, 有效期 10 年) ..."
openssl req -x509 -nodes -newkey rsa:2048 \
    -days 3650 \
    -keyout "$KEY_FILE" \
    -out "$CERT_FILE" \
    -subj "/CN=$CN" \
    -addext "subjectAltName=DNS:$CN,DNS:localhost,IP:127.0.0.1" \
    2>/dev/null

chmod 600 "$KEY_FILE"
echo "[cert] 完成。"
