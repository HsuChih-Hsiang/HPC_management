#!/bin/bash

# 1. 載入 .env 變數
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
else
    echo "錯誤: 找不到 .env 檔案"
    exit 1
fi

# 使用 .env 中的 DOMAIN 定義憑證路徑
CERT_PATH="./certbot/conf/live/${DOMAIN}/fullchain.pem"

echo "=== 開始部署流程 (目標網域: ${DOMAIN}) ==="

# 2. 檢查憑證是否存在 (判斷是否為初次部署)
if [ ! -f "$CERT_PATH" ]; then
    echo "偵測到初次部署或憑證遺失，準備初始化 SSL 證書..."
    
    mkdir -p ./certbot/conf ./certbot/www
    
    # 啟動 Nginx (HTTP 模式) 以進行 ACME 驗證
    docker compose up -d nginx
    
    echo "正在向 Let's Encrypt 申請 SSL 憑證..."
    docker compose run --rm certbot certonly --webroot \
        --webroot-path /var/www/certbot \
        -d ${DOMAIN} \
        --register-unsafely-without-email \
        --agree-tos \
        --non-interactive
    
    if [ $? -ne 0 ]; then
        echo "憑證申請失敗，請檢查："
        echo "1. 網域是否已正確解析到本機 IP"
        echo "2. 伺服器 80 port 是否未被占用且可由外部存取"
        exit 1
    fi
    echo "SSL 憑證申請成功！"
fi

# 3. 執行正式部署
echo "正在更新程式碼並啟動正式服務..."
docker compose up -d --build

echo "=== 部署完成！服務已於 https://${DOMAIN} 上線 ==="