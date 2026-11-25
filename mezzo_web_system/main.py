# [拆分 nvr_viewer.py] secrets 只有 NVR Viewer 的 /api/nvrv/login 在用，已隨路由搬到 features/nvr_viewer.py，main.py 不再使用
# 原本：import asyncio, random, json, os, time, base64, io, uuid, wave, re, secrets
import asyncio, random, json, os, time, base64, io, uuid, wave, re
import urllib.request
import urllib.parse
# [拆分 nvr_viewer.py] ET 只有 NVR Viewer 的 record_status 在用，已隨路由搬到 features/nvr_viewer.py，main.py 不再使用
# import xml.etree.ElementTree as ET
# [拆分 tak.py] timedelta 只有 TAK 的 _cot_time 在用，已隨 TAK 程式搬到 features/tak.py，main.py 不再使用
# from datetime import timedelta
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
# [拆分 database.py] 下面這些 sqlalchemy 名稱只有 Model 定義在用，已隨 Model 搬到 database.py，main.py 不再使用
# from sqlalchemy import create_engine, Column, Integer, String, ForeignKey, Table, Boolean, Text, text
# from sqlalchemy.orm import declarative_base, sessionmaker, relationship, Session
from sqlalchemy import text
from sqlalchemy.orm import Session

# ====== 環境設定 ======
# 環境變數，以及 PyJWT、aiohttp 的選裝檢查搬到 config.py 了
# （STT、WebRTC 的選裝檢查還留在下面，之後跟各自的模組一起拆，原因見 config.py 開頭說明）
# [搬移] config.py 搬到 core/config.py。原本：from config import (
from core.config import (
    MQTT_BROKER_HOST, MQTT_BROKER_PORT, MQTT_TOPIC,
    # [拆分 nvr.py] NVR_MEDIA_PATH 只有 NVR 本機磁碟 API 在用，已隨路由搬到 features/nvr.py，main.py 不再使用
    # 原本：NVR_HOST, NVR_AUTH, AUDIO_BASE_PATH, NVR_MEDIA_PATH,
    NVR_HOST, NVR_AUTH, AUDIO_BASE_PATH,
    TAK_SERVER_HOST, TAK_SERVER_PORT,
    # [拆分 auth.py] _pyjwt、JWT_SECRET 只有 JWT 函式在用，已隨函式搬到 core/auth.py，main.py 不再使用
    # 原本：_pyjwt, JWT_AVAILABLE, JWT_SECRET, JWT_EXPIRE_HOURS,
    JWT_AVAILABLE, JWT_EXPIRE_HOURS,
    aiohttp, AIOHTTP_AVAILABLE,
)

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
        print("[STT] faster-whisper not installed, STT disabled")
        return
    try:
        import concurrent.futures
        loop = asyncio.get_running_loop()
        def _load():
            return _WhisperModelClass("base", device="cpu", compute_type="int8")
        _whisper_model = await loop.run_in_executor(None, _load)
        STT_AVAILABLE = True
        print("[STT] faster-whisper model loaded, STT enabled")
    except Exception as _e:
        print(f"[STT] model load failed ({_e}), STT disabled")

# ====== WebRTC 相依套件（選裝）======
try:
    import av
    from aiortc import RTCPeerConnection, RTCSessionDescription
    from aiortc.mediastreams import VideoStreamTrack
    WEBRTC_AVAILABLE = AIOHTTP_AVAILABLE  # WebRTC 也需要 aiohttp
    if WEBRTC_AVAILABLE:
        print("[WebRTC] aiortc loaded, WebRTC enabled")
    else:
        print("[WebRTC] aiohttp required, WebRTC disabled")
except ImportError:
    WEBRTC_AVAILABLE = False
    print("[WebRTC] aiortc not installed, WebRTC disabled. Run: pip install aiortc aiohttp")

# ====== 資料庫 ======
# engine / SessionLocal / Base / 所有資料表 Model / get_db 搬到 database.py 了
# [搬移] database.py 搬到 core/database.py。原本：from database import (
from core.database import (
    engine, SessionLocal, Base,
    User, Device, NVRConfig, MqttConfig, SocialMediaConfig, TakServerConfig,
    GpsRecord, WhatsAppLog, SosRecord, PttRecord,
    get_db,
)

