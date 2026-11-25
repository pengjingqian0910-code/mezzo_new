# [拆分 nvr_viewer.py] secrets 只有 NVR Viewer 的 /api/nvrv/login 在用，已隨路由搬到 features/nvr_viewer.py，main.py 不再使用
# 原本：import asyncio, random, json, os, time, base64, io, uuid, wave, re, secrets
# [拆分 stt.py] io、wave 只有 STT 的 pcm_to_wav_bytes／transcribe_pcm_bytes 在用，已隨函式搬到 features/stt.py，main.py 不再使用
# 原本：import asyncio, random, json, os, time, base64, io, uuid, wave, re
# [拆分 mqtt_handler.py] uuid 只有 MQTT SOS 廣播的 id 在用，已隨 on_mqtt_message 搬到 features/mqtt_handler.py，main.py 不再使用
# 原本：import asyncio, random, json, os, time, base64, uuid, re
# [拆分 v1.py] json 只有 v1 API 在用，已隨 v1 搬到 api/v1.py，main.py 不再使用
# 原本：import asyncio, random, json, os, time, base64, re
# [拆分 devices.py] re 只有設備 API 的 _device_dict 在用，已隨設備 API 搬到 features/devices.py，main.py 不再使用
# 原本：import asyncio, random, os, time, base64, re
import asyncio, random, os, time, base64
# [拆分 v1.py] urllib.request 只有 v1 API（NVR 影片列表）在用，已隨 v1 搬到 api/v1.py，main.py 不再使用
# import urllib.request
# [拆分 v1.py] urllib.parse 只有 v1 API（NVR 影片列表／下載）在用，已隨 v1 搬到 api/v1.py，main.py 不再使用
# import urllib.parse
# [拆分 nvr_viewer.py] ET 只有 NVR Viewer 的 record_status 在用，已隨路由搬到 features/nvr_viewer.py，main.py 不再使用
# import xml.etree.ElementTree as ET
# [拆分 tak.py] timedelta 只有 TAK 的 _cot_time 在用，已隨 TAK 程式搬到 features/tak.py，main.py 不再使用
# from datetime import timedelta
# [拆分 mqtt_handler.py] paho 的 mqtt 只有 mqtt.Client() 在用，已隨 MQTT 程式搬到 features/mqtt_handler.py，main.py 不再使用
# import paho.mqtt.client as mqtt
from datetime import datetime
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass
# [拆分 mqtt_handler.py] BaseModel 只有 MqttConfigBody 在用，已隨 /api/mqtt/* 搬到 features/mqtt_handler.py，main.py 不再使用
# from pydantic import BaseModel
# [拆分 mqtt_handler.py] WebSocketDisconnect 只有 /ws/map-data、/ws/ptt 在用，已隨端點搬到 features/mqtt_handler.py，main.py 不再使用
# 原本：from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends, HTTPException, Header, File, UploadFile, Form
# [拆分 v1.py] WebSocket 只有 v1 即時語音 WebSocket 在用，已隨 v1 搬到 api/v1.py，main.py 不再使用
# 原本：from fastapi import FastAPI, WebSocket, Depends, HTTPException, Header, File, UploadFile, Form
# [拆分 users.py] Header 只有 /api/logout 在用，已隨使用者 API 搬到 features/users.py，main.py 不再使用
# 原本：from fastapi import FastAPI, Depends, HTTPException, Header, File, UploadFile, Form
from fastapi import FastAPI, Depends, HTTPException, File, UploadFile, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
# [拆分 webrtc.py] HTMLResponse 只有 /view/{device_id} 在用，已隨路由搬到 features/webrtc.py，main.py 不再使用
# 原本：from fastapi.responses import FileResponse, HTMLResponse
from fastapi.responses import FileResponse
# [拆分 users.py] Optional 只有 /api/logout 在用，已隨使用者 API 搬到 features/users.py，main.py 不再使用
# from typing import Optional
# [拆分 database.py] 下面這些 sqlalchemy 名稱只有 Model 定義在用，已隨 Model 搬到 database.py，main.py 不再使用
# from sqlalchemy import create_engine, Column, Integer, String, ForeignKey, Table, Boolean, Text, text
# from sqlalchemy.orm import declarative_base, sessionmaker, relationship, Session
from sqlalchemy import text
from sqlalchemy.orm import Session

