FROM python:3.11-slim

WORKDIR /app

# 安裝系統依賴
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# 安裝 Python 依賴
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 複製應用程式
COPY . .

# 建立音檔目錄與靜態資源（build 時預先複製，volume 掛載時由 entrypoint.sh 覆蓋）
RUN mkdir -p static/audio && cp WiB.png static/WiB.png

# entrypoint：每次啟動時同步 js/ → static/js/，再起 uvicorn
COPY entrypoint.sh /entrypoint.sh
RUN sed -i 's/\r$//' /entrypoint.sh && chmod +x /entrypoint.sh

EXPOSE 80

CMD ["/entrypoint.sh"]