# Geofence / GeofenceEvent 模型定義在 geofence.py，由 database.py 呼叫 init_models() 註冊（原因見下方 [修正]）；
# router 部分要等 get_current_user / manager 等依賴都定義好之後才能組出來，見下面 geofence.init_router()。
# [搬移] geofence.py 搬到 features/geofence.py。原本：import geofence   # 下面 geofence.init_router() 還會用到，保留
from features import geofence   # 下面 geofence.init_router() 還會用到，保留
# [修正] init_models() 改到 database.py 裡呼叫。python main.py（reload 模式）會讓 main.py 被執行兩次
# （__main__ / __mp_main__ 與 uvicorn 匯入的 main），但 database 模組只載入一次、Base 是同一份，
# 留在這裡會對同一個 Base 重複註冊 → "Table 'geofences' is already defined"。
# Geofence, GeofenceEvent = geofence.init_models(Base)
# [搬移] 原本：from database import Geofence, GeofenceEvent
from core.database import Geofence, GeofenceEvent

# 所有 Model（含 geofence 的兩張表）都註冊完才建表
Base.metadata.create_all(bind=engine)

# ====== TAK TCP Server（供 ATAK 客戶端連線）／ TAK / CoT 模組 ======
# TAK_TCP_PORT、_tak_clients、TCP Server、CoT 產生與送出、forward_gps_to_tak 搬到 features/tak.py 了（原樣搬移）
# 下面的 TAK Server APIs（5 個 /api/tak/* 路由）也一起搬過去，改成 router，在原位置 include_router
from features.tak import forward_gps_to_tak, _start_tak_tcp_server, router as tak_router

# ====== Session Token 管理（Web UI 用）／ JWT 工具（v1 API 用）======
# _sessions、create_session、get_current_user、_v1_err、_create_jwt、_decode_jwt、
# get_v1_user、require_v1_admin、require_admin 搬到 core/auth.py 了（原樣搬移）
from core.auth import (
    _sessions, create_session, get_current_user,
    _v1_err, _create_jwt, _decode_jwt, get_v1_user, require_v1_admin, require_admin,
)

# ====== NVR / MQTT 動態設定輔助函式 ======
# _get_nvr_cfg、_nvr_auth_b64、_nvr_base_url 搬到 features/nvr.py 了（原樣搬移）；_get_mqtt_cfg 屬於 MQTT，留在這裡
from features.nvr import (
    _get_nvr_cfg, _nvr_auth_b64, _nvr_base_url,
    config_router as nvr_config_router, router as nvr_router,
)

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
# ConnectionManager、manager、ptt_manager 搬到 core/ws_manager.py 了（原樣搬移）
# main.py 只用到 manager、ptt_manager 兩個實例，ConnectionManager 類別本身不再用到，所以不匯入
# 原本會用到的寫法：from core.ws_manager import ConnectionManager, manager, ptt_manager
from core.ws_manager import manager, ptt_manager

# ====== 設備即時狀態 (記憶體) ======
devices_state: dict = {}

# PTT 音訊緩衝區（STT 用）
ptt_buffers: dict = {}

# v1 API 即時音訊訂閱佇列：device_id → set of asyncio.Queue
_audio_ws_queues: dict = {}

# ====== MQTT ======
mqtt_client  = mqtt.Client()
fastapi_loop = None

def on_mqtt_connect(client, userdata, flags, rc):
    cfg = _get_mqtt_cfg()
    print(f"[MQTT] connected to {cfg.ip}:{cfg.port}, rc={rc}")
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
                    asyncio.run_coroutine_threadsafe(
                        forward_gps_to_tak(dev_id, lat, lng, battery),
                        fastapi_loop
                    )
                    asyncio.run_coroutine_threadsafe(
                        check_geofence_and_notify(dev_id, lat, lng),
                        fastapi_loop
                    )
        except Exception as e:
            print(f"[MQTT GPS] exception: {e}")

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
                print(f"[MQTT SOS] exception: {e}")

        # PTT 音訊代理
        if fastapi_loop and ptt_manager.active_connections:
            payload_b64 = base64.b64encode(msg.payload).decode('utf-8')
            asyncio.run_coroutine_threadsafe(
                ptt_manager.broadcast({"topic": topic, "payload": payload_b64}),
                fastapi_loop
            )
        # 轉發到 v1 API 即時語音訂閱佇列
        if fastapi_loop and _audio_ws_queues:
            t_parts  = topic.split('/')
            dev_id_ptt = t_parts[-1] if len(t_parts) >= 3 else "unknown"
            if dev_id_ptt in _audio_ws_queues:
                payload_b64 = base64.b64encode(msg.payload).decode()
                packet = {"type": "audio", "device_id": dev_id_ptt,
                          "payload_b64": payload_b64,
                          "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S")}
                for q in list(_audio_ws_queues[dev_id_ptt]):
                    if not q.full():
                        asyncio.run_coroutine_threadsafe(q.put(packet), fastapi_loop)

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