# ====== 環境設定 ======
# 環境變數，以及 PyJWT、aiohttp 的選裝檢查搬到 config.py 了
# [拆分 webrtc.py] WebRTC 的選裝檢查已隨 WebRTC 搬到 features/webrtc.py
# 原本：# （STT、WebRTC 的選裝檢查還留在下面，之後跟各自的模組一起拆，原因見 config.py 開頭說明）
# [拆分 stt.py] STT 的選裝檢查已隨 STT 搬到 features/stt.py
# 原本：# （STT 的選裝檢查還留在下面，之後跟 STT 模組一起拆，原因見 config.py 開頭說明）
# [搬移] config.py 搬到 core/config.py。原本：from config import (
from core.config import (
    MQTT_BROKER_HOST, MQTT_BROKER_PORT, MQTT_TOPIC,
    # [拆分 nvr.py] NVR_MEDIA_PATH 只有 NVR 本機磁碟 API 在用，已隨路由搬到 features/nvr.py，main.py 不再使用
    # 原本：NVR_HOST, NVR_AUTH, AUDIO_BASE_PATH, NVR_MEDIA_PATH,
    NVR_HOST, NVR_AUTH, AUDIO_BASE_PATH,
    TAK_SERVER_HOST, TAK_SERVER_PORT,
    # [拆分 auth.py] _pyjwt、JWT_SECRET 只有 JWT 函式在用，已隨函式搬到 core/auth.py，main.py 不再使用
    # 原本：_pyjwt, JWT_AVAILABLE, JWT_SECRET, JWT_EXPIRE_HOURS,
    # [拆分 v1.py] JWT_AVAILABLE、JWT_EXPIRE_HOURS 只有 v1 API 在用，已隨 v1 搬到 api/v1.py，main.py 不再使用
    # 原本：JWT_AVAILABLE, JWT_EXPIRE_HOURS,
    # [拆分 v1.py] aiohttp、AIOHTTP_AVAILABLE 只有 v1 影片下載在用，已隨 v1 搬到 api/v1.py，main.py 不再使用
    # 原本：aiohttp, AIOHTTP_AVAILABLE,
)

# ====== STT (語音轉文字) 相依套件（選裝）======
# faster-whisper 選裝檢查、_whisper_model、STT_AVAILABLE、_load_whisper_model 搬到 features/stt.py 了（原樣搬移）。
# STT_AVAILABLE 啟動後才會變成 True，所以 main.py 不匯入它，改用 stt.is_available() 讀取（見 stt.py 說明）
from features import stt
# [拆分 mqtt_handler.py] transcribe_pcm_bytes 只有 mqtt_stt_worker 在用，已隨它搬到 features/mqtt_handler.py，main.py 不再匯入
# 原本：from features.stt import _load_whisper_model, pcm_to_wav_bytes, transcribe_bilingual, transcribe_pcm_bytes
from features.stt import _load_whisper_model, pcm_to_wav_bytes, transcribe_bilingual

# ====== WebRTC 相依套件（選裝）======
# WebRTC 選裝檢查（av、aiortc、WEBRTC_AVAILABLE）搬到 features/webrtc.py 了（原樣搬移），
# main.py 在下面「獨立影像檢視頁面／WebRTC API」原本的位置匯入

