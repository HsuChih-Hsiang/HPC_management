#!/usr/bin/env bash
#
# 部署入口。CI（.github/workflows/deploy.yml）與人工部署都呼叫這一支，
# 確保兩條路徑做的事情完全一樣。
#
# 用法（在 deployment/ 底下執行）：
#     ./deployment.sh
#
# 憑證說明：對外 TLS 由主機前面的 WAF 負責，nginx 只在容器啟動時
# 產生一張自簽憑證供 WAF 回源使用，不需要 certbot，也沒有續期問題。

set -euo pipefail

cd "$(dirname "$0")"

ENV_FILE="../.env"

if [ ! -f "$ENV_FILE" ]; then
    echo "錯誤: 找不到 $ENV_FILE"
    echo "請參考 deployment/.env.example 在專案根目錄建立 .env 後再執行。"
    exit 1
fi

# 讀 DOMAIN 只是為了印訊息。這裡刻意不用 `export $(grep ... | xargs)`：
# 那種寫法碰到含空白或 # 的值（例如密碼）會被 xargs 拆爛，
# 舊版腳本就是這樣壞的。真正的變數傳遞交給 compose 的 --env-file。
# tr 的參數 '"'' 表示同時去掉雙引號與單引號
DOMAIN="$(grep -E '^DOMAIN=' "$ENV_FILE" | head -n1 | cut -d= -f2- | tr -d "\"'" || true)"
DOMAIN="${DOMAIN:-localhost}"

# compose 預設只會讀「compose 檔旁邊」的 .env，而本專案的 .env 在上一層，
# 所以一定要明確指定 --env-file，${DOMAIN} 之類的插值才有值。
COMPOSE=(docker compose --env-file "$ENV_FILE" -f docker-compose.yml)

echo "=== 開始部署 (目標網域: ${DOMAIN}) ==="

echo "--- 建置 image ---"
"${COMPOSE[@]}" build

echo "--- 啟動服務 ---"
"${COMPOSE[@]}" up -d --remove-orphans

echo "--- 等待 app 通過健康檢查 ---"
for i in $(seq 1 40); do
    status="$("${COMPOSE[@]}" ps --format json app 2>/dev/null | grep -o '"Health":"[^"]*"' | head -n1 | cut -d'"' -f4 || true)"
    case "$status" in
        healthy)
            echo "app 已就緒。"
            break
            ;;
        unhealthy)
            echo "app 健康檢查失敗，以下是最後 100 行日誌："
            "${COMPOSE[@]}" logs --tail 100 app
            exit 1
            ;;
    esac
    if [ "$i" -eq 40 ]; then
        echo "等待逾時（200 秒），以下是最後 100 行日誌："
        "${COMPOSE[@]}" logs --tail 100 app
        exit 1
    fi
    sleep 5
done

# 只清沒有任何 tag 的中介層，不動具名 image 與 volume。
# 千萬不要在這裡加 --volumes：app_keys volume 裡是 RSA 私鑰，刪掉就回不來了。
echo "--- 清理沒被引用的舊 image layer ---"
docker image prune -f >/dev/null

echo "=== 部署完成 ==="
"${COMPOSE[@]}" ps