# Geofence 伺服器端偵測 + 通知邏輯搬到 geofence.py 的 check_geofence_and_notify()

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

# 警戒區 router 需要的依賴（get_current_user、manager、send_whatsapp_message...）到這裡都齊了，
# 呼叫 geofence.init_router() 組出 router 跟偵測函式。
geofence_router, check_geofence_and_notify = geofence.init_router(
    Geofence, GeofenceEvent, SessionLocal, get_current_user, manager,
    User, Device, get_social_config, send_whatsapp_message, generate_viewer_url
)
app.include_router(geofence_router)

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
        db.add(NVRConfig(ip=NVR_HOST, http_port=80, rtsp_port=2554, username=u, password=p))
        db.commit()
    # 初始化 MqttConfig（從環境變數）
    if not db.query(MqttConfig).first():
        db.add(MqttConfig(ip=MQTT_BROKER_HOST, port=MQTT_BROKER_PORT))
        db.commit()
    # 初始化 SocialMediaConfig
    if not db.query(SocialMediaConfig).first():
        db.add(SocialMediaConfig())
        db.commit()
    # 初始化 TakServerConfig
    if not db.query(TakServerConfig).first():
        db.add(TakServerConfig(host=TAK_SERVER_HOST, port=TAK_SERVER_PORT, enabled=bool(TAK_SERVER_HOST)))
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
    asyncio.create_task(_start_tak_tcp_server())
    try:
        mqtt_cfg = _get_mqtt_cfg()
        mqtt_client.connect(mqtt_cfg.ip, mqtt_cfg.port, 60)
        mqtt_client.loop_start()
        print(f"[MQTT] connecting to {mqtt_cfg.ip}:{mqtt_cfg.port}")
    except Exception as e:
        print(f"[MQTT] connection failed: {e}")

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
# /api/nvr/config（GET / PUT）與 NVRConfigBody 搬到 features/nvr.py 的 config_router 了（原樣搬移，@app 改 @config_router）
# 放在原本的位置 include，路由順序跟搬移前一樣
app.include_router(nvr_config_router)

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

# ====== TAK Server APIs ======
# 5 個 /api/tak/* 路由與 TakConfigBody 搬到 features/tak.py 了（原樣搬移，@app 改 @router）
# 放在原本的位置 include，路由順序跟搬移前一樣
app.include_router(tak_router)

# ====== NVR 即時 APIs ／ NVR 歷史影像 APIs ／ NVR 本機磁碟影像 API ======
# 這 15 個 /api/nvr/* 路由搬到 features/nvr.py 的 router 了（原樣搬移，@app 改 @router）
# 放在原本的位置 include，路由順序跟搬移前一樣
app.include_router(nvr_router)

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

# ====== Geofence APIs：搬到 geofence.py 的 router 了，見下方 app.include_router(geofence_router) ======

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

# ======================================================================
# EOC Web Service RESTful API  v1.0
# 路徑前綴：/api/v1/
# 認證：Bearer JWT（外部合作廠商）或 Session Token（內部 Web UI）
# ======================================================================

def _v1_device_status(device: Device) -> dict:
    """組合單一設備的即時狀態"""
    state = devices_state.get(device.device_id, {})
    last_ts = state.get("last_real_time", 0)
    online   = last_ts > 0 and (time.time() - last_ts) <= 300   # 5 分鐘內算在線
    return {
        "device_id":      device.device_id,
        "name":           device.name,
        "online":         online,
        "last_heartbeat": (datetime.fromtimestamp(last_ts).strftime("%Y-%m-%dT%H:%M:%SZ")
                           if last_ts else None),
        "battery":        state.get("battery", None),
        "signal_strength": state.get("signal_strength", None),   # MQTT 目前未提供
        "lat":            state.get("lat", None),
        "lng":            state.get("lng", None),
        "status":         state.get("status", "offline" if not online else "online"),
    }

def _get_user_devices(username: str, role: str, db: Session):
    """依角色取得使用者可存取的設備列表"""
    user = db.query(User).filter(User.username == username).first()
    if not user:
        return []
    if role == "admin":
        return db.query(Device).all()
    if role == "group_manager":
        dev_set = set(user.devices)
        for u in user.managed_users:
            for d in u.devices:
                dev_set.add(d)
        return list(dev_set)
    return user.devices  # operator

# ── Module 1: Auth ─────────────────────────────────────────────────────

