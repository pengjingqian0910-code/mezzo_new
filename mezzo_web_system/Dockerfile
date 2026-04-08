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

# 將 js 目錄複製到 static 裡（使靜態檔案掛載時可以存取）
RUN cp -r js static/js

# 建立音檔目錄（由外部 volume 掛載時會被覆蓋）
RUN mkdir -p static/audio

EXPOSE 5555

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "5555"]