# ====== 資料庫 ======
# engine / SessionLocal / Base / 所有資料表 Model / get_db 搬到 database.py 了
# [搬移] database.py 搬到 core/database.py。原本：from database import (
from core.database import (
    engine, SessionLocal, Base,
    User, Device, NVRConfig, MqttConfig, SocialMediaConfig, TakServerConfig,
    # [拆分 social.py] WhatsAppLog 只有 process_transcript_and_notify 與 /api/social/logs 在用，已隨函式搬到 features/social.py，main.py 不再使用
    # 原本：GpsRecord, WhatsAppLog, SosRecord, PttRecord,
    GpsRecord, SosRecord, PttRecord,
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
# [拆分 mqtt_handler.py] forward_gps_to_tak 只有 on_mqtt_message 在用，已隨它搬到 features/mqtt_handler.py，main.py 不再匯入
# 原本：from features.tak import forward_gps_to_tak, _start_tak_tcp_server, router as tak_router
from features.tak import _start_tak_tcp_server, router as tak_router

# ====== Session Token 管理（Web UI 用）／ JWT 工具（v1 API 用）======
# _sessions、create_session、get_current_user、_v1_err、_create_jwt、_decode_jwt、
# get_v1_user、require_v1_admin、require_admin 搬到 core/auth.py 了（原樣搬移）
from core.auth import (
    # [拆分 users.py] _sessions、create_session 只有登入／登出在用，已隨使用者 API 搬到 features/users.py，main.py 不再匯入
    # 原本：_sessions, create_session, get_current_user,
    get_current_user,
    # [拆分 v1.py] _v1_err、_create_jwt、_decode_jwt、get_v1_user、require_v1_admin 只有 v1 API 在用，已隨 v1 搬到 api/v1.py
    # 原本：_v1_err, _create_jwt, _decode_jwt, get_v1_user, require_v1_admin, require_admin,
    # [拆分 users.py] require_admin 只有重設密碼／指派管理者在用，已隨使用者 API 搬到 features/users.py，main.py 不再匯入
    # 原本：require_admin,
)

# ====== NVR / MQTT 動態設定輔助函式 ======
# [拆分 mqtt_handler.py] _get_mqtt_cfg 也搬到 features/mqtt_handler.py 了
# 原本：# _get_nvr_cfg、_nvr_auth_b64、_nvr_base_url 搬到 features/nvr.py 了（原樣搬移）；_get_mqtt_cfg 屬於 MQTT，留在這裡
# _get_nvr_cfg、_nvr_auth_b64、_nvr_base_url 搬到 features/nvr.py 了（原樣搬移）
from features.nvr import (
    # [拆分 v1.py] _nvr_auth_b64、_nvr_base_url 只有 v1 影片 API 在用，已隨 v1 搬到 api/v1.py，main.py 不再匯入
    # 原本：_get_nvr_cfg, _nvr_auth_b64, _nvr_base_url,
    # [拆分 devices.py] _get_nvr_cfg 只有設備 API 的 _device_dict 在用，已隨設備 API 搬到 features/devices.py，main.py 不再匯入
    # 原本：_get_nvr_cfg,
    config_router as nvr_config_router, router as nvr_router,
)

# [拆分 mqtt_handler.py] _get_mqtt_cfg 與 MQTT 相關程式（共用狀態、mqtt_client、收訊息處理、/ws/map-data、/ws/ptt、
# GPS／SOS 存檔、定期廣播、mqtt_stt_worker、/api/mqtt/*）搬到 features/mqtt_handler.py 了（原樣搬移），
# main.py 匯入還會用到的名稱；兩個 router 各在原本的位置 include
from features import mqtt_handler
from features.mqtt_handler import (
    # [拆分 v1.py] _audio_ws_queues 只有 v1 即時語音 WebSocket 在用，已隨 v1 搬到 api/v1.py，main.py 不再匯入
    # 原本：_get_mqtt_cfg, devices_state, _audio_ws_queues, mqtt_client,
    _get_mqtt_cfg, devices_state, mqtt_client,
    telemetry_broadcaster, mqtt_stt_worker,
    router as mqtt_ws_router, config_router as mqtt_config_router,
)

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
# [拆分 mqtt_handler.py] ptt_manager 只有 on_mqtt_message、/ws/ptt 在用，已隨它們搬到 features/mqtt_handler.py，main.py 不再匯入
# 原本：from core.ws_manager import manager, ptt_manager
from core.ws_manager import manager

# ====== 設備即時狀態 (記憶體) ======
# devices_state、ptt_buffers、_audio_ws_queues 搬到 features/mqtt_handler.py 了（原樣搬移）；
# 下面的位置 API、v1 API 用到的 devices_state、_audio_ws_queues 在上面匯入（同一個物件）

# ====== MQTT ======
# mqtt_client、fastapi_loop、on_mqtt_connect、on_mqtt_message 搬到 features/mqtt_handler.py 了（原樣搬移）。
# fastapi_loop 改由 startup 呼叫 mqtt_handler.set_fastapi_loop() 設定（見下方 startup_event）

# ====== WebSocket Endpoints ======
# /ws/map-data、/ws/ptt 搬到 features/mqtt_handler.py 了（原樣搬移，@app 改 @router）；在原本的位置 include，路由順序跟搬移前一樣
app.include_router(mqtt_ws_router)

# ====== GPS 資料庫儲存 ======
# _gps_last_save、GPS_SAVE_INTERVAL、_save_gps_record、_save_sos_record 搬到 features/mqtt_handler.py 了（原樣搬移）

# Geofence 伺服器端偵測 + 通知邏輯搬到 geofence.py 的 check_geofence_and_notify()

# ====== 定期廣播 ======
# telemetry_broadcaster 搬到 features/mqtt_handler.py 了（原樣搬移），在上面匯入給 startup 用

# ====== STT 函式 ======
# pcm_to_wav_bytes、_google_translate、transcribe_bilingual、transcribe_pcm_bytes 搬到 features/stt.py 了（原樣搬移），
# 在上面「STT 相依套件」的位置匯入

# ====== WhatsApp 發送函式 ======
# get_social_config、send_whatsapp_message、generate_viewer_url 搬到 features/social.py 了（原樣搬移）。
# 下面 geofence.init_router() 還要用這 3 個函式，所以 init_router 留在原位、從 social 匯入；
# process_transcript_and_notify 與 /api/social/* 路由也一起搬過去了
from features.social import (
    get_social_config, send_whatsapp_message, generate_viewer_url, process_transcript_and_notify,
    router as social_router,
)

# 警戒區 router 需要的依賴（get_current_user、manager、send_whatsapp_message...）到這裡都齊了，
# 呼叫 geofence.init_router() 組出 router 跟偵測函式。
geofence_router, check_geofence_and_notify = geofence.init_router(
    Geofence, GeofenceEvent, SessionLocal, get_current_user, manager,
    User, Device, get_social_config, send_whatsapp_message, generate_viewer_url
)
app.include_router(geofence_router)
# [拆分 mqtt_handler.py] MQTT 收到 GPS 時要呼叫 check_geofence_and_notify，但它是上面才產生的
# （mqtt_handler 不能 import main），所以產生後交給 mqtt_handler
mqtt_handler.set_geofence_checker(check_geofence_and_notify)

# process_transcript_and_notify 搬到 features/social.py 了（原樣搬移）；
# 下面的 mqtt_stt_worker 與 PTT 上傳 API 還會用到，在上面「WhatsApp 發送函式」的位置匯入

# mqtt_stt_worker 搬到 features/mqtt_handler.py 了（原樣搬移），在上面「MQTT 動態設定輔助函式」的位置匯入給 startup 用

# ====== 獨立影像檢視頁面 (WhatsApp 連結用) ======
# VIEWER_HTML_TEMPLATE 只有 /view/{device_id} 在用，已隨路由搬到 features/webrtc.py（原樣搬移）

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
    # [拆分 mqtt_handler.py] fastapi_loop 搬到 features/mqtt_handler.py，這裡的 global 改不到它，改呼叫設定函式
    # 原本：global fastapi_loop
    # 原本：fastapi_loop = asyncio.get_running_loop()
    mqtt_handler.set_fastapi_loop(asyncio.get_running_loop())
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
# /api/login、/api/logout、/api/register、/api/users 與使用者 WhatsApp／重設密碼／指派管理者，共 7 個路由
# 搬到 features/users.py 了（原樣搬移，@app 改 @router）；在原本的位置 include，路由順序跟搬移前一樣
from features.users import router as users_router
app.include_router(users_router)

# ====== Device APIs ======
# _device_dict 與設備清單／新增／刪除／綁定／解除綁定／自己綁定，共 8 個路由
# 搬到 features/devices.py 了（原樣搬移，@app 改 @router）；在原本的位置 include，路由順序跟搬移前一樣
from features.devices import router as devices_router
app.include_router(devices_router)

# ====== NVR 動態設定 API ======
# /api/nvr/config（GET / PUT）與 NVRConfigBody 搬到 features/nvr.py 的 config_router 了（原樣搬移，@app 改 @config_router）
# 放在原本的位置 include，路由順序跟搬移前一樣
app.include_router(nvr_config_router)

# ====== MQTT 動態設定 API ======
# 3 個 /api/mqtt/* 路由與 MqttConfigBody 搬到 features/mqtt_handler.py 了（原樣搬移，@app 改 @config_router）；
# 在原本的位置 include，路由順序跟搬移前一樣
app.include_router(mqtt_config_router)

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
    # [拆分 stt.py] STT_AVAILABLE 會在啟動後改變，改用 stt.is_available() 在當下讀取
    # 原本：if STT_AVAILABLE:
    if stt.is_available():
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
# 5 個 /api/social/* 路由搬到 features/social.py 了（原樣搬移，@app 改 @router）；在原本的位置 include，路由順序跟搬移前一樣
app.include_router(social_router)

# ====== 獨立影像檢視頁面 ／ WebRTC API ======
# /view/{device_id} 頁面、webrtc_pcs、MJPEGStreamTrack／RTSPStreamTrack／_make_video_track、WebRTCOfferBody、DeviceOfferBody、
# 4 個 /api/webrtc/* 路由搬到 features/webrtc.py 了（原樣搬移，@app 改 @router）；在原本的位置 include，路由順序跟搬移前一樣。
# [拆分 v1.py] v1 API 搬到 api/v1.py 後，WEBRTC_AVAILABLE、DeviceOfferBody、webrtc_offer_by_device 改由 api/v1.py 自己從 features.webrtc 匯入
# 原本：# 下面 v1 API 的 /api/v1/live/... 還會用到 WEBRTC_AVAILABLE、DeviceOfferBody、webrtc_offer_by_device，從 features.webrtc 匯入
from features.webrtc import (
    # 原本：WEBRTC_AVAILABLE, DeviceOfferBody, webrtc_offer_by_device,
    router as webrtc_router,
)
app.include_router(webrtc_router)

# ======================================================================
# EOC Web Service RESTful API  v1.0
# _v1_device_status、_get_user_devices 與 16 個 /api/v1/* 路由搬到 api/v1.py 了（原樣搬移，@app 改 @router）；
# 在原本的位置 include，路由順序跟搬移前一樣
# ======================================================================
from api.v1 import router as v1_router
app.include_router(v1_router)

# ====== NVR Viewer 獨立查看器 ======
# _nvrv_sessions、_resolve_nvrv、/nvr 頁面與 10 個 /api/nvrv/* 路由搬到 features/nvr_viewer.py 了
# （原樣搬移，@app 改 @router）；放在原本的位置（檔案最後）include，路由順序跟搬移前一樣
from features.nvr_viewer import router as nvr_viewer_router
app.include_router(nvr_viewer_router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", "80")), reload=True)