@app.post("/api/v1/auth/login")
def v1_login(data: dict, db: Session = Depends(get_db)):
    """取得 Bearer JWT Token（有效期 24 小時）"""
    user = db.query(User).filter(
        User.username == data.get("username"),
        User.password == data.get("password")
    ).first()
    if not user:
        raise _v1_err("INVALID_CREDENTIALS", "帳號或密碼錯誤", 401)
    token = _create_jwt(user.username, user.role)
    return {
        "token":      token,
        "token_type": "Bearer",
        "expires_in": JWT_EXPIRE_HOURS * 3600,
        "username":   user.username,
        "role":       user.role
    }

@app.post("/api/v1/users")
def v1_create_user(data: dict, db: Session = Depends(get_db),
                   _u: dict = Depends(require_v1_admin)):
    """建立後台帳號（需 Admin 權限）"""
    username = (data.get("username") or "").strip()
    password = (data.get("password") or "").strip()
    role     = data.get("role", "operator")
    if not username or not password:
        raise _v1_err("INVALID_PARAMS", "username / password 不可為空")
    if role not in ("operator", "group_manager", "admin"):
        raise _v1_err("INVALID_PARAMS", "role 必須為 operator / group_manager / admin")
    if db.query(User).filter(User.username == username).first():
        raise _v1_err("DUPLICATE_USER", f"帳號 {username} 已存在", 409)
    db.add(User(username=username, password=password,
                email=data.get("email", ""), role=role))
    db.commit()
    return {"message": f"帳號 {username} 建立成功", "username": username, "role": role}

# ── Module 1: Mapping ──────────────────────────────────────────────────

@app.post("/api/v1/mapping/assign")
def v1_assign_device(data: dict, db: Session = Depends(get_db),
                     _u: dict = Depends(require_v1_admin)):
    """將 DeviceID 綁定至指定 UserID（username）"""
    username  = (data.get("userId") or data.get("username") or "").strip()
    device_id = (data.get("deviceId") or data.get("device_id") or "").strip()
    if not username or not device_id:
        raise _v1_err("INVALID_PARAMS", "userId / deviceId 不可為空")
    user   = db.query(User).filter(User.username == username).first()
    if not user:
        raise _v1_err("NOT_FOUND", f"找不到使用者 {username}", 404)
    device = db.query(Device).filter(Device.device_id == device_id).first()
    if not device:
        raise _v1_err("NOT_FOUND", f"找不到設備 {device_id}", 404)
    if device not in user.devices:
        user.devices.append(device)
        db.commit()
    return {
        "message":   f"設備 {device_id} 已綁定至 {username}",
        "userId":    username,
        "deviceId":  device_id
    }

@app.delete("/api/v1/mapping/assign")
def v1_unassign_device(data: dict, db: Session = Depends(get_db),
                       _u: dict = Depends(require_v1_admin)):
    """解除 DeviceID 與 UserID 的綁定"""
    username  = (data.get("userId") or "").strip()
    device_id = (data.get("deviceId") or "").strip()
    user   = db.query(User).filter(User.username == username).first()
    device = db.query(Device).filter(Device.device_id == device_id).first()
    if user and device and device in user.devices:
        user.devices.remove(device)
        db.commit()
    return {"message": f"已解除綁定 {device_id} ← {username}"}

@app.get("/api/v1/mapping/devices/{userId}")
def v1_user_devices(userId: str, db: Session = Depends(get_db),
                    current: dict = Depends(get_v1_user)):
    """查詢指定使用者可存取的設備清單"""
    # operator 只能查自己
    if current["role"] == "operator" and current["username"] != userId:
        raise _v1_err("FORBIDDEN", "只能查詢自己的設備清單", 403)
    devices = _get_user_devices(userId, current["role"] if current["username"] == userId
                                else "admin", db)
    return [_v1_device_status(d) for d in devices]

# ── Module 2: Device Status ────────────────────────────────────────────

@app.get("/api/v1/devices/status")
def v1_devices_status(db: Session = Depends(get_db),
                      current: dict = Depends(get_v1_user)):
    """取得登入使用者可存取的所有設備即時狀態"""
    devices = _get_user_devices(current["username"], current["role"], db)
    return {
        "total":   len(devices),
        "online":  sum(1 for d in devices
                       if (time.time() - devices_state.get(d.device_id, {})
                           .get("last_real_time", 0)) <= 300
                          and devices_state.get(d.device_id, {}).get("last_real_time", 0) > 0),
        "devices": [_v1_device_status(d) for d in devices],
        "timestamp": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    }

# ── Module 3: Live — MQTT subscribe info ──────────────────────────────

