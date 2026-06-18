#!/bin/bash

# 定義路徑，假設你在專案根目錄執行此腳本
COMPOSE_FILE="docker-compose.yml"

echo "開始更新 SSL 證書..."

# 1. 執行 Certbot renew
docker compose run --rm certbot renew

# 2. 如果更新成功，重載 Nginx 以載入新證書
if [ $? -eq 0 ]; then
    echo "證書更新成功，正在重載 Nginx..."
    docker compose exec nginx nginx -s reload
else
    echo "證書暫時無需更新或更新失敗。"
fi