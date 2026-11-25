"""
WiB VMS Web System — 應用程式入口
=================================
這支檔案只負責「組裝」：建立 FastAPI app、首頁與 /static、資料庫建表與預設資料（auto_init_db）、
啟動事件（startup_event），以及依序 include 各模組的 router。功能程式都在下面這些資料夾：

  core/      共用基礎：config（環境變數、PyJWT／aiohttp 選裝檢查）、database（資料表、Session）、
             auth（Session Token／JWT）、ws_manager（WebSocket 連線管理）
  features/  各功能（含給自己前端用的 API）：geofence、tak、nvr、nvr_viewer、webrtc、stt、social、
             mqtt_handler、users、devices、tracking、ptt
  api/       對外 API（外部合作廠商）：v1

注意事項：
- 下面 app.include_router(...) 的順序就是路由註冊的順序，跟拆分前 main.py 裡路由的先後一致，不要隨意調換
  （路徑有重疊時，先註冊的會先比對到）。
- python main.py（reload 模式）會讓 main.py 執行兩次（__main__／__mp_main__ 與 uvicorn 匯入的 main），
  但 core/、features/、api/ 的模組只載入一次。所以「對共用物件做註冊／修改」的程式要放在被 import 的模組裡
  （例如 geofence 資料表在 core/database.py 註冊），不要放在這裡。
- 各模組不 import main；main 需要交給模組的東西用設定函式傳過去（mqtt_handler.set_fastapi_loop／set_geofence_checker）。
- 拆分的過程與每一步的驗證記錄在 git 歷史（refactor/restructure-main 分支）與 commit 訊息。
"""
import asyncio, os, base64
import random   # 沒用到（拆分前就沒有被使用），保留
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlalchemy import text

# ---- core ----
from core.config import (
    MQTT_BROKER_HOST, MQTT_BROKER_PORT,
    MQTT_TOPIC,   # 沒用到（拆分前就沒有被使用），保留
    NVR_HOST, NVR_AUTH,
    TAK_SERVER_HOST, TAK_SERVER_PORT,
)
from core.database import (
    engine, SessionLocal, Base,
    User, Device, NVRConfig, MqttConfig, SocialMediaConfig, TakServerConfig,
    Geofence, GeofenceEvent,   # 由 core/database.py 呼叫 geofence.init_models() 註冊
)
from core.auth import get_current_user
from core.ws_manager import manager

# ---- features ----
from features import geofence
from features import mqtt_handler
from features.mqtt_handler import (
    _get_mqtt_cfg, mqtt_client,
    telemetry_broadcaster, mqtt_stt_worker,
    router as mqtt_ws_router, config_router as mqtt_config_router,
)
from features.social import (
    get_social_config, send_whatsapp_message, generate_viewer_url,
    router as social_router,
)
from features.stt import _load_whisper_model
from features.tak import _start_tak_tcp_server, router as tak_router
from features.nvr import config_router as nvr_config_router, router as nvr_router
from features.users import router as users_router
from features.devices import router as devices_router
from features.tracking import router as tracking_router
from features.ptt import router as ptt_router
from features.webrtc import router as webrtc_router
from features.nvr_viewer import router as nvr_viewer_router

# ---- api（對外）----
from api.v1 import router as v1_router

# 所有資料表（含 geofence 的兩張）都在 core/database.py 註冊完了，才建表
Base.metadata.create_all(bind=engine)

# ====== FastAPI ======
app = FastAPI(title="WiB VMS Web System")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

@app.get("/")
@app.get("/index_3D.html")
async def get_index():
    return FileResponse("index_3D.html", media_type="text/html")

app.mount("/static", StaticFiles(directory="static"), name="static")

# /ws/map-data、/ws/ptt
app.include_router(mqtt_ws_router)

# 警戒區：router 與伺服器端進出偵測由 geofence.init_router() 依賴注入組出來。
# MQTT 收到 GPS 時要呼叫 check_geofence_and_notify，它在這裡才產生（mqtt_handler 不能 import main），
# 所以產生後交給 mqtt_handler。
geofence_router, check_geofence_and_notify = geofence.init_router(
    Geofence, GeofenceEvent, SessionLocal, get_current_user, manager,
    User, Device, get_social_config, send_whatsapp_message, generate_viewer_url
)
app.include_router(geofence_router)
mqtt_handler.set_geofence_checker(check_geofence_and_notify)

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
    # MQTT 處理函式在 paho 的執行緒裡，要把工作丟回這個事件迴圈（fastapi_loop 在 mqtt_handler 裡，用設定函式設定）
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

# ====== 各模組的 API（順序 = 路由註冊順序，見開頭說明）======
app.include_router(users_router)          # /api/login、/api/logout、/api/register、/api/users…
app.include_router(devices_router)        # /api/devices…、/api/users/{username}/bind…、/api/me/bind_device
app.include_router(nvr_config_router)     # /api/nvr/config
app.include_router(mqtt_config_router)    # /api/mqtt/*
app.include_router(tak_router)            # /api/tak/*
app.include_router(nvr_router)            # /api/nvr/*（即時、歷史、本機磁碟）
app.include_router(tracking_router)       # /api/devices/positions、/api/gps/*、/api/sos/records
app.include_router(ptt_router)            # /api/audio/*、/api/ptt/records
app.include_router(social_router)         # /api/social/*
app.include_router(webrtc_router)         # /view/{device_id}、/api/webrtc/*
app.include_router(v1_router)             # /api/v1/*（對外）
app.include_router(nvr_viewer_router)     # /nvr、/api/nvrv/*


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", "80")), reload=True)