@app.get("/api/v1/live/{deviceId}/subscribe")
def v1_live_subscribe(deviceId: str, db: Session = Depends(get_db),
                      current: dict = Depends(get_v1_user)):
    """
    取得 MQTT Broker 連線資訊與即時訂閱 Topic。
    合作廠商可直接訂閱這些 Topic 取得即時 GPS / PTT / Alert。
    """
    # 驗證使用者有此設備存取權
    devices = _get_user_devices(current["username"], current["role"], db)
    if not any(d.device_id == deviceId for d in devices):
        raise _v1_err("FORBIDDEN", f"無此設備 {deviceId} 的存取權限", 403)
    cfg = _get_mqtt_cfg()
    return {
        "device_id": deviceId,
        "broker": {
            "host":     cfg.ip,
            "port":     cfg.port,
            "protocol": "mqtt",
            "note":     "無需認證（公開 Broker）"
        },
        "topics": {
            "gps":   f"/WJI/GPS/{deviceId}",
            "ptt":   f"/WJI/PTT/{deviceId}",
            "alert": f"/WJI/PTT/{deviceId}/SOS"
        },
        "payload_format": {
            "gps":   {"device_id": "string", "lat": "float", "lng": "float",
                      "battery": "int", "status": "string"},
            "ptt":   "binary PCM audio (8000 Hz, 16-bit, mono)",
            "alert": "binary — SOS 緊急告警封包"
        }
    }

# ── Module 3: Live — WebRTC video stream ──────────────────────────────

@app.get("/api/v1/live/{deviceId}/stream")
def v1_live_stream(deviceId: str, db: Session = Depends(get_db),
                   current: dict = Depends(get_v1_user)):
    """
    取得即時影像串流資訊。
    回傳 WebRTC signaling 端點，客戶端需執行 WebRTC offer/answer 交換。
    同時提供 MJPEG proxy URL 作為備用（低延遲替代方案）。
    """
    devices = _get_user_devices(current["username"], current["role"], db)
    dev = next((d for d in devices if d.device_id == deviceId), None)
    if not dev:
        raise _v1_err("FORBIDDEN", f"無此設備 {deviceId} 的存取權限", 403)

    # 找出對應的 NVR channel
    cfg = _get_nvr_cfg()
    ch  = None
    if dev.mjpeg_url:
        m = re.search(r"ch=(\d+)", dev.mjpeg_url)
        if m:
            ch = int(m.group(1))

    base = os.getenv("PUBLIC_URL", "").rstrip("/")  # e.g. http://54.x.x.x

    result = {
        "device_id": deviceId,
        "webrtc": {
            "enabled":      WEBRTC_AVAILABLE,
            "signaling_url": f"{base}/api/v1/live/{deviceId}/webrtc/offer",
            "stun_servers": ["stun:stun.l.google.com:19302"],
            "note": ("POST SDP offer → 取得 SDP answer，再完成 ICE 交換"
                     if WEBRTC_AVAILABLE else "伺服器未安裝 aiortc，WebRTC 不可用")
        },
        "mjpeg_proxy": {
            "enabled": AIOHTTP_AVAILABLE and ch is not None,
            "url": (f"{base}/api/nvrv/mjpeg/{ch}" if ch is not None else None),
            "note": "直接放入 <img src='...'> 即可顯示（需帶 Bearer Token 或 nvrv token）"
        },
        "rtsp": {
            "url": (f"rtsp://{cfg.username}:{cfg.password}@{cfg.ip}:{cfg.rtsp_port}/ch{ch+1}"
                    if ch is not None else None),
            "note": "僅限與 NVR 同網段使用"
        }
    }
    return result

@app.post("/api/v1/live/{deviceId}/webrtc/offer")
async def v1_webrtc_offer(deviceId: str, body: DeviceOfferBody,
                           db: Session = Depends(get_db),
                           current: dict = Depends(get_v1_user)):
    """
    WebRTC Offer/Answer 交換。
    客戶端送出 SDP offer，伺服器回傳 SDP answer，完成後影像開始串流。
    """
    devices = _get_user_devices(current["username"], current["role"], db)
    if not any(d.device_id == deviceId for d in devices):
        raise _v1_err("FORBIDDEN", f"無此設備 {deviceId} 的存取權限", 403)
    # 複用現有 WebRTC endpoint 邏輯
    return await webrtc_offer_by_device(deviceId, body, db)

# ── Module 4: History — GPS (GeoJSON) ─────────────────────────────────

