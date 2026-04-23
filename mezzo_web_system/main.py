import asyncio, random, json, os, time, base64, io, uuid, wave, re, secrets
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
import paho.mqtt.client as mqtt
from datetime import datetime
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass
from pydantic import BaseModel
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends, HTTPException, Header, File, UploadFile, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse
from typing import Optional
from sqlalchemy import create_engine, Column, Integer, String, ForeignKey, Table, Boolean, Text, text
from sqlalchemy.orm import declarative_base, sessionmaker, relationship, Session

# ====== 環境設定 ======
MQTT_BROKER_HOST = os.getenv("MQTT_BROKER_HOST", "118.163.141.80")
MQTT_BROKER_PORT = int(os.getenv("MQTT_BROKER_PORT", "1688"))
MQTT_TOPIC       = os.getenv("MQTT_TOPIC", "/WJI/PTT/#")
NVR_HOST         = os.getenv("NVR_HOST", "118.163.141.80")
NVR_AUTH         = os.getenv("NVR_AUTH", "YWRtaW46MTIzNA==")  # base64(admin:1234)
AUDIO_BASE_PATH  = os.getenv("AUDIO_BASE_PATH", "static/audio")

os.makedirs(AUDIO_BASE_PATH, exist_ok=True)

# ====== STT (語音轉文字) 相依套件（選裝）======
try:
    from faster_whisper import WhisperModel as _WhisperModelClass
    _WHISPER_IMPORT_OK = True
except ImportError:
    _WhisperModelClass = None
    _WHISPER_IMPORT_OK = False

_whisper_model = None
STT_AVAILABLE  = False

async def _load_whisper_model():
    global _whisper_model, STT_AVAILABLE
    if not _WHISPER_IMPORT_OK:
        print("⚠️  [STT] faster-whisper 未安裝，STT 功能停用")
        return
    try:
        import concurrent.futures
        loop = asyncio.get_running_loop()
        def _load():
            return _WhisperModelClass("base", device="cpu", compute_type="int8")
        _whisper_model = await loop.run_in_executor(None, _load)
        STT_AVAILABLE = True
        print("✅ [STT] faster-whisper 模型載入完成，語音辨識已啟用")
    except Exception as _e:
        print(f"⚠️  [STT] 模型載入失敗 ({_e})，STT 功能停用")

# ====== aiohttp（MJPEG 代理使用，選裝）======
try:
    import aiohttp
    AIOHTTP_AVAILABLE = True
except ImportError:
    aiohttp = None  # type: ignore
    AIOHTTP_AVAILABLE = False
    print("⚠️  [aiohttp] 未安裝，MJPEG 代理功能停用。請執行: pip install aiohttp")

# ====== WebRTC 相依套件（選裝）======
try:
    import av
    from aiortc import RTCPeerConnection, RTCSessionDescription
    from aiortc.mediastreams import VideoStreamTrack
    WEBRTC_AVAILABLE = AIOHTTP_AVAILABLE  # WebRTC 也需要 aiohttp
    if WEBRTC_AVAILABLE:
        print("✅ [WebRTC] aiortc 載入成功，WebRTC 模組已啟用")
    else:
        print("⚠️  [WebRTC] 需要 aiohttp，WebRTC 功能停用")
except ImportError:
    WEBRTC_AVAILABLE = False
    print("⚠️  [WebRTC] 未安裝 aiortc，WebRTC 功能停用。請執行: pip install aiortc aiohttp")

# ====== 資料庫 ======
SQLALCHEMY_DATABASE_URL = "sqlite:///./mezzo.db"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

user_device_link = Table(
    'user_device_link', Base.metadata,
    Column('user_id', Integer, ForeignKey('users.id'), primary_key=True),
    Column('device_id', Integer, ForeignKey('devices.id'), primary_key=True)
)

class User(Base):
    __tablename__ = 'users'
    id            = Column(Integer, primary_key=True, index=True)
    username      = Column(String, unique=True, index=True)
    password      = Column(String)
    email         = Column(String, nullable=True)
    role          = Column(String, default="operator")
    whatsapp      = Column(String, nullable=True)
    manager_id    = Column(Integer, ForeignKey('users.id'), nullable=True)
    managed_users = relationship("User", backref="manager", remote_side=[id])
    devices       = relationship("Device", secondary=user_device_link, backref="users")

class Device(Base):
    __tablename__ = 'devices'
    id        = Column(Integer, primary_key=True, index=True)
    device_id = Column(String, unique=True, index=True)
    name      = Column(String)
    mjpeg_url = Column(String)

class Geofence(Base):
    __tablename__ = 'geofences'
    id         = Column(Integer, primary_key=True, index=True)
    name       = Column(String)
    points     = Column(String)
    is_enabled = Column(Boolean, default=True)

class NVRConfig(Base):
    __tablename__ = 'nvr_config'
    id        = Column(Integer, primary_key=True)
    ip        = Column(String,  default='118.163.141.80')
    http_port = Column(Integer, default=80)
    rtsp_port = Column(Integer, default=1554)
    username  = Column(String,  default='admin')
    password  = Column(String,  default='1234')

class MqttConfig(Base):
    __tablename__ = 'mqtt_config'
    id   = Column(Integer, primary_key=True)
    ip   = Column(String,  default='118.163.141.80')
    port = Column(Integer, default=1688)

class SocialMediaConfig(Base):
    __tablename__ = 'social_media_config'
    id             = Column(Integer, primary_key=True)
    provider       = Column(String,  default="meta")
    access_token   = Column(String,  default="")
    phone_number_id = Column(String, default="")
    account_sid    = Column(String,  default="")
    public_url     = Column(String,  default="")
    stt_keyword    = Column(String,  default="影像傳送")
    is_enabled     = Column(Boolean, default=False)

class GpsRecord(Base):
    __tablename__ = 'gps_records'
    id        = Column(Integer, primary_key=True, index=True)
    device_id = Column(String, index=True)
    lat       = Column(String)
    lng       = Column(String)
    battery   = Column(Integer, default=0)
    status    = Column(String, default="")
    source    = Column(String, default="mqtt")
    timestamp = Column(String, index=True)

class WhatsAppLog(Base):
    __tablename__ = 'whatsapp_logs'
    id               = Column(Integer, primary_key=True, index=True)
    timestamp        = Column(String)
    device_id        = Column(String)
    source           = Column(String, default="mqtt")
    transcript       = Column(Text, default="")
    keyword_detected = Column(Boolean, default=False)
    stream_url       = Column(String, default="")
    recipients       = Column(String, default="")
    status           = Column(String, default="pending")

class SosRecord(Base):
    __tablename__ = 'sos_records'
    id        = Column(Integer, primary_key=True, index=True)
    device_id = Column(String, index=True)
    channel   = Column(String, default='')
    lat       = Column(String, default='0')
    lng       = Column(String, default='0')
    timestamp = Column(String, index=True)

class PttRecord(Base):
    __tablename__ = 'ptt_records'
    id        = Column(Integer, primary_key=True, index=True)
    group_id  = Column(Integer)
    sender    = Column(String)
    text      = Column(String)
    text_zh   = Column(String, default="")
    text_en   = Column(String, default="")
    audio_url = Column(String)
    timestamp = Column(String)

Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()

# ====== Session Token 管理 ======
_sessions: dict = {}

def create_session(username: str, role: str) -> str:
    token = secrets.token_hex(32)
    _sessions[token] = {"username": username, "role": role}
    return token

def get_current_user(authorization: Optional[str] = Header(default=None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="未登入")
    token = authorization[7:]
    user = _sessions.get(token)
    if not user:
        raise HTTPException(status_code=401, detail="Token 無效或已過期，請重新登入")
    return user

def require_admin(user: dict = Depends(get_current_user)):
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="需要管理員權限")
    return user

# ====== NVR / MQTT 動態設定輔助函式 ======
def _get_nvr_cfg():
    db = SessionLocal()
    try:
        cfg = db.query(NVRConfig).first()
        if not cfg:
            cfg = NVRConfig()
            db.add(cfg)
            db.commit()
            db.refresh(cfg)
        return cfg
    finally:
        db.close()

def _nvr_auth_b64(cfg) -> str:
    return base64.b64encode(f"{cfg.username}:{cfg.password}".encode()).decode()

def _nvr_base_url(cfg) -> str:
    return f"http://{cfg.ip}:{cfg.http_port}"

def _get_mqtt_cfg():
    db = SessionLocal()
    try:
        cfg = db.query(MqttConfig).first()
        if not cfg:
            cfg = MqttConfig()
            db.add(cfg)
            db.commit()
        return cfg
    finally:
        db.close()

# ====== FastAPI ======
app = FastAPI(title="WiB VMS Web System")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

@app.get("/")
@app.get("/index_3D.html")
async def get_index():
    return FileResponse("index_3D.html", media_type="text/html")

app.mount("/static", StaticFiles(directory="static"), name="static")

# ====== WebSocket 管理器 ======
class ConnectionManager:
    def __init__(self): self.active_connections = []
    async def connect(self, ws: WebSocket): await ws.accept(); self.active_connections.append(ws)
    def disconnect(self, ws: WebSocket):
        if ws in self.active_connections: self.active_connections.remove(ws)
    async def broadcast(self, msg: dict):
        for conn in list(self.active_connections):
            try: await conn.send_json(msg)
            except: self.active_connections.remove(conn)

