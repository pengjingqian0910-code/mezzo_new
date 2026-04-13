#!/bin/bash
# 每次容器啟動時，將 js/ 同步到 static/js/（支援 volume 掛載部署）
mkdir -p /app/static
cp -r /app/js /app/static/

exec uvicorn main:app --host 0.0.0.0 --port 80