@app.get("/api/v1/history/{deviceId}/gps")
def v1_history_gps(deviceId: str,
                   start_time: str, end_time: str,
                   limit: int = 2000,
                   db: Session = Depends(get_db),
                   current: dict = Depends(get_v1_user)):
    """
    查詢歷史 GPS 軌跡，回傳 GeoJSON FeatureCollection。
    start_time / end_time 格式：ISO 8601（YYYY-MM-DDTHH:MM:SS 或 YYYY-MM-DD HH:MM:SS）
    """
    devices = _get_user_devices(current["username"], current["role"], db)
    if not any(d.device_id == deviceId for d in devices):
        raise _v1_err("FORBIDDEN", f"無此設備 {deviceId} 的存取權限", 403)

    # 標準化時間格式（ISO 8601 → YYYY-MM-DD HH:MM:SS）
    start = start_time.replace("T", " ").replace("Z", "")[:19]
    end   = end_time.replace("T", " ").replace("Z", "")[:19]

    records = (db.query(GpsRecord)
               .filter(GpsRecord.device_id == deviceId,
                       GpsRecord.timestamp >= start,
                       GpsRecord.timestamp <= end)
               .order_by(GpsRecord.timestamp.asc())
               .limit(limit).all())

    features = []
    for r in records:
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [float(r.lng), float(r.lat)]  # GeoJSON: [lng, lat]
            },
            "properties": {
                "timestamp": r.timestamp,
                "battery":   r.battery,
                "status":    r.status,
                "device_id": r.device_id
            }
        })

    # LineString 軌跡線（方便地圖顯示）
    coords = [[float(r.lng), float(r.lat)] for r in records]
    line_feature = {
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": coords},
        "properties": {"device_id": deviceId, "point_count": len(records)}
    } if len(coords) >= 2 else None

    return {
        "type": "FeatureCollection",
        "device_id":  deviceId,
        "start_time": start,
        "end_time":   end,
        "point_count": len(records),
        "features":   ([line_feature] if line_feature else []) + features
    }

# ── Module 4: History — Audio ──────────────────────────────────────────

@app.get("/api/v1/history/{deviceId}/audio")
def v1_history_audio(deviceId: str,
                     start_time: str = "", end_time: str = "",
                     db: Session = Depends(get_db),
                     current: dict = Depends(get_v1_user)):
    """查詢歷史語音檔案清單（WAV/MP3），回傳下載網址"""
    devices = _get_user_devices(current["username"], current["role"], db)
    if not any(d.device_id == deviceId for d in devices):
        raise _v1_err("FORBIDDEN", f"無此設備 {deviceId} 的存取權限", 403)

    base = os.getenv("PUBLIC_URL", "").rstrip("/")
    safe_id = os.path.basename(deviceId)
    audio_dir = os.path.join(AUDIO_BASE_PATH, safe_id)

    if not os.path.isdir(audio_dir):
        return {"device_id": deviceId, "total": 0, "files": []}

    files = []
    for fname in sorted(os.listdir(audio_dir)):
        if not fname.lower().endswith((".wav", ".mp3", ".raw")):
            continue
        fpath = os.path.join(audio_dir, fname)
        mtime = os.path.getmtime(fpath)
        ts    = datetime.fromtimestamp(mtime).strftime("%Y-%m-%dT%H:%M:%SZ")
        # 時間過濾（若有提供）
        if start_time and ts < start_time.replace(" ", "T")[:19] + "Z":
            continue
        if end_time and ts > end_time.replace(" ", "T")[:19] + "Z":
            continue
        files.append({
            "filename":   fname,
            "timestamp":  ts,
            "size_bytes": os.path.getsize(fpath),
            "download_url": f"{base}/api/audio/{safe_id}/{fname}",
            "format":     fname.rsplit(".", 1)[-1].upper()
        })

    return {"device_id": deviceId, "total": len(files), "files": files}

# ── Module 4: History — Videos (NVR) ──────────────────────────────────