manager     = ConnectionManager()
ptt_manager = ConnectionManager()

# ====== 設備即時狀態 (記憶體) ======
devices_state: dict = {}

# PTT 音訊緩衝區
ptt_buffers: dict = {}

# ====== MQTT ======
mqtt_client  = mqtt.Client()
fastapi_loop = None

def on_mqtt_connect(client, userdata, flags, rc):
    cfg = _get_mqtt_cfg()
    print(f"🟢 [MQTT] 連線至 {cfg.ip}:{cfg.port}，rc={rc}")
    client.subscribe("WJI/PTT/#")
    client.subscribe("WJI/GPS/#")
    client.subscribe("/WJI/PTT/#")
    client.subscribe("/WJI/GPS/#")

def on_mqtt_message(client, userdata, msg):
    topic = msg.topic.lstrip('/')

    # 1. GPS 座標
    if topic.endswith("/GPS") or topic.startswith("WJI/GPS/"):
        try:
            raw     = msg.payload
            dev_id  = None
            lat = lng = None
            battery = 0
            status  = "Online"
            try:
                data   = json.loads(raw.decode('utf-8'))
                dev_id = data.get("device_id")
                lng    = data.get("lng")
                lat    = data.get("lat")
                battery = data.get("battery", 0) or 0
                status  = data.get("status", "Online") or "Online"
            except Exception:
                pass
            if dev_id is None:
                txt   = raw.decode('ascii', errors='ignore')
                match = re.search(r'([0-9A-Fa-f]{12}),(-?\d+\.\d+),(-?\d+\.\d+)', txt)
                if match:
                    dev_id = match.group(1).upper()
                    lat    = float(match.group(2))
                    lng    = float(match.group(3))
            if dev_id and lng is not None and lat is not None:
                if dev_id not in devices_state:
                    devices_state[dev_id] = {"lng": lng, "lat": lat, "battery": battery,
                                             "status": status, "last_real_time": 0}
                devices_state[dev_id].update({"lng": lng, "lat": lat, "battery": battery,
                                              "status": status, "last_real_time": time.time()})
                if fastapi_loop:
                    asyncio.run_coroutine_threadsafe(
                        _save_gps_record(dev_id, lat, lng, battery, status, source="mqtt"),
                        fastapi_loop
                    )
        except Exception as e:
            print(f"⚠️  [MQTT GPS] 例外: {e}")

    # 2. PTT 封包
    elif topic.startswith("WJI/PTT/"):
        # SOS 偵測
        if topic.endswith('/SOS'):
            try:
                raw      = msg.payload
                dev_id   = raw[32:160].decode('ascii', errors='ignore').rstrip('\x00').strip().upper()
                data_str = raw[160:].decode('ascii', errors='ignore').rstrip('\x00').strip()
                parts    = data_str.split(',')
                lat      = float(parts[0]) if len(parts) >= 1 else 0.0
                lng      = float(parts[1]) if len(parts) >= 2 else 0.0
                t_parts  = topic.split('/')
                channel  = t_parts[2] if len(t_parts) >= 3 else 'UNKNOWN'
                ts       = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                print(f"🆘 [MQTT SOS] device={dev_id} channel={channel}")
                if fastapi_loop:
                    asyncio.run_coroutine_threadsafe(
                        _save_sos_record(dev_id, channel, lat, lng, ts), fastapi_loop)
                    asyncio.run_coroutine_threadsafe(
                        manager.broadcast({"type": "sos_alert", "data": {
                            "id": str(uuid.uuid4()), "device_id": dev_id,
                            "channel": channel, "lat": lat, "lng": lng, "timestamp": ts
                        }}), fastapi_loop)
            except Exception as e:
                print(f"⚠️  [MQTT SOS] 例外: {e}")

        # PTT 音訊代理
        if fastapi_loop and ptt_manager.active_connections:
            payload_b64 = base64.b64encode(msg.payload).decode('utf-8')
            asyncio.run_coroutine_threadsafe(
                ptt_manager.broadcast({"topic": topic, "payload": payload_b64}),
                fastapi_loop
            )
        # 累積供 STT 分析
        if STT_AVAILABLE and msg.payload and fastapi_loop:
            if topic not in ptt_buffers:
                p = topic.split('/')
                ptt_buffers[topic] = {"data": bytearray(), "last_update": 0.0,
                                      "device_id": p[-1] if len(p) > 2 else "unknown"}
            ptt_buffers[topic]["data"]        += msg.payload
            ptt_buffers[topic]["last_update"]  = time.time()

mqtt_client.on_connect = on_mqtt_connect
mqtt_client.on_message = on_mqtt_message

# ====== WebSocket Endpoints ======
@app.websocket("/ws/map-data")
async def websocket_map(websocket: WebSocket):
    await manager.connect(websocket)
    if devices_state:
        await websocket.send_json({"type": "telemetry_update", "data": devices_state})
    try:
        while True: await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)

@app.websocket("/ws/ptt")
async def websocket_ptt(websocket: WebSocket):
    await ptt_manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            msg  = json.loads(data)
            if msg.get("action") == "publish":
                mqtt_client.publish(msg.get("topic"), msg.get("payload", "").encode('utf-8'))
    except WebSocketDisconnect:
        ptt_manager.disconnect(websocket)

# ====== GPS 資料庫儲存 ======
_gps_last_save: dict = {}
GPS_SAVE_INTERVAL = 5

