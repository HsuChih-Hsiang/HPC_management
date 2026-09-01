# 部署說明

## 架構

```
網際網路
   │
   ▼
  WAF          ← 對外 TLS 在這裡終結（正式憑證由 WAF 管理）
   │  http 或 https 回源
   ▼
 nginx (容器, 80/443)   ← 自簽憑證，只供 WAF 回源用；不需要 certbot
   │  http://app:8000
   ▼
gunicorn + Flask (容器)
   │
   ▼
PostgreSQL (容器外，140.112.8.36)
```

CI/CD 走 GitHub Actions + **裝在正式機 VM 上的 self-hosted runner**：
VM 只需要能連得出去，不必開任何對外的 inbound port，也不用把 SSH 私鑰
存進 GitHub secrets。

| 觸發               | Workflow             | 做什麼 |
| ------------------ | -------------------- | ------ |
| push 到非 main 分支 / PR | `.github/workflows/ci.yml`     | 語法檢查、相依套件可安裝性、兩個 image 能否建置 |
| push 到 main / 手動   | `.github/workflows/deploy.yml` | 先做同樣的驗證，通過後由 VM 上的 runner 執行 `deployment/deployment.sh` |

---

## 檔案

| 檔案 | 用途 |
| ---- | ---- |
| `DOCKERFILE`             | app image（Python + gunicorn + Playwright/Chromium） |
| `nginx.Dockerfile`       | nginx image（官方 image + openssl） |
| `10-selfsigned-cert.sh`  | nginx 啟動時產生自簽憑證（已存在則沿用） |
| `nginx.conf`             | 反向代理設定 |
| `docker-compose.yml`     | 服務編排 |
| `deployment.sh`          | 部署入口，CI 與人工部署都用這一支 |
| `.env.example`           | 正式機 `.env` 範本 |

---

## 一、正式機 VM 初次設定

以下只需要做一次。

### 1. 安裝 Docker

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo systemctl enable --now docker
```

### 2. 建立 `.env`

`.env` 含有資料庫密碼與 `SECRET_KEY`，**不會進版控**。
把它放在 VM 上的固定位置，CI 每次部署會複製進 workspace：

```bash
sudo mkdir -p /srv/hpcemail
sudo cp deployment/.env.example /srv/hpcemail/.env
sudo chmod 600 /srv/hpcemail/.env
sudo vi /srv/hpcemail/.env        # 填入實際值
```

> ⚠️ `SECRET_KEY` 同時是資料庫欄位加密（Fernet）的金鑰來源。
> 換掉它，資料庫裡已加密的 SMTP 密碼就再也解不開，必須到「設定」頁面重新輸入。

### 3. 安裝 self-hosted runner

GitHub repo → **Settings → Actions → Runners → New self-hosted runner**，
選 Linux x64，照畫面給的指令做。**設定時 label 要加上 `hpcemail`**
（`deploy.yml` 的 `runs-on: [self-hosted, linux, hpcemail]` 靠它挑機器）：

```bash
mkdir ~/actions-runner && cd ~/actions-runner
# curl -o ... / tar xzf ...   （用 GitHub 頁面上顯示的版本號）
./config.sh --url https://github.com/HsuChih-Hsiang/HPC_management \
            --token <頁面上的 token> \
            --labels hpcemail
```

裝成開機自動啟動的 service：

```bash
sudo ./svc.sh install
sudo ./svc.sh start
```

### 4. 讓 runner 有權限用 docker

```bash
sudo usermod -aG docker $USER
sudo ./svc.sh stop && sudo ./svc.sh start     # 重啟 service 讓群組生效
```

### 5. 建立 production environment（選用，但建議）

repo → **Settings → Environments → New environment → `production`**。
在裡面加 **Required reviewers**，之後每次部署都會停下來等人按核准，
避免半夜一個 push 直接改動正式機。

### 6. 第一次部署

到 **Actions → Deploy → Run workflow** 手動觸發，或直接 push 到 `main`。

---

## 二、WAF 設定

- 回源位址：`https://<VM IP>:443`（或 `http://<VM IP>:80`，兩者都通）
- 回源憑證驗證請**關閉**或設為信任 —— nginx 用的是自簽憑證，不會通過公開 CA 驗證。
- 請確認 WAF 有帶上 `X-Forwarded-Proto: https`。
  少了它，Flask 產生的 Google OAuth `redirect_uri` 會是 `http://` 開頭，
  與 Google 後台註冊的網址對不起來，登入會失敗。
- 健康檢查可打 `/healthz`（nginx 直接回 200，不進 Flask）。

### Google OAuth

Google Cloud Console 的「已授權的重新導向 URI」要填：

```
https://<你的網域>/callback
```

---

## 三、日常操作

部署由 push 到 `main` 自動觸發。需要手動介入時，在 VM 上：

```bash
cd ~/actions-runner/_work/HPC_management/HPC_management/deployment
```

| 需求 | 指令 |
| ---- | ---- |
| 看狀態 | `docker compose -p hpcemail ps` |
| 看日誌 | `docker compose -p hpcemail logs -f app` |
| 重啟   | `docker compose -p hpcemail restart app` |
| 手動重新部署 | `cp /srv/hpcemail/.env ../.env && ./deployment.sh` |

### 持久化資料

三個具名 volume，**重新部署不會被清掉**：

| Volume | 掛載點 | 內容 |
| ------ | ------ | ---- |
| `hpcemail_app_keys`   | `/source`         | RSA 私鑰（`utils/params.py` 的 `KEY_DIR`）。刪掉會讓前端加密的資料解不開。 |
| `hpcemail_app_logs`   | `/app/log`        | HPC 用量通知紀錄 |
| `hpcemail_nginx_certs`| `/etc/nginx/certs`| 自簽憑證 |

> ⚠️ 清理磁碟時**不要**下 `docker compose down -v` 或 `docker volume prune`。
> `deployment.sh` 只會做 `docker image prune -f`，刻意不碰 volume。

備份 RSA 私鑰：

```bash
docker run --rm -v hpcemail_app_keys:/k -v "$PWD":/backup alpine \
    tar czf /backup/hpcemail-keys-$(date +%F).tar.gz -C /k .
```

---

## 四、已知事項

- **排程通知目前不會執行。** `app.py` 底部的 APScheduler 在
  `if __name__ == '__main__'` 區塊內，而且是註解掉的；用 gunicorn 啟動時
  這段根本不會跑。若要讓 `check_hpc_usage_and_notify` 定期執行，
  需要另外處理（獨立的排程容器，或用 gunicorn 的 `post_fork` hook
  只在單一 worker 啟動 scheduler —— 直接在 app 層啟動會變成 3 個 worker
  各跑一份，通知信重複寄出）。
- **自簽憑證有效期 10 年**，不需要續期。原本的 `renew_cert.sh` 已刪除。