@app.get("/api/v1/history/{deviceId}/videos")
def v1_history_videos(deviceId: str,
                      start_time: str, end_time: str,
                      db: Session = Depends(get_db),
                      current: dict = Depends(get_v1_user)):
    """
    查詢指定時間段的 NVR 歷史錄影清單，回傳下載網址。
    時間格式：ISO 8601 或 YYYY-MM-DD HH:MM:SS
    """
    devices = _get_user_devices(current["username"], current["role"], db)
    dev = next((d for d in devices if d.device_id == deviceId), None)
    if not dev:
        raise _v1_err("FORBIDDEN", f"無此設備 {deviceId} 的存取權限", 403)

    # 解析設備對應的 NVR channel
    ch = 0
    if dev.mjpeg_url:
        m = re.search(r"ch=(\d+)", dev.mjpeg_url)
        if m:
            ch = int(m.group(1))

    # 標準化時間
    begin = start_time.replace("T", " ").replace("Z", "")[:19]
    end   = end_time.replace("T", " ").replace("Z", "")[:19]

    cfg  = _get_nvr_cfg()
    auth = _nvr_auth_b64(cfg)
    base_url = _nvr_base_url(cfg)
    pub_base = os.getenv("PUBLIC_URL", "").rstrip("/")

    try:
        params = urllib.parse.urlencode({
            "BeginTime": begin, "EndTime": end,
            "Channels": ch, "Auth": auth
        }, quote_via=urllib.parse.quote)
        req = urllib.request.Request(f"{base_url}/GetBackupList.cgi?{params}")
        req.add_header("Authorization", f"Basic {auth}")
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            try:
                nvr_data = json.loads(raw)
            except Exception:
                nvr_data = {}
    except Exception as e:
        raise _v1_err("NVR_ERROR", f"無法查詢 NVR 錄影清單: {e}", 502)

    # 解析各種 NVR 回應格式
    records = (nvr_data if isinstance(nvr_data, list)
               else nvr_data.get("Backup") or nvr_data.get("Record") or [])

    files = []
    for rec in records:
        tag = rec.get("Tag") or rec.get("tag") or rec.get("FileTag") or ""
        avi_url = (f"{pub_base}/api/v1/history/{deviceId}/videos/download?tag={tag}&fmt=avi"
                   if tag else None)
        raw_url = (f"{pub_base}/api/v1/history/{deviceId}/videos/download?tag={tag}&fmt=raw"
                   if tag else None)
        files.append({
            "start_time":    rec.get("StartTime") or rec.get("BeginTime") or begin,
            "end_time":      rec.get("EndTime") or end,
            "channel":       ch,
            "tag":           tag,
            "download_avi":  avi_url,
            "download_raw":  raw_url,
            "playback_url":  f"{pub_base}/api/v1/live/{deviceId}/stream",
            "format":        "AVI / RAW"
        })

    return {
        "device_id":  deviceId,
        "channel":    ch,
        "start_time": begin,
        "end_time":   end,
        "total":      len(files),
        "videos":     files
    }

@app.get("/api/v1/history/{deviceId}/videos/download")
async def v1_video_download(deviceId: str, tag: str, fmt: str = "avi",
                            db: Session = Depends(get_db),
                            current: dict = Depends(get_v1_user)):
    """
    下載 NVR 歷史錄影（透過伺服器代理，合作廠商無需連到內部 NVR IP）。
    fmt=avi → 壓縮版 AVI；fmt=raw → 原始格式
    """
    from fastapi.responses import StreamingResponse as SR
    devices = _get_user_devices(current["username"], current["role"], db)
    if not any(d.device_id == deviceId for d in devices):
        raise _v1_err("FORBIDDEN", f"無此設備 {deviceId} 的存取權限", 403)

    cfg  = _get_nvr_cfg()
    auth = _nvr_auth_b64(cfg)
    base = _nvr_base_url(cfg)
    cgi  = "BackupMedia.cgi" if fmt == "raw" else "GetAVIMedia.cgi"
    nvr_url = f"{base}/{cgi}?{urllib.parse.urlencode({'Tag': tag, 'Auth': auth})}"
    ext  = "raw" if fmt == "raw" else "avi"
    filename = f"{deviceId}_{tag}.{ext}".replace(" ", "_").replace(":", "-")

    if not AIOHTTP_AVAILABLE:
        from fastapi.responses import RedirectResponse
        return RedirectResponse(nvr_url)

    sess = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(connect=15, total=None))
    try:
        resp = await sess.get(nvr_url)
        if resp.status != 200:
            await resp.release(); await sess.close()
            raise _v1_err("NVR_ERROR", f"NVR 回應 {resp.status}", 502)
        ct = resp.headers.get("Content-Type", "video/avi")

        async def gen():
            try:
                async for chunk in resp.content.iter_chunked(65536):
                    yield chunk
            except (asyncio.CancelledError, Exception):
                pass
            finally:
                try: resp.release()
                except Exception: pass
                try: await sess.close()
                except Exception: pass

        return SR(gen(), media_type=ct,
                  headers={"Content-Disposition": f'attachment; filename="{filename}"'})
    except HTTPException:
        await sess.close(); raise
    except Exception as e:
        await sess.close()
        raise _v1_err("NVR_ERROR", f"下載代理失敗: {e}", 502)

# ── Module 3: Live — 即時語音 WebSocket ───────────────────────────────