async def _save_gps_record(device_id: str, lat, lng, battery: int = 0,
                            status: str = "", source: str = "mqtt"):
    now = time.time()
    if now - _gps_last_save.get(device_id, 0) < GPS_SAVE_INTERVAL:
        return
    _gps_last_save[device_id] = now
    db = SessionLocal()
    try:
        db.add(GpsRecord(device_id=device_id, lat=str(lat), lng=str(lng),
                         battery=int(battery), status=status, source=source,
                         timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        db.commit()
    except Exception as e:
        print(f"[GPS DB] 寫入錯誤: {e}")
    finally:
        db.close()

async def _save_sos_record(device_id: str, channel: str, lat, lng, timestamp: str):
    db = SessionLocal()
    try:
        db.add(SosRecord(device_id=device_id, channel=channel,
                         lat=str(lat), lng=str(lng), timestamp=timestamp))
        db.commit()
    except Exception as e:
        print(f"[SOS DB] 寫入錯誤: {e}")
    finally:
        db.close()

# ====== 定期廣播 ======
async def telemetry_broadcaster():
    while True:
        current_time = time.time()
        payload = {}
        for dev_id, state in devices_state.items():
            is_simulated = current_time - state.get("last_real_time", 0) > 5
            payload[dev_id] = {
                "lng": state["lng"], "lat": state["lat"],
                "battery": state["battery"], "status": state["status"],
                "is_realtime": current_time - state.get("last_real_time", 0) <= 30
            }
        await manager.broadcast({"type": "telemetry_update", "data": payload})
        await asyncio.sleep(1)

# ====== STT 函式 ======
def pcm_to_wav_bytes(pcm_data: bytes, sample_rate=8000, channels=1, sampwidth=2) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, 'wb') as wf:
        wf.setnchannels(channels); wf.setsampwidth(sampwidth)
        wf.setframerate(sample_rate); wf.writeframes(pcm_data)
    return buf.getvalue()

def _google_translate(text: str, target_lang: str) -> str:
    if not text.strip(): return ""
    try:
        params = urllib.parse.urlencode({"client": "gtx", "sl": "auto", "tl": target_lang, "dt": "t", "q": text})
        req = urllib.request.Request(
            f"https://translate.googleapis.com/translate_a/single?{params}",
            headers={"User-Agent": "Mozilla/5.0"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        return "".join(item[0] for item in data[0] if item[0]).strip()
    except Exception as e:
        print(f"[STT] Translation error ({target_lang}): {e}")
        return ""

def transcribe_bilingual(audio_path: str) -> tuple:
    if not STT_AVAILABLE or not _whisper_model: return ("", "")
    try:
        segments, info = _whisper_model.transcribe(audio_path, language=None, beam_size=5)
        original_text = "".join(s.text for s in segments).strip()
        detected_lang = (info.language or "").lower()
        if detected_lang == "en":
            text_en = original_text
        else:
            en_segs, _ = _whisper_model.transcribe(audio_path, task="translate", beam_size=5)
            text_en = "".join(s.text for s in en_segs).strip()
        if detected_lang in ("zh", "yue"):
            text_zh = original_text
        else:
            text_zh = _google_translate(text_en or original_text, "zh-TW")
        return (text_zh, text_en)
    except Exception as e:
        print(f"[STT] 雙語辨識錯誤: {e}")
        return ("", "")

def transcribe_pcm_bytes(pcm_data: bytes) -> str:
    if not STT_AVAILABLE or not _whisper_model or len(pcm_data) < 1600: return ""
    try:
        wav_bytes = pcm_to_wav_bytes(pcm_data)
        buf = io.BytesIO(wav_bytes)
        segments, _ = _whisper_model.transcribe(buf, language=None, beam_size=5)
        return "".join(s.text for s in segments).strip()
    except Exception as e:
        print(f"[STT] PCM 辨識錯誤: {e}")
        return ""

# ====== WhatsApp 發送函式 ======
def get_social_config():
    db = SessionLocal()
    cfg = db.query(SocialMediaConfig).first()
    db.close()
    return cfg

def send_whatsapp_message(phone: str, message: str, cfg: SocialMediaConfig) -> tuple:
    phone = phone.strip().lstrip('+')
    if not phone: return False, "no phone"
    try:
        import urllib.request as _ur
        if cfg.provider == "meta":
            url     = f"https://graph.facebook.com/v19.0/{cfg.phone_number_id}/messages"
            headers = {"Authorization": f"Bearer {cfg.access_token}", "Content-Type": "application/json"}
            payload = {"messaging_product": "whatsapp", "to": phone, "type": "text", "text": {"body": message}}
            req = _ur.Request(url, data=json.dumps(payload).encode(), headers=headers, method='POST')
            with _ur.urlopen(req, timeout=10) as resp:
                return resp.status in (200, 201), resp.read().decode()
        elif cfg.provider == "twilio":
            from_num = f"whatsapp:+{cfg.phone_number_id.strip().lstrip('+')}"
            to_num   = f"whatsapp:+{phone}"
            auth_str = base64.b64encode(f"{cfg.account_sid}:{cfg.access_token}".encode()).decode()
            data = urllib.parse.urlencode({"From": from_num, "To": to_num, "Body": message}).encode()
            req  = _ur.Request(
                f"https://api.twilio.com/2010-04-01/Accounts/{cfg.account_sid}/Messages.json",
                data=data, headers={"Authorization": f"Basic {auth_str}"}, method='POST'
            )
            with _ur.urlopen(req, timeout=10) as resp:
                return resp.status in (200, 201), resp.read().decode()
    except Exception as e:
        return False, str(e)
    return False, "unknown provider"

def generate_viewer_url(device_id: str, cfg: SocialMediaConfig) -> str:
    base = (cfg.public_url or "").rstrip('/')
    return f"{base}/view/{device_id}" if base else f"/view/{device_id}"

async def process_transcript_and_notify(device_id: str, transcript: str, source: str = "mqtt"):
    if not transcript: return
    cfg         = get_social_config()
    keyword     = (cfg.stt_keyword if cfg else None) or "影像傳送"
    keyword_hit = keyword in transcript
    stream_url  = ""
    status      = "keyword_not_found"
    recipients  = ""

    if keyword_hit and cfg and cfg.is_enabled:
        stream_url = generate_viewer_url(device_id, cfg)
        db = SessionLocal()
        users_wa = db.query(User).filter(User.whatsapp != None, User.whatsapp != "").all()
        db.close()
        if not users_wa:
            status = "no_recipients"
        else:
            db2 = SessionLocal()
            dev = db2.query(Device).filter(Device.device_id == device_id).first()
            db2.close()
            dev_name = dev.name if dev else device_id
            msg = (f"🚨 *WiB EOC 緊急通知*\n設備: {dev_name} ({device_id})\n"
                   f"時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                   f"語音內容: {transcript}\n──────────────\n"
                   f"📹 即時影像：\n{stream_url}\n──────────────\nWiB EOC 緊急調度指揮系統")
            results = []
            for u in users_wa:
                ok, err = send_whatsapp_message(u.whatsapp, msg, cfg)
                results.append(f"{u.whatsapp}:{'ok' if ok else err[:30]}")
            recipients = ",".join(u.whatsapp for u in users_wa)
            status = "sent" if all(r.endswith(":ok") for r in results) else "partial"
    elif keyword_hit and (not cfg or not cfg.is_enabled):
        status = "disabled"

    db3 = SessionLocal()
    db3.add(WhatsAppLog(
        timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        device_id=device_id, source=source,
        transcript=transcript, keyword_detected=keyword_hit,
        stream_url=stream_url, recipients=recipients, status=status
    ))
    db3.commit()
    db3.close()

async def mqtt_stt_worker():
    while True:
        await asyncio.sleep(1.0)
        if not STT_AVAILABLE: continue
        now = time.time()
        to_process = []
        for topic, buf in list(ptt_buffers.items()):
            if now - buf["last_update"] > 2.0 and len(buf["data"]) > 0:
                to_process.append((topic, bytes(buf["data"]), buf["device_id"]))
                ptt_buffers[topic]["data"] = bytearray()
        for topic, audio_bytes, device_id in to_process:
            loop = asyncio.get_running_loop()
            transcript = await loop.run_in_executor(None, transcribe_pcm_bytes, audio_bytes)
            await process_transcript_and_notify(device_id, transcript, source="mqtt")

# ====== 獨立影像檢視頁面 (WhatsApp 連結用) ======
VIEWER_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-TW">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>WiB 即時影像 — {device_name}</title>
<style>*{{margin:0;padding:0;box-sizing:border-box}}body{{background:#000;color:#fff;font-family:sans-serif;display:flex;flex-direction:column;height:100vh}}
header{{background:#0d1117;padding:10px 20px;display:flex;align-items:center;gap:12px;border-bottom:1px solid #1f2937}}
.logo{{color:#00f6ff;font-weight:bold;font-size:16px}}.dev{{color:#9ca3af;font-size:13px}}
#status{{margin-left:auto;font-size:11px;padding:3px 10px;border-radius:10px;font-weight:bold}}
.connecting{{background:#374151;color:#9ca3af}}.connected{{background:#14532d;color:#4ade80}}.error{{background:#450a0a;color:#f87171}}
video{{flex:1;width:100%;background:#000;display:block}}</style></head>
<body>
<header><div class="logo">WiB EOC</div><div class="dev">即時影像 | {device_name} ({device_id})</div>
<div id="status" class="status connecting">● 連線建立中…</div></header>
<video id="v" autoplay playsinline muted></video>
<script>(async()=>{{const statusEl=document.getElementById('status');const videoEl=document.getElementById('v');
const BACKEND='{backend_url}';const DEVICE_ID='{device_id}';
async function connect(){{const pc=new RTCPeerConnection({{iceServers:[{{urls:'stun:stun.l.google.com:19302'}}]}});
pc.addTransceiver('video',{{direction:'recvonly'}});pc.ontrack=e=>{{if(e.streams[0])videoEl.srcObject=e.streams[0];}};
pc.oniceconnectionstatechange=()=>{{const s=pc.iceConnectionState;
if(s==='connected'||s==='completed'){{statusEl.className='status connected';statusEl.textContent='● 串流播放中';}}
else if(s==='failed'||s==='disconnected'){{statusEl.className='status error';statusEl.textContent='✕ 連線中斷';setTimeout(()=>{{pc.close();connect();}},3000);}}}};
const offer=await pc.createOffer();await pc.setLocalDescription(offer);
await new Promise(r=>{{if(pc.iceGatheringState==='complete')return r();pc.addEventListener('icegatheringstatechange',()=>{{if(pc.iceGatheringState==='complete')r();}});setTimeout(r,5000);}});
const res=await fetch(BACKEND+'/api/webrtc/offer/device/'+DEVICE_ID,{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{sdp:pc.localDescription.sdp,type:pc.localDescription.type}})}});
if(!res.ok)throw new Error('HTTP '+res.status);const ans=await res.json();
await pc.setRemoteDescription(new RTCSessionDescription({{sdp:ans.sdp,type:ans.type}}));}}
try{{await connect();}}catch(e){{statusEl.className='status error';statusEl.textContent='✕ '+e.message;}}
}})();</script></body></html>"""

# ====== 啟動事件 ======
def auto_init_db():
    db = SessionLocal()
    if not db.query(User).filter(User.username == "admin").first():
        db.add(User(username="admin", password="admin", email="admin@mezzo.com", role="admin"))
        db.commit()
    # 初始化 NVRConfig（從環境變數）
    if not db.query(NVRConfig).first():
        try:
            auth_dec = base64.b64decode(NVR_AUTH).decode()
            u, p = auth_dec.split(':', 1)
        except Exception:
            u, p = 'admin', '1234'
        db.add(NVRConfig(ip=NVR_HOST, http_port=80, rtsp_port=1554, username=u, password=p))
        db.commit()
    # 初始化 MqttConfig（從環境變數）
    if not db.query(MqttConfig).first():
        db.add(MqttConfig(ip=MQTT_BROKER_HOST, port=MQTT_BROKER_PORT))
        db.commit()
    # 初始化 SocialMediaConfig
    if not db.query(SocialMediaConfig).first():
        db.add(SocialMediaConfig())
        db.commit()
    # 遷移 ptt_records 表（增加 text_zh / text_en 欄位）
    try:
        with engine.connect() as con:
            existing = [row[1] for row in con.execute(text("PRAGMA table_info(ptt_records)"))]
            if "text_zh" not in existing:
                con.execute(text("ALTER TABLE ptt_records ADD COLUMN text_zh TEXT DEFAULT ''"))
            if "text_en" not in existing:
                con.execute(text("ALTER TABLE ptt_records ADD COLUMN text_en TEXT DEFAULT ''"))
            con.commit()
    except Exception as _e:
        print(f"[DB] Migration warning: {_e}")
    # 遷移 users 表（增加 whatsapp 欄位）
    try:
        with engine.connect() as con:
            existing = [row[1] for row in con.execute(text("PRAGMA table_info(users)"))]
            if "whatsapp" not in existing:
                con.execute(text("ALTER TABLE users ADD COLUMN whatsapp TEXT"))
                con.commit()
    except Exception as _e:
        print(f"[DB] Users migration warning: {_e}")
    db.close()

@app.on_event("startup")
async def startup_event():
    global fastapi_loop
    fastapi_loop = asyncio.get_running_loop()
    auto_init_db()
    asyncio.create_task(telemetry_broadcaster())
    asyncio.create_task(mqtt_stt_worker())
    asyncio.create_task(_load_whisper_model())
    try:
        mqtt_cfg = _get_mqtt_cfg()
        mqtt_client.connect(mqtt_cfg.ip, mqtt_cfg.port, 60)
        mqtt_client.loop_start()
        print(f"🔌 [MQTT] 嘗試連線至 {mqtt_cfg.ip}:{mqtt_cfg.port}")
    except Exception as e:
        print(f"❌ [MQTT] 連線失敗: {e}")

# ====== Auth & User APIs ======
@app.post("/api/login")
def login(data: dict, db: Session = Depends(get_db)):
    user = db.query(User).filter(
        User.username == data.get("username"),
        User.password == data.get("password")
    ).first()
    if not user: raise HTTPException(status_code=401, detail="帳密錯誤")
    token = create_session(user.username, user.role)
    return {"token": token, "username": user.username, "role": user.role}

@app.post("/api/logout")
def logout(authorization: Optional[str] = Header(default=None)):
    if authorization and authorization.startswith("Bearer "):
        _sessions.pop(authorization[7:], None)
    return {"msg": "已登出"}

@app.post("/api/register")
def register(data: dict, db: Session = Depends(get_db)):
    if db.query(User).filter(User.username == data.get("username")).first():
        raise HTTPException(status_code=400, detail="帳號已存在")
    db.add(User(username=data.get("username"), password=data.get("password"),
                email=data.get("email"), role="operator"))
    db.commit()
    return {"msg": "註冊成功"}

@app.get("/api/users")
def get_users(db: Session = Depends(get_db), _user: dict = Depends(get_current_user)):
    return [{"username": u.username, "email": u.email, "role": u.role,
             "whatsapp": u.whatsapp or "",
             "manager": u.manager.username if u.manager else None}
            for u in db.query(User).all()]

@app.put("/api/users/{username}/whatsapp")
def update_whatsapp(username: str, data: dict, db: Session = Depends(get_db),
                    _user: dict = Depends(get_current_user)):
    user = db.query(User).filter(User.username == username).first()
    if not user: raise HTTPException(status_code=404, detail="使用者不存在")
    user.whatsapp = data.get("whatsapp", "").strip()
    db.commit()
    return {"msg": "WhatsApp 號碼已更新"}

@app.put("/api/users/{username}/reset_password")
def reset_pwd(username: str, data: dict, db: Session = Depends(get_db),
              _user: dict = Depends(require_admin)):
    user = db.query(User).filter(User.username == username).first()
    if user: user.password = data.get("new_password")
    db.commit()
    return {"msg": "密碼已重設"}

@app.put("/api/users/{username}/assign_manager")
def assign_mgr(username: str, data: dict, db: Session = Depends(get_db),
               _user: dict = Depends(require_admin)):
    user = db.query(User).filter(User.username == username).first()
    mgr  = db.query(User).filter(User.username == data.get("manager_username")).first()
    user.manager_id = mgr.id if mgr else None
    user.role = data.get("role", user.role)
    db.commit()
    return {"msg": "權限與群組已更新"}

# ====== Device APIs ======
def _device_dict(d):
    rtsp_url = ""
    if d.mjpeg_url:
        m = re.search(r"ch=(\d+)", d.mjpeg_url)
        if m:
            cfg = _get_nvr_cfg()
            ch_rtsp = int(m.group(1)) + 1
            rtsp_url = f"rtsp://{cfg.username}:{cfg.password}@{cfg.ip}:{cfg.rtsp_port}/ch{ch_rtsp}"
    return {"device_id": d.device_id, "name": d.name,
            "mjpeg_url": d.mjpeg_url or "", "rtsp_url": rtsp_url}

@app.get("/api/devices")
def get_devices(username: str = None, db: Session = Depends(get_db)):
    if not username: return []
    user = db.query(User).filter(User.username == username).first()
    if not user: return []
    if user.role == "admin":
        devices = db.query(Device).all()
    elif user.role == "group_manager":
        dev_set = set(user.devices)
        for u in user.managed_users:
            for d in u.devices: dev_set.add(d)
        devices = list(dev_set)
    else:
        devices = user.devices
    return [_device_dict(d) for d in devices]

@app.get("/api/admin/all_devices")
def get_all_devices(db: Session = Depends(get_db)):
    return [_device_dict(d) for d in db.query(Device).all()]

@app.get("/api/devices/available")
def get_available_devices(username: str, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == username).first()
    if not user: return []
    bound_ids = {d.device_id for d in user.devices}
    return [{"device_id": d.device_id, "name": d.name}
            for d in db.query(Device).all() if d.device_id not in bound_ids]

@app.post("/api/devices")
def add_device(dev: dict, db: Session = Depends(get_db)):
    if db.query(Device).filter(Device.device_id == dev.get("device_id")).first():
        raise HTTPException(status_code=400, detail="DeviceID 已存在系統")
    db.add(Device(device_id=dev.get("device_id"), name=dev.get("name"),
                  mjpeg_url=dev.get("mjpeg_url", "")))
    db.commit()
    return {"msg": "設備註冊成功"}

@app.delete("/api/devices/{device_id}")
def del_device(device_id: str, db: Session = Depends(get_db)):
    db.query(Device).filter(Device.device_id == device_id).delete()
    db.commit()
    return {"msg": "刪除成功"}

@app.post("/api/users/{username}/bind")
def bind_device(username: str, data: dict, db: Session = Depends(get_db),
                current_user: dict = Depends(get_current_user)):
    if current_user["role"] == "operator" and current_user["username"] != username:
        raise HTTPException(status_code=403, detail="只能綁定自己的帳號")
    user   = db.query(User).filter(User.username == username).first()
    device = db.query(Device).filter(Device.device_id == data.get("device_id")).first()
    if not device: raise HTTPException(status_code=404, detail="找不到此設備 ID")
    if device not in user.devices: user.devices.append(device); db.commit()
    return {"msg": "設備綁定成功"}

@app.delete("/api/users/{username}/unbind/{device_id}")
def unbind_device(username: str, device_id: str, db: Session = Depends(get_db),
                  current_user: dict = Depends(get_current_user)):
    if current_user["role"] == "operator" and current_user["username"] != username:
        raise HTTPException(status_code=403, detail="只能解除綁定自己的帳號")
    user   = db.query(User).filter(User.username == username).first()
    device = db.query(Device).filter(Device.device_id == device_id).first()
    if device in user.devices: user.devices.remove(device); db.commit()
    return {"msg": "解除綁定成功"}

@app.post("/api/me/bind_device")
def operator_self_bind(data: dict, db: Session = Depends(get_db),
                       current_user: dict = Depends(get_current_user)):
    device_id = data.get("device_id", "").strip()
    if not device_id: raise HTTPException(status_code=400, detail="device_id 不可為空")
    user = db.query(User).filter(User.username == current_user["username"]).first()
    if current_user["role"] == "operator" and user.devices:
        user.devices.clear()
    device = db.query(Device).filter(Device.device_id == device_id).first()
    if not device:
        device = Device(device_id=device_id, name=device_id, mjpeg_url="")
        db.add(device)
    if device not in user.devices:
        user.devices.append(device)
    db.commit()
    return {"msg": f"已綁定設備 {device_id}", "device_id": device_id}

# ====== NVR 動態設定 API ======
@app.get("/api/nvr/config")
def get_nvr_config_api():
    cfg = _get_nvr_cfg()
    return {"ip": cfg.ip, "http_port": cfg.http_port, "rtsp_port": cfg.rtsp_port,
            "username": cfg.username, "password": cfg.password,
            "auth_b64": _nvr_auth_b64(cfg)}

class NVRConfigBody(BaseModel):
    ip: str; http_port: int; rtsp_port: int; username: str; password: str

@app.put("/api/nvr/config")
def update_nvr_config(body: NVRConfigBody, db: Session = Depends(get_db),
                      _user: dict = Depends(require_admin)):
    cfg = db.query(NVRConfig).first()
    if not cfg: cfg = NVRConfig(); db.add(cfg)
    cfg.ip = body.ip; cfg.http_port = body.http_port; cfg.rtsp_port = body.rtsp_port
    cfg.username = body.username; cfg.password = body.password
    db.commit()
    return {"msg": "NVR 設定已儲存"}

# ====== MQTT 動態設定 API ======
@app.get("/api/mqtt/config")
def get_mqtt_config_api():
    cfg = _get_mqtt_cfg()
    return {"ip": cfg.ip, "port": cfg.port}

class MqttConfigBody(BaseModel):
    ip: str; port: int

@app.put("/api/mqtt/config")
def update_mqtt_config(body: MqttConfigBody, db: Session = Depends(get_db),
                       _user: dict = Depends(require_admin)):
    cfg = db.query(MqttConfig).first()
    if not cfg: cfg = MqttConfig(); db.add(cfg)
    cfg.ip = body.ip; cfg.port = body.port
    db.commit()
    return {"msg": "MQTT 設定已儲存"}

@app.post("/api/mqtt/reconnect")
def mqtt_reconnect_api(_user: dict = Depends(require_admin)):
    cfg = _get_mqtt_cfg()
    try:
        mqtt_client.disconnect()
        time.sleep(0.5)
        mqtt_client.connect(cfg.ip, cfg.port, 60)
        return {"msg": f"Reconnecting to {cfg.ip}:{cfg.port}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ====== NVR 即時 APIs ======
@app.get("/api/nvr/server_info")
def get_nvr_server_info():
    cfg  = _get_nvr_cfg()
    auth = _nvr_auth_b64(cfg)
    base = _nvr_base_url(cfg)
    try:
        url = f"{base}/GetServerInfo.cgi?Auth={auth}"
        req = urllib.request.Request(url)
        req.add_header("Authorization", f"Basic {auth}")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = resp.read().decode('utf-8')
            try: return json.loads(data)
            except json.JSONDecodeError:
                fixed = re.sub(r'([{,]\s*)([a-zA-Z0-9_]+)\s*:', r'\1"\2":', data)
                return json.loads(fixed)
    except Exception as e:
        print(f"[NVR] GetServerInfo error: {e}")
        raise HTTPException(status_code=500, detail="無法連線至 NVR")

@app.get("/api/nvr/cameras")
def get_nvr_cameras():
    cfg  = _get_nvr_cfg()
    auth = _nvr_auth_b64(cfg)
    base = _nvr_base_url(cfg)
    try:
        url = f"{base}/CameraList.cgi?Auth={auth}"
        req = urllib.request.Request(url)
        req.add_header("Authorization", f"Basic {auth}")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = resp.read().decode('utf-8')
            try: return json.loads(data)
            except json.JSONDecodeError:
                fixed = re.sub(r'([{,]\s*)([a-zA-Z0-9_]+)\s*:', r'\1"\2":', data)
                return json.loads(fixed)
    except Exception as e:
        print(f"[NVR] CameraList error: {e}")
        raise HTTPException(status_code=500, detail="無法連線至 NVR")

@app.get("/api/nvr/record_status")
def get_nvr_record_status(channel: int, time_str: str):
    cfg  = _get_nvr_cfg()
    auth = _nvr_auth_b64(cfg)
    base = _nvr_base_url(cfg)
    try:
        url = f"{base}/GetRecordStatus.cgi?time={urllib.parse.quote(time_str)}&type=month&channels={channel}&Auth={auth}"
        req = urllib.request.Request(url)
        req.add_header("Authorization", f"Basic {auth}")
        with urllib.request.urlopen(req, timeout=5) as resp:
            root = ET.fromstring(resp.read().decode('utf-8'))
            data_node = root.find(".//Data")
            if data_node is not None and data_node.text:
                sl = list(data_node.text.strip())
                while len(sl) < 31: sl.append('0')
                return {"status_array": sl[:31]}
    except Exception as e:
        print(f"[NVR] RecordStatus error: {e}")
    return {"status_array": ["0"] * 31}

# ====== NVR 歷史影像 APIs ======
@app.get("/api/nvr/history")
def get_nvr_history(channels: str, begin_time: str, end_time: str):
    cfg  = _get_nvr_cfg()
    auth = _nvr_auth_b64(cfg)
    base = _nvr_base_url(cfg)
    try:
        params = urllib.parse.urlencode({
            "BeginTime": begin_time, "EndTime": end_time,
            "Channels": channels, "Auth": auth
        }, quote_via=urllib.parse.quote)
        req = urllib.request.Request(f"{base}/GetBackupList.cgi?{params}")
        req.add_header("Authorization", f"Basic {auth}")
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = resp.read().decode('utf-8')
            try: return json.loads(data)
            except json.JSONDecodeError: return {"raw": data}
    except Exception as e:
        print(f"[NVR] GetBackupList error: {e}")
        raise HTTPException(status_code=500, detail="無法取得 NVR 歷史清單")

@app.get("/api/nvr/query_event")
def query_nvr_events(begin_time: str, end_time: str, event_type: str = "",
                     device_id: str = "", start: int = 0, limit: int = 100):
    cfg  = _get_nvr_cfg()
    auth = _nvr_auth_b64(cfg)
    base = _nvr_base_url(cfg)
    try:
        params = {"BeginTime": begin_time, "EndTime": end_time, "Auth": auth,
                  "Start": start, "Limit": limit}
        if event_type: params["EventType"] = event_type
        if device_id:  params["DeviceID"] = device_id
        qs  = urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
        req = urllib.request.Request(f"{base}/QueryEvent.cgi?{qs}")
        req.add_header("Authorization", f"Basic {auth}")
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = resp.read().decode('utf-8')
            try: return json.loads(data)
            except json.JSONDecodeError: return {"raw": data}
    except Exception as e:
        print(f"[NVR] QueryEvent error: {e}")
        raise HTTPException(status_code=500, detail="無法查詢 NVR 事件")

@app.get("/api/nvr/download/avi")
def download_nvr_avi(tag: str):
    from fastapi.responses import RedirectResponse
    cfg  = _get_nvr_cfg()
    auth = _nvr_auth_b64(cfg)
    base = _nvr_base_url(cfg)
    params = urllib.parse.urlencode({"Tag": tag, "Auth": auth})
    return RedirectResponse(url=f"{base}/GetAVIMedia.cgi?{params}")

@app.get("/api/nvr/download/raw")
def download_nvr_raw(tag: str):
    from fastapi.responses import RedirectResponse
    cfg  = _get_nvr_cfg()
    auth = _nvr_auth_b64(cfg)
    base = _nvr_base_url(cfg)
    params = urllib.parse.urlencode({"Tag": tag, "Auth": auth})
    return RedirectResponse(url=f"{base}/BackupMedia.cgi?{params}")

@app.get("/api/nvr/live_stream/{channel}")
def get_nvr_live_stream(channel: int):
    from fastapi.responses import RedirectResponse
    cfg  = _get_nvr_cfg()
    auth = _nvr_auth_b64(cfg)
    base = _nvr_base_url(cfg)
    params = urllib.parse.urlencode({"Auth": auth, "ch": channel, "metadata": "0"})
    return RedirectResponse(url=f"{base}/mjpeg_stream.cgi?{params}")

@app.get("/api/nvr/playback_stream/{channel}")
def get_nvr_playback_stream(channel: int, time: str):
    from fastapi.responses import RedirectResponse
    cfg  = _get_nvr_cfg()
    auth = _nvr_auth_b64(cfg)
    base = _nvr_base_url(cfg)
    params = urllib.parse.urlencode({
        "Auth": auth, "ch": channel, "clientid": "web",
        "playback": urllib.parse.quote(time)
    })
    return RedirectResponse(url=f"{base}/mjpeg_stream.cgi?{params}")

@app.get("/api/nvr/snapshot/{channel}")
def get_nvr_snapshot(channel: int, time: str = ""):
    from fastapi.responses import RedirectResponse
    cfg  = _get_nvr_cfg()
    auth = _nvr_auth_b64(cfg)
    base = _nvr_base_url(cfg)
    params = {"Ch": channel, "Auth": auth}
    if time: params["Time"] = time
    return RedirectResponse(url=f"{base}/Snapshot.cgi?{urllib.parse.urlencode(params)}")

# ====== 即時設備位置 API ======
@app.get("/api/devices/positions")
def get_device_positions():
    return devices_state

@app.get("/api/gps/realtime")
def gps_realtime():
    return {dev_id: {"lat": s["lat"], "lng": s["lng"],
                     "battery": s["battery"], "status": s["status"],
                     "is_realtime": time.time() - s.get("last_real_time", 0) <= 10}
            for dev_id, s in devices_state.items()}

@app.get("/api/gps/history")
def gps_history(device_ids: str, start: str = None, end: str = None,
                limit: int = 2000, source: str = None, db: Session = Depends(get_db)):
    ids = [d.strip() for d in device_ids.split(",") if d.strip()]
    if not ids: raise HTTPException(400, "至少提供一個 device_id")
    query = db.query(GpsRecord).filter(GpsRecord.device_id.in_(ids))
    if start:  query = query.filter(GpsRecord.timestamp >= start)
    if end:    query = query.filter(GpsRecord.timestamp <= end)
    if source: query = query.filter(GpsRecord.source == source)
    records = query.order_by(GpsRecord.timestamp.asc()).limit(limit).all()
    result: dict = {}
    for r in records:
        if r.device_id not in result: result[r.device_id] = []
        result[r.device_id].append({"lat": float(r.lat), "lng": float(r.lng),
                                    "battery": r.battery, "status": r.status,
                                    "source": r.source, "timestamp": r.timestamp})
    return result

@app.get("/api/gps/history/{device_id}")
def gps_history_single(device_id: str, start: str = None, end: str = None,
                       limit: int = 1000, source: str = None, db: Session = Depends(get_db)):
    query = db.query(GpsRecord).filter(GpsRecord.device_id == device_id)
    if start:  query = query.filter(GpsRecord.timestamp >= start)
    if end:    query = query.filter(GpsRecord.timestamp <= end)
    if source: query = query.filter(GpsRecord.source == source)
    records = query.order_by(GpsRecord.timestamp.asc()).limit(limit).all()
    return [{"lat": float(r.lat), "lng": float(r.lng),
             "battery": r.battery, "status": r.status,
             "source": r.source, "timestamp": r.timestamp} for r in records]

# ====== SOS 記錄 API ======
@app.get("/api/sos/records")
def get_sos_records(limit: int = 100, db: Session = Depends(get_db)):
    rows = db.query(SosRecord).order_by(SosRecord.id.desc()).limit(limit).all()
    return [{"id": r.id, "device_id": r.device_id, "channel": r.channel,
             "lat": float(r.lat or 0), "lng": float(r.lng or 0),
             "timestamp": r.timestamp} for r in rows]

# ====== Geofence APIs ======
@app.get("/api/geofences")
def get_geofences(db: Session = Depends(get_db)):
    return [{"id": g.id, "name": g.name, "points": g.points, "is_enabled": g.is_enabled}
            for g in db.query(Geofence).all()]

@app.post("/api/geofences")
def add_geofence(geo: dict, db: Session = Depends(get_db)):
    db.add(Geofence(name=geo.get("name"), points=geo.get("points"))); db.commit(); return {}

@app.put("/api/geofences/{geo_id}")
def update_geofence(geo_id: int, geo: dict, db: Session = Depends(get_db)):
    g = db.query(Geofence).filter(Geofence.id == geo_id).first()
    if not g: raise HTTPException(status_code=404, detail="找不到警戒區")
    if "is_enabled" in geo: g.is_enabled = geo["is_enabled"]
    if "name" in geo:       g.name = geo["name"]
    if "points" in geo:     g.points = geo["points"]
    db.commit(); return {}

@app.delete("/api/geofences/{geo_id}")
def del_geofence(geo_id: int, db: Session = Depends(get_db)):
    db.query(Geofence).filter(Geofence.id == geo_id).delete(); db.commit(); return {}

# ====== 音檔服務 API ======
@app.get("/api/audio/{device_id}/{filename}")
def serve_audio(device_id: str, filename: str):
    safe_device_id = os.path.basename(device_id)
    safe_filename  = os.path.basename(filename)
    audio_path = os.path.join(AUDIO_BASE_PATH, safe_device_id, safe_filename)
    if not os.path.exists(audio_path):
        raise HTTPException(status_code=404, detail="音檔不存在")
    return FileResponse(audio_path)

@app.get("/api/audio/{device_id}")
def list_audio(device_id: str):
    safe_device_id = os.path.basename(device_id)
    device_audio_dir = os.path.join(AUDIO_BASE_PATH, safe_device_id)
    if not os.path.isdir(device_audio_dir): return []
    files = sorted(os.listdir(device_audio_dir))
    return [{"filename": f, "url": f"/api/audio/{safe_device_id}/{f}"} for f in files]

# ====== PTT 記錄 API ======
@app.post("/api/ptt/records")
async def upload_ptt_record(group_id: int = Form(...), sender: str = Form(...),
                            text: str = Form(""), audio: UploadFile = File(...),
                            db: Session = Depends(get_db)):
    raw_bytes = await audio.read()
    orig_name = audio.filename or "audio"
    if orig_name.endswith('.raw'):
        raw_bytes = pcm_to_wav_bytes(raw_bytes, sample_rate=8000, channels=1, sampwidth=2)
        orig_name = orig_name[:-4] + '.wav'
    file_name = f"ptt_{int(time.time())}_{orig_name}"
    file_path = f"static/audio/{file_name}"
    with open(file_path, "wb") as f:
        f.write(raw_bytes)
    text_zh, text_en = ("", "")
    if STT_AVAILABLE:
        loop = asyncio.get_running_loop()
        text_zh, text_en = await loop.run_in_executor(None, transcribe_bilingual, file_path)
    elif text.strip():
        text_zh = text
    final_text = text_zh or text_en or text
    db.add(PttRecord(group_id=group_id, sender=sender, text=final_text,
                     text_zh=text_zh, text_en=text_en,
                     audio_url=f"/{file_path}",
                     timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    db.commit()
    asyncio.create_task(process_transcript_and_notify(sender, final_text, source="upload"))
    return {"msg": "錄音儲存成功", "transcript": final_text, "text_zh": text_zh, "text_en": text_en}

@app.get("/api/ptt/records")
def get_ptt_records(group_id: int = None, db: Session = Depends(get_db)):
    query = db.query(PttRecord)
    if group_id: query = query.filter(PttRecord.group_id == group_id)
    records = query.order_by(PttRecord.id.desc()).all()
    return [{"id": r.id, "group_id": r.group_id, "sender": r.sender, "text": r.text,
             "text_zh": r.text_zh or "", "text_en": r.text_en or "",
             "audio_url": r.audio_url, "timestamp": r.timestamp} for r in records]

# ====== Social Media / WhatsApp API ======
@app.get("/api/social/config")
def get_social_cfg(db: Session = Depends(get_db)):
    cfg = db.query(SocialMediaConfig).first()
    if not cfg: return {}
    return {"provider": cfg.provider, "access_token": cfg.access_token,
            "phone_number_id": cfg.phone_number_id, "account_sid": cfg.account_sid,
            "public_url": cfg.public_url, "stt_keyword": cfg.stt_keyword,
            "is_enabled": cfg.is_enabled}

@app.put("/api/social/config")
def update_social_cfg(data: dict, db: Session = Depends(get_db),
                      _user: dict = Depends(require_admin)):
    cfg = db.query(SocialMediaConfig).first()
    if not cfg: cfg = SocialMediaConfig(); db.add(cfg)
    for field in ("provider", "access_token", "phone_number_id", "account_sid",
                  "public_url", "stt_keyword", "is_enabled"):
        if field in data: setattr(cfg, field, data[field])
    db.commit()
    return {"msg": "設定已儲存"}

@app.get("/api/social/logs")
def get_social_logs(limit: int = 50, db: Session = Depends(get_db)):
    logs = db.query(WhatsAppLog).order_by(WhatsAppLog.id.desc()).limit(limit).all()
    return [{"id": l.id, "timestamp": l.timestamp, "device_id": l.device_id,
             "source": l.source, "transcript": l.transcript,
             "keyword_detected": l.keyword_detected, "stream_url": l.stream_url,
             "recipients": l.recipients, "status": l.status} for l in logs]

@app.post("/api/social/test")
async def test_whatsapp(data: dict, db: Session = Depends(get_db)):
    cfg = db.query(SocialMediaConfig).first()
    if not cfg: raise HTTPException(400, "尚未設定 WhatsApp 參數")
    phone = data.get("phone", "").strip()
    msg   = data.get("message", "WiB EOC 測試訊息 — 系統運作正常 ✅")
    ok, detail = send_whatsapp_message(phone, msg, cfg)
    return {"success": ok, "detail": detail}

@app.get("/api/social/stt_status")
def stt_status():
    return {"available": STT_AVAILABLE, "model": "faster-whisper base" if STT_AVAILABLE else None}

# ====== 獨立影像檢視頁面 ======
@app.get("/view/{device_id}", response_class=HTMLResponse)
def viewer_page(device_id: str, db: Session = Depends(get_db)):
    dev = db.query(Device).filter(Device.device_id == device_id).first()
    if not dev: raise HTTPException(404, "設備不存在")
    cfg = db.query(SocialMediaConfig).first()
    backend_url = (cfg.public_url if cfg else "").rstrip('/')
    html = VIEWER_HTML_TEMPLATE.format(
        device_id=device_id, device_name=dev.name, backend_url=backend_url)
    return HTMLResponse(html)

# ====== WebRTC API ======
webrtc_pcs: dict = {}

if WEBRTC_AVAILABLE:
    class MJPEGStreamTrack(VideoStreamTrack):
        kind = "video"
        def __init__(self, mjpeg_url: str):
            super().__init__()
            self.mjpeg_url = mjpeg_url
            self._queue: asyncio.Queue = asyncio.Queue(maxsize=5)
            self._fetch_task = None

        async def _fetch_frames(self):
            while True:
                buf = b""
                try:
                    timeout = aiohttp.ClientTimeout(connect=10, total=None)
                    async with aiohttp.ClientSession(timeout=timeout) as sess:
                        async with sess.get(self.mjpeg_url) as resp:
                            if resp.status != 200:
                                await asyncio.sleep(3); continue
                            async for chunk in resp.content.iter_chunked(8192):
                                buf += chunk
                                while True:
                                    s = buf.find(b'\xff\xd8')
                                    if s == -1: buf = b""; break
                                    e = buf.find(b'\xff\xd9', s + 2)
                                    if e == -1: buf = buf[s:]; break
                                    jpeg = buf[s:e + 2]; buf = buf[e + 2:]
                                    if not self._queue.full():
                                        await self._queue.put(jpeg)
                except asyncio.CancelledError: return
                except Exception as ex:
                    print(f"[WebRTC] MJPEG 擷取錯誤，重連: {ex}")
                    await asyncio.sleep(3)

        def _make_black_frame(self, pts, time_base):
            frame = av.VideoFrame(640, 360, "yuv420p")
            for p in frame.planes: p.update(bytes(p.buffer_size))
            frame.pts = pts; frame.time_base = time_base; return frame

        async def recv(self):
            if self._fetch_task is None:
                self._fetch_task = asyncio.ensure_future(self._fetch_frames())
            pts, time_base = await self.next_timestamp()
            try:
                jpeg = await asyncio.wait_for(self._queue.get(), timeout=5.0)
            except asyncio.TimeoutError:
                return self._make_black_frame(pts, time_base)
            try:
                container = av.open(io.BytesIO(jpeg), format="mjpeg")
                for pkt in container.demux(video=0):
                    for frm in pkt.decode():
                        out = frm.reformat(format="yuv420p")
                        out.pts = pts; out.time_base = time_base; return out
            except Exception: pass
            return self._make_black_frame(pts, time_base)

        def stop(self):
            if self._fetch_task and not self._fetch_task.done():
                self._fetch_task.cancel()
            super().stop()

    class RTSPStreamTrack(VideoStreamTrack):
        kind = "video"
        def __init__(self, rtsp_url: str):
            super().__init__()
            self.rtsp_url = rtsp_url
            self._queue: asyncio.Queue = asyncio.Queue(maxsize=5)
            self._fetch_task = None

        async def _fetch_frames(self):
            loop = asyncio.get_running_loop()
            while True:
                stop_flag = {"stop": False}
                container = None
                try:
                    def _stream_worker():
                        nonlocal container
                        container = av.open(self.rtsp_url, options={"rtsp_transport": "tcp", "stimeout": "5000000"})
                        vs = container.streams.video[0]; vs.thread_type = "AUTO"
                        for packet in container.demux(vs):
                            if stop_flag["stop"] or packet.size == 0: break
                            for frame in packet.decode():
                                out = frame.reformat(format="yuv420p")
                                asyncio.run_coroutine_threadsafe(self._put_frame(out), loop)
                    await loop.run_in_executor(None, _stream_worker)
                except asyncio.CancelledError: stop_flag["stop"] = True; break
                except Exception as ex:
                    print(f"[WebRTC/RTSP] 擷取錯誤，重連: {ex}"); await asyncio.sleep(3)
                finally:
                    stop_flag["stop"] = True
                    if container:
                        try: container.close()
                        except Exception: pass

        async def _put_frame(self, frame):
            if not self._queue.full(): await self._queue.put(frame)

        async def recv(self):
            if self._fetch_task is None:
                self._fetch_task = asyncio.ensure_future(self._fetch_frames())
            pts, time_base = await self.next_timestamp()
            try:
                frame = await asyncio.wait_for(self._queue.get(), timeout=8.0)
                frame.pts = pts; frame.time_base = time_base; return frame
            except asyncio.TimeoutError:
                f = av.VideoFrame(640, 360, "yuv420p")
                for p in f.planes: p.update(bytes(p.buffer_size))
                f.pts = pts; f.time_base = time_base; return f

        def stop(self):
            if self._fetch_task and not self._fetch_task.done():
                self._fetch_task.cancel()
            super().stop()

    def _make_video_track(stream_url: str):
        if stream_url.startswith("rtsp://") or stream_url.startswith("rtsps://"):
            return RTSPStreamTrack(stream_url)
        return MJPEGStreamTrack(stream_url)

class WebRTCOfferBody(BaseModel):
    sdp: str; type: str
    mjpeg_url: str = ""; rtsp_url: str = ""

@app.post("/api/webrtc/offer")
async def webrtc_offer(body: WebRTCOfferBody):
    if not WEBRTC_AVAILABLE:
        raise HTTPException(status_code=503, detail="WebRTC 模組未安裝")
    stream_url = body.rtsp_url or body.mjpeg_url
    if not stream_url:
        raise HTTPException(status_code=400, detail="需提供 rtsp_url 或 mjpeg_url")
    offer = RTCSessionDescription(sdp=body.sdp, type=body.type)
    pc    = RTCPeerConnection()
    pc_id = str(uuid.uuid4())
    webrtc_pcs[pc_id] = pc
    track = _make_video_track(stream_url)
    pc.addTrack(track)
    @pc.on("connectionstatechange")
    async def on_conn_state():
        if pc.connectionState in ("failed", "closed"):
            track.stop(); await pc.close(); webrtc_pcs.pop(pc_id, None)
    await pc.setRemoteDescription(offer)
    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)
    elapsed = 0.0
    while pc.iceGatheringState != "complete" and elapsed < 10.0:
        await asyncio.sleep(0.1); elapsed += 0.1
    return {"sdp": pc.localDescription.sdp, "type": pc.localDescription.type, "pc_id": pc_id}

@app.delete("/api/webrtc/{pc_id}")
async def webrtc_close(pc_id: str):
    pc = webrtc_pcs.pop(pc_id, None)
    if pc: await pc.close()
    return {"msg": "closed"}

@app.get("/api/webrtc/status")
def webrtc_status():
    return {"available": WEBRTC_AVAILABLE, "active_connections": len(webrtc_pcs)}

class DeviceOfferBody(BaseModel):
    sdp: str; type: str

@app.post("/api/webrtc/offer/device/{device_id}")
async def webrtc_offer_by_device(device_id: str, body: DeviceOfferBody,
                                  db: Session = Depends(get_db)):
    dev = db.query(Device).filter(Device.device_id == device_id).first()
    if not dev: raise HTTPException(404, "設備不存在")
    if not WEBRTC_AVAILABLE: raise HTTPException(503, "WebRTC 模組未安裝")
    stream_url = dev.mjpeg_url or ""
    if stream_url:
        m = re.search(r"ch=(\d+)", stream_url)
        if m:
            cfg = _get_nvr_cfg()
            ch_rtsp = int(m.group(1)) + 1
            stream_url = f"rtsp://{cfg.username}:{cfg.password}@{cfg.ip}:{cfg.rtsp_port}/ch{ch_rtsp}"
    if not stream_url: raise HTTPException(400, "此設備無可用串流 URL")
    offer = RTCSessionDescription(sdp=body.sdp, type=body.type)
    pc    = RTCPeerConnection()
    pc_id = str(uuid.uuid4())
    webrtc_pcs[pc_id] = pc
    track = _make_video_track(stream_url)
    pc.addTrack(track)
    @pc.on("connectionstatechange")
    async def on_state():
        if pc.connectionState in ("failed", "closed"):
            track.stop(); await pc.close(); webrtc_pcs.pop(pc_id, None)
    await pc.setRemoteDescription(offer)
    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)
    elapsed = 0.0
    while pc.iceGatheringState != "complete" and elapsed < 10.0:
        await asyncio.sleep(0.1); elapsed += 0.1
    return {"sdp": pc.localDescription.sdp, "type": pc.localDescription.type, "pc_id": pc_id}

# ====== NVR Viewer 獨立查看器 ======
# 第三方 / 外部使用者可用 /api/nvrv/login 取得 token
# 內部使用者直接帶 mezzo Bearer token 即可（使用 DB 中的 NVR 設定）

_nvrv_sessions: dict = {}   # nvrv_token -> {base_url, auth_b64, created_at}

def _resolve_nvrv(nvrv_token: str = "", authorization: str = None):
    """
    回傳 (base_url, auth_b64)。
    優先使用 nvrv_token（外部第三方），否則用 mezzo Bearer token（內部）。
    """
    if nvrv_token and nvrv_token in _nvrv_sessions:
        sess = _nvrv_sessions[nvrv_token]
        if time.time() - sess["created_at"] < 86400:  # 24 小時 TTL
            return sess["base_url"], sess["auth_b64"]
        _nvrv_sessions.pop(nvrv_token, None)
    if authorization and authorization.startswith("Bearer "):
        token = authorization[7:]
        if token in _sessions:
            cfg = _get_nvr_cfg()
            return _nvr_base_url(cfg), _nvr_auth_b64(cfg)
    raise HTTPException(status_code=401, detail="請先登入 NVR 或提供有效的 Mezzo Token")

@app.get("/nvr", response_class=HTMLResponse)
async def nvr_viewer_page():
    return FileResponse("nvr_viewer.html", media_type="text/html")

@app.post("/api/nvrv/login")
async def nvrv_login(data: dict):
    """第三方登入：驗證 NVR 帳密，回傳 24h session token"""
    ip       = data.get("ip", "").strip()
    port     = int(data.get("port", 80))
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()
    if not ip or not username:
        raise HTTPException(400, "需要提供 IP 與帳號")
    base_url = f"http://{ip}:{port}"
    auth_b64 = base64.b64encode(f"{username}:{password}".encode()).decode()
    # 用 GetServerInfo.cgi 驗證連線
    try:
        req = urllib.request.Request(f"{base_url}/GetServerInfo.cgi?Auth={auth_b64}")
        req.add_header("Authorization", f"Basic {auth_b64}")
        with urllib.request.urlopen(req, timeout=8) as resp:
            if resp.status not in (200, 206):
                raise HTTPException(401, "NVR 帳密錯誤或無法連線")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"無法連線至 NVR ({ip}:{port}): {e}")
    token = secrets.token_hex(32)
    _nvrv_sessions[token] = {"base_url": base_url, "auth_b64": auth_b64, "created_at": time.time()}
    return {"token": token, "msg": "登入成功", "base_url": base_url}

@app.post("/api/nvrv/logout")
async def nvrv_logout(data: dict):
    _nvrv_sessions.pop(data.get("token", ""), None)
    return {"msg": "已登出"}

@app.get("/api/nvrv/server_info")
def nvrv_server_info(token: str = "", authorization: Optional[str] = Header(default=None)):
    base_url, auth_b64 = _resolve_nvrv(token, authorization)
    try:
        req = urllib.request.Request(f"{base_url}/GetServerInfo.cgi?Auth={auth_b64}")
        req.add_header("Authorization", f"Basic {auth_b64}")
        with urllib.request.urlopen(req, timeout=8) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            try:
                return json.loads(raw)
            except Exception:
                fixed = re.sub(r'([{,]\s*)([a-zA-Z0-9_]+)\s*:', r'\1"\2":', raw)
                try:
                    return json.loads(fixed)
                except Exception:
                    return {"raw": raw}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"NVR server_info 錯誤: {e}")

@app.get("/api/nvrv/cameras")
def nvrv_cameras(token: str = "", authorization: Optional[str] = Header(default=None)):
    base_url, auth_b64 = _resolve_nvrv(token, authorization)
    try:
        req = urllib.request.Request(f"{base_url}/CameraList.cgi?Auth={auth_b64}")
        req.add_header("Authorization", f"Basic {auth_b64}")
        with urllib.request.urlopen(req, timeout=8) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            try:
                return json.loads(raw)
            except Exception:
                fixed = re.sub(r'([{,]\s*)([a-zA-Z0-9_]+)\s*:', r'\1"\2":', raw)
                try:
                    return json.loads(fixed)
                except Exception:
                    return {"raw": raw}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"NVR cameras 錯誤: {e}")

@app.get("/api/nvrv/mjpeg/{ch}")
async def nvrv_mjpeg(ch: int, token: str = "",
                     authorization: Optional[str] = Header(default=None)):
    """MJPEG 即時串流代理（解決 CORS 及跨網路存取問題）"""
    from fastapi.responses import StreamingResponse as SR
    base_url, auth_b64 = _resolve_nvrv(token, authorization)
    nvr_url = f"{base_url}/mjpeg_stream.cgi?Auth={auth_b64}&ch={ch}&metadata=0"

    if not AIOHTTP_AVAILABLE:
        from fastapi.responses import RedirectResponse
        return RedirectResponse(nvr_url)

    sess = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(connect=10, total=None))
    try:
        resp = await sess.get(nvr_url)
        if resp.status != 200:
            await resp.release(); await sess.close()
            raise HTTPException(502, f"NVR MJPEG 回應 {resp.status}")
        content_type = resp.headers.get("Content-Type", "multipart/x-mixed-replace; boundary=ipcamera")

        async def gen():
            try:
                async for chunk in resp.content.iter_chunked(8192):
                    yield chunk
            except (asyncio.CancelledError, Exception):
                pass
            finally:
                try: resp.release()
                except Exception: pass
                try: await sess.close()
                except Exception: pass

        return SR(gen(), media_type=content_type,
                  headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
    except HTTPException:
        await sess.close(); raise
    except Exception as e:
        await sess.close()
        raise HTTPException(502, f"MJPEG 代理連線失敗: {e}")

@app.get("/api/nvrv/playback/{ch}")
async def nvrv_playback(ch: int, time_str: str, token: str = "",
                        authorization: Optional[str] = Header(default=None)):
    """MJPEG 回放串流代理"""
    from fastapi.responses import StreamingResponse as SR
    base_url, auth_b64 = _resolve_nvrv(token, authorization)
    params = urllib.parse.urlencode({
        "Auth": auth_b64, "ch": ch, "clientid": "web",
        "playback": time_str
    }, quote_via=urllib.parse.quote)
    nvr_url = f"{base_url}/mjpeg_stream.cgi?{params}"

    if not AIOHTTP_AVAILABLE:
        from fastapi.responses import RedirectResponse
        return RedirectResponse(nvr_url)

    sess = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(connect=10, total=None))
    try:
        resp = await sess.get(nvr_url)
        if resp.status != 200:
            await resp.release(); await sess.close()
            raise HTTPException(502, f"NVR 回放回應 {resp.status}")
        content_type = resp.headers.get("Content-Type", "multipart/x-mixed-replace; boundary=ipcamera")

        async def gen():
            try:
                async for chunk in resp.content.iter_chunked(8192):
                    yield chunk
            except (asyncio.CancelledError, Exception):
                pass
            finally:
                try: resp.release()
                except Exception: pass
                try: await sess.close()
                except Exception: pass

        return SR(gen(), media_type=content_type,
                  headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
    except HTTPException:
        await sess.close(); raise
    except Exception as e:
        await sess.close()
        raise HTTPException(502, f"回放代理連線失敗: {e}")

@app.get("/api/nvrv/snapshot/{ch}")
async def nvrv_snapshot(ch: int, time_str: str = "", token: str = "",
                        authorization: Optional[str] = Header(default=None)):
    """擷取單張 JPEG 截圖"""
    from fastapi.responses import Response as Resp
    base_url, auth_b64 = _resolve_nvrv(token, authorization)
    params: dict = {"Ch": ch, "Auth": auth_b64}
    if time_str:
        params["Time"] = time_str
    nvr_url = f"{base_url}/Snapshot.cgi?{urllib.parse.urlencode(params, quote_via=urllib.parse.quote)}"

    if not AIOHTTP_AVAILABLE:
        from fastapi.responses import RedirectResponse
        return RedirectResponse(nvr_url)

    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=8)) as sess:
            async with sess.get(nvr_url) as resp:
                data = await resp.read()
                ct = resp.headers.get("Content-Type", "image/jpeg")
        return Resp(content=data, media_type=ct)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"Snapshot 失敗: {e}")

@app.get("/api/nvrv/recordings")
def nvrv_recordings(ch: int, begin_time: str, end_time: str,
                    token: str = "", authorization: Optional[str] = Header(default=None)):
    """取得指定時間段的錄影清單"""
    base_url, auth_b64 = _resolve_nvrv(token, authorization)
    params = urllib.parse.urlencode({
        "BeginTime": begin_time, "EndTime": end_time,
        "Channels": ch, "Auth": auth_b64
    }, quote_via=urllib.parse.quote)
    try:
        req = urllib.request.Request(f"{base_url}/GetBackupList.cgi?{params}")
        req.add_header("Authorization", f"Basic {auth_b64}")
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            try:
                return json.loads(raw)
            except Exception:
                return {"raw": raw}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"錄影清單查詢失敗: {e}")

@app.get("/api/nvrv/download")
def nvrv_download(tag: str, fmt: str = "avi", token: str = "",
                  authorization: Optional[str] = Header(default=None)):
    """下載錄影檔案（AVI 壓縮版或 RAW 原始檔）"""
    from fastapi.responses import RedirectResponse
    base_url, auth_b64 = _resolve_nvrv(token, authorization)
    if fmt == "raw":
        params = urllib.parse.urlencode({"Tag": tag, "Auth": auth_b64})
        return RedirectResponse(f"{base_url}/BackupMedia.cgi?{params}")
    params = urllib.parse.urlencode({"Tag": tag, "Auth": auth_b64})
    return RedirectResponse(f"{base_url}/GetAVIMedia.cgi?{params}")

@app.get("/api/nvrv/record_status")
def nvrv_record_status(ch: int, time_str: str, token: str = "",
                       authorization: Optional[str] = Header(default=None)):
    """取得月份錄影狀態陣列"""
    base_url, auth_b64 = _resolve_nvrv(token, authorization)
    try:
        url = (f"{base_url}/GetRecordStatus.cgi"
               f"?time={urllib.parse.quote(time_str)}&type=month&channels={ch}&Auth={auth_b64}")
        req = urllib.request.Request(url)
        req.add_header("Authorization", f"Basic {auth_b64}")
        with urllib.request.urlopen(req, timeout=8) as resp:
            root = ET.fromstring(resp.read().decode("utf-8", errors="replace"))
            node = root.find(".//Data")
            if node is not None and node.text:
                sl = list(node.text.strip())
                while len(sl) < 31: sl.append("0")
                return {"status_array": sl[:31]}
    except HTTPException:
        raise
    except Exception as e:
        print(f"[NVRv] record_status 錯誤: {e}")
    return {"status_array": ["0"] * 31}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=80, reload=True)
