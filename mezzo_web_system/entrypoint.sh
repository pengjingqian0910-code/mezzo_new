#!/bin/bash
# 每次容器啟動時，將 js/ 同步到 static/js/ 並補齊靜態資源（支援 volume 掛載部署）
mkdir -p /app/static/audio
cp -r /app/js /app/static/
# WiB.png：volume 掛載後 build 時的複製被蓋掉，需在啟動時補回
if [ -f /app/WiB.png ] && [ ! -f /app/static/WiB.png ]; then
    cp /app/WiB.png /app/static/WiB.png
fi

exec uvicorn main:app --host 0.0.0.0 --port 80
