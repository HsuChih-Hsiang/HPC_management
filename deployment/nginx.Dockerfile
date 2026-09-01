# syntax=docker/dockerfile:1
#
# 自訂 nginx image：只比官方多一個 openssl，用來在容器啟動時
# 產生自簽憑證。裝在 image 裡而不是每次啟動 apk add，
# 是為了讓服務在沒有外網、或 alpine repo 掛掉時仍然起得來。
FROM nginx:1.27-alpine

RUN apk add --no-cache openssl

# nginx 官方 entrypoint 會依序執行 /docker-entrypoint.d/ 底下的 *.sh
COPY 10-selfsigned-cert.sh /docker-entrypoint.d/10-selfsigned-cert.sh
RUN chmod +x /docker-entrypoint.d/10-selfsigned-cert.sh
