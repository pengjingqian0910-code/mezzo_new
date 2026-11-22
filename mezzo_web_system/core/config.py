"""
設定模組
--------
環境變數，以及 PyJWT、aiohttp 兩個選裝套件的檢查。

STT（faster-whisper）、WebRTC（aiortc）的選裝檢查刻意留在 main.py：
- STT：啟動時才用 global 把 STT_AVAILABLE 改成 True，放這裡 main.py 會讀不到更新後的值
- WebRTC：沒裝 aiortc 時 av / RTCPeerConnection 等名稱不存在，main.py 無法 from config import

這支檔案不 import main。
"""
import os

# 讀環境變數前先載入 .env（main.py 開頭也有一份，重複呼叫沒有影響）
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ====== 環境設定 ======
MQTT_BROKER_HOST = os.getenv("MQTT_BROKER_HOST", "118.163.141.80")
MQTT_BROKER_PORT = int(os.getenv("MQTT_BROKER_PORT", "1688"))
MQTT_TOPIC       = os.getenv("MQTT_TOPIC", "/WJI/PTT/#")
NVR_HOST         = os.getenv("NVR_HOST", "118.163.141.80")
NVR_AUTH         = os.getenv("NVR_AUTH", "QWRtaW46MTIzNA==")  # base64(Admin:1234)
AUDIO_BASE_PATH  = os.getenv("AUDIO_BASE_PATH", "static/audio")
NVR_MEDIA_PATH   = os.getenv("NVR_MEDIA_PATH", r"C:\Media")
TAK_SERVER_HOST  = os.getenv("TAK_SERVER_HOST", "")
TAK_SERVER_PORT  = int(os.getenv("TAK_SERVER_PORT", "8087"))

os.makedirs(AUDIO_BASE_PATH, exist_ok=True)


# ====== PyJWT（v1 API 認證用）======
try:
    import jwt as _pyjwt
    JWT_AVAILABLE = True
except ImportError:
    _pyjwt = None  # type: ignore
    JWT_AVAILABLE = False
    print("[JWT] PyJWT not installed, v1 API JWT disabled. Run: pip install PyJWT")

JWT_SECRET = os.getenv("JWT_SECRET", "mezzo_eoc_jwt_secret_change_me_in_production")
JWT_EXPIRE_HOURS = int(os.getenv("JWT_EXPIRE_HOURS", "24"))

# ====== aiohttp（MJPEG 代理使用，選裝）======
try:
    import aiohttp
    AIOHTTP_AVAILABLE = True
except ImportError:
    aiohttp = None  # type: ignore
    AIOHTTP_AVAILABLE = False
    print("[aiohttp] not installed, MJPEG proxy disabled. Run: pip install aiohttp")