@app.websocket("/api/v1/live/{deviceId}/audio/ws")
async def v1_audio_ws(deviceId: str, websocket: WebSocket, token: str = ""):
    """
    即時 PTT 語音 WebSocket。
    連線方式：ws://host/api/v1/live/{deviceId}/audio/ws?token=JWT
    收到的訊息格式：
      {"type": "audio", "device_id": "...", "payload_b64": "<base64 PCM>", "timestamp": "..."}
      {"type": "ping"}   ← 每 30 秒心跳，客戶端不需回應
    PCM 格式：8000 Hz, 16-bit, mono（解碼後可播放或轉換為 WAV）
    """
    # ── 認證 ──
    user = None
    if token:
        if JWT_AVAILABLE and token.count(".") == 2:
            try:
                user = _decode_jwt(token)
            except HTTPException:
                pass
        if user is None:
            user = _sessions.get(token)
    if not user:
        await websocket.close(code=4001, reason="Unauthorized: invalid token")
        return

    # ── 設備存取權檢查 ──
    db = SessionLocal()
    try:
        devices = _get_user_devices(user["username"], user["role"], db)
        if not any(d.device_id == deviceId for d in devices):
            await websocket.close(code=4003, reason="Forbidden: no access to device")
            return
    finally:
        db.close()

    await websocket.accept()

    # ── 建立佇列並加入訂閱 ──
    queue: asyncio.Queue = asyncio.Queue(maxsize=100)
    _audio_ws_queues.setdefault(deviceId, set()).add(queue)
    try:
        await websocket.send_json({"type": "connected", "device_id": deviceId,
                                   "message": "即時語音串流已建立"})
        while True:
            try:
                packet = await asyncio.wait_for(queue.get(), timeout=30.0)
                await websocket.send_json(packet)
            except asyncio.TimeoutError:
                await websocket.send_json({"type": "ping"})
            except Exception:
                break
    except Exception:
        pass
    finally:
        _audio_ws_queues.get(deviceId, set()).discard(queue)

# ── Device ↔ NVR Channel 對應設定 ─────────────────────────────────────

@app.put("/api/v1/devices/{deviceId}/nvr_channel")
def v1_set_nvr_channel(deviceId: str, data: dict,
                        db: Session = Depends(get_db),
                        _u: dict = Depends(require_v1_admin)):
    """
    設定 PTT 設備對應的 NVR 攝影機頻道（Admin 權限）。
    這個設定決定了 /stream、/videos 等 API 要讀哪一路 NVR 畫面。

    Body: {"channel": 0, "name": "車牌 AAA-1234"}
    channel：NVR 頻道號碼（從 0 開始）
    """
    channel = data.get("channel")
    if channel is None:
        raise _v1_err("INVALID_PARAMS", "需要提供 channel 欄位（整數，從 0 開始）")
    channel = int(channel)

    cfg = _get_nvr_cfg()
    mjpeg_url = (f"http://{cfg.ip}:{cfg.http_port}/mjpeg_stream.cgi"
                 f"?Auth={_nvr_auth_b64(cfg)}&ch={channel}&metadata=0")

    dev = db.query(Device).filter(Device.device_id == deviceId).first()
    if not dev:
        dev = Device(device_id=deviceId,
                     name=data.get("name", deviceId),
                     mjpeg_url=mjpeg_url)
        db.add(dev)
    else:
        dev.mjpeg_url = mjpeg_url
        if data.get("name"):
            dev.name = data["name"]
    db.commit()

    return {
        "message":   f"設備 {deviceId} 已對應至 NVR CH{channel}",
        "device_id": deviceId,
        "channel":   channel,
        "mjpeg_url": mjpeg_url,
        "rtsp_url":  (f"rtsp://{cfg.username}:{cfg.password}"
                      f"@{cfg.ip}:{cfg.rtsp_port}/ch{channel + 1}")
    }

@app.get("/api/v1/devices/{deviceId}/nvr_channel")
def v1_get_nvr_channel(deviceId: str, db: Session = Depends(get_db),
                        current: dict = Depends(get_v1_user)):
    """查詢設備目前對應的 NVR 頻道"""
    dev = db.query(Device).filter(Device.device_id == deviceId).first()
    if not dev:
        raise _v1_err("NOT_FOUND", f"找不到設備 {deviceId}", 404)
    ch = None
    if dev.mjpeg_url:
        m = re.search(r"ch=(\d+)", dev.mjpeg_url)
        if m:
            ch = int(m.group(1))
    return {"device_id": deviceId, "name": dev.name, "nvr_channel": ch}

# ====== NVR Viewer 獨立查看器 ======
# _nvrv_sessions、_resolve_nvrv、/nvr 頁面與 10 個 /api/nvrv/* 路由搬到 features/nvr_viewer.py 了
# （原樣搬移，@app 改 @router）；放在原本的位置（檔案最後）include，路由順序跟搬移前一樣
from features.nvr_viewer import router as nvr_viewer_router
app.include_router(nvr_viewer_router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", "80")), reload=True)
