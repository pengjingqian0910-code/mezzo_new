# Mezzo EOC Web System

WiB 緊急指揮中心（EOC）整合系統，提供即時 NVR 影像、MQTT 裝置追蹤、PTT 語音，並整合 ATAK 戰術感知平台。

## 功能

- NVR 即時串流（FMP4 / MJPEG）與歷史影像回放（AVI + ffmpeg）
- MQTT 即時 GPS 追蹤與歷史軌跡
- PTT 語音即時 WebSocket 串流
- 地理圍欄管理
- **ATAK 整合**：GPS CoT 自動推送、NVR Video Link 推送

## 快速啟動

### 前置需求

- Python 3.10+
- ffmpeg（AVI 影像轉碼用）

```bash
# Windows
winget install ffmpeg

# Ubuntu
sudo apt install ffmpeg
```

### 安裝與啟動

```bash
pip install fastapi uvicorn sqlalchemy paho-mqtt aiohttp pyjwt python-multipart
cd mezzo_web_system
python main.py
```

伺服器預設在 `http://0.0.0.0:80` 啟動。

### 環境變數（選填）

```env
MQTT_BROKER_HOST=118.163.141.80
MQTT_BROKER_PORT=1688
NVR_HOST=127.0.0.1
NVR_AUTH=QWRtaW46MTIzNA==   # base64(Admin:1234)
NVR_MEDIA_PATH=C:\Media
TAK_SERVER_HOST=             # OpenTAKServer IP（可留空）
TAK_SERVER_PORT=8087
TAK_TCP_PORT=8087            # 本系統的 ATAK TCP 接收 port
```

---

## ATAK 整合

### 架構

```
MQTT GPS 裝置
     ↓
Mezzo Server（port 80）
     ↓ CoT XML（TCP port 8087 + UDP Multicast 239.2.3.1:6969）
ATAK 客戶端（手機 / 平板）
```

### 安裝 OpenTAKServer（選用，進階）

> 若只需要手機直接收 GPS 標記，可跳過此步驟，直接用下方 ATAK 設定。

**Ubuntu / Raspberry Pi（推薦）：**
```bash
curl -s -L https://i.opentakserver.io/ubuntu_installer | bash -
```

**Windows：**
```powershell
# 以系統管理員身分執行 PowerShell
Set-ExecutionPolicy Bypass -Scope Process -Force
.\windows_installer.ps1
```

安裝完成後 Web UI：`http://<伺服器IP>:8080`
預設帳號：`administrator` / `password`

OpenTAKServer GitHub：https://github.com/brian7704/OpenTAKServer

---

### ATAK 手機 App 設定

#### 下載 ATAK

| 平台 | 來源 |
|------|------|
| Android（ATAK-CIV） | [Google Play](https://play.google.com/store/apps/details?id=com.atakmap.app.civ) |
| Android（ATAK 完整版） | [TAK.gov](https://tak.gov)（需申請帳號）|
| iOS（iTAK） | [App Store](https://apps.apple.com/app/itak/id1561716415) |

#### 連線設定（TCP 模式）

手機與 Mezzo 伺服器須在**同一個 WiFi 網段**。

1. ATAK → 右上角齒輪 **Settings**
2. **Network** → **Manage Server Connections** → **+**
3. 填入：
   - **Description**: `Mezzo EOC`
   - **Address**: `<Mezzo 伺服器 IP>`
   - **Port**: `8087`
   - **Protocol**: `TCP`
4. 儲存並連線

連線成功後，Mezzo 收到 MQTT GPS 資料時會自動在 ATAK 地圖顯示裝置位置。

#### 測試連線

連線後呼叫以下 API 發送測試標記：

```bash
# 1. 登入取得 token
curl -X POST http://<伺服器IP>/api/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin"}'

# 2. 發送測試 GPS CoT
curl -X POST "http://<伺服器IP>/api/tak/test_send?lat=25.0&lon=121.5&callsign=TEST" \
  -H "Authorization: Bearer <token>"
```

ATAK 地圖出現 **TEST** 標記即代表連線正常。

#### 推送 NVR 影像連結

```bash
curl -X POST http://<伺服器IP>/api/tak/push_video \
  -H "Authorization: Bearer <token>"
```

ATAK 的 **Video** 功能會收到所有 NVR 頻道的 RTSP 連結。

> **注意：** NVR 的 RTSP 位址需為手機可連到的 IP（非 127.0.0.1），請在後台 `PUT /api/nvr/config` 更新 NVR IP。

---

## API 文件

伺服器啟動後瀏覽：`http://<伺服器IP>/docs`

### 主要端點

| 類別 | 端點 | 說明 |
|------|------|------|
| 認證 | `POST /api/login` | Web UI 登入 |
| 認證 | `POST /api/v1/auth/login` | JWT 登入（外部系統用）|
| NVR | `GET /api/nvr/server_info` | NVR 伺服器資訊 |
| NVR | `GET /api/nvr/live_stream/{ch}` | 即時 MJPEG 串流 |
| NVR | `GET /api/nvr/local/stream` | AVI 歷史影像播放 |
| GPS | `GET /api/gps/realtime` | 所有裝置即時位置 |
| GPS | `GET /api/gps/history/{device_id}` | 歷史軌跡 |
| ATAK | `GET /api/tak/config` | 讀取 TAK 設定 |
| ATAK | `PUT /api/tak/config` | 更新 TAK 設定 |
| ATAK | `POST /api/tak/test_send` | 發送測試 CoT |
| ATAK | `POST /api/tak/push_video` | 推送 NVR 影像連結 |
| ATAK | `GET /api/tak/status` | 測試 TAK Server 連線 |

---

## 部署（延平主機）

```bash
# 打包
tar -czf mezzo_deploy.tar.gz mezzo_web_system/

# 傳至遠端並啟動
scp mezzo_deploy.tar.gz user@<主機IP>:~/
ssh user@<主機IP>
tar -xzf mezzo_deploy.tar.gz
cd mezzo_web_system
python main.py
```
