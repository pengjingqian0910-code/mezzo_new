import asyncio, json, os, base64, secrets
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
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from typing import Optional
from sqlalchemy import create_engine, Column, Integer, String, ForeignKey, Table, Boolean
from sqlalchemy.orm import declarative_base, sessionmaker, relationship, Session

# ====== 環境設定 ======
MQTT_BROKER_HOST = os.getenv("MQTT_BROKER_HOST", "118.163.141.80")
MQTT_BROKER_PORT = int(os.getenv("MQTT_BROKER_PORT", "1688"))
MQTT_TOPIC       = os.getenv("MQTT_TOPIC", "/WJI/PTT/#")
NVR_HOST         = os.getenv("NVR_HOST", "118.163.141.80")
NVR_AUTH         = os.getenv("NVR_AUTH", "YWRtaW46MTIzNA==")
AUDIO_BASE_PATH  = os.getenv("AUDIO_BASE_PATH", "static/audio")

os.makedirs(AUDIO_BASE_PATH, exist_ok=True)

# ====== 資料庫 (SQLite - 僅存應用設定：帳號、設備清單、Geofence) ======
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
    id          = Column(Integer, primary_key=True, index=True)
    username    = Column(String, unique=True, index=True)
    password    = Column(String)
    email       = Column(String, nullable=True)
    role        = Column(String, default="operator")  # admin / group_manager / operator
    manager_id  = Column(Integer, ForeignKey('users.id'), nullable=True)
    managed_users = relationship("User", backref="manager", remote_side=[id])
    devices     = relationship("Device", secondary=user_device_link, backref="users")

class Device(Base):
    __tablename__ = 'devices'
    id          = Column(Integer, primary_key=True, index=True)
    device_id   = Column(String, unique=True, index=True)
    name        = Column(String)
    mjpeg_url   = Column(String)

class Geofence(Base):
    __tablename__ = 'geofences'
    id          = Column(Integer, primary_key=True, index=True)
    name        = Column(String)
    points      = Column(String)  # JSON string [{lng, lat}, ...]
    is_enabled  = Column(Boolean, default=True)

Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()

# ====== Session Token 管理（記憶體，重啟失效需重新登入）======
# { token: { username, role } }  — 參考 Mezzo-main auth.cjs 的設計思路，簡化為 server-side session
_sessions: dict = {}

def create_session(username: str, role: str) -> str:
    token = secrets.token_hex(32)
    _sessions[token] = {"username": username, "role": role}
    return token

def get_current_user(authorization: Optional[str] = Header(default=None)):
    """從 Authorization: Bearer <token> 取得當前使用者，無 token 則回 401。"""
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

# ====== FastAPI ======
app = FastAPI(title="WiB VMS Web System")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
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

manager     = ConnectionManager()  # 地圖即時資料
ptt_manager = ConnectionManager()  # PTT 語音通道

# ====== 設備即時狀態 (記憶體，不落地) ======
# { device_id: { lat, lng, status, last_update } }
device_positions: dict = {}

# ====== MQTT ======
mqtt_client  = mqtt.Client()
fastapi_loop = None

def handle_gps_message(channel: str, uuid: str, data: str):
    """
    解析 GPS payload 並廣播給地圖 WebSocket。
    支援兩種格式：
      格式 1：UUID,Lat,Lon
      格式 2：Lat,Lon
    """
    parts = data.strip().split(',')
    try:
        if len(parts) >= 3:
            lat = float(parts[1])
            lng = float(parts[2])
        elif len(parts) >= 2:
            lat = float(parts[0])
            lng = float(parts[1])
        else:
            return

        device_positions[uuid] = {
            "lat": lat,
            "lng": lng,
            "status": "active",
            "last_update": datetime.now().isoformat()
        }

        if fastapi_loop:
            asyncio.run_coroutine_threadsafe(
                manager.broadcast({
                    "type": "telemetry_update",
                    "data": { uuid: device_positions[uuid] }
                }),
                fastapi_loop
            )
    except (ValueError, IndexError) as e:
        print(f"[MQTT] GPS parse error ({uuid}): {e}")

def on_mqtt_connect(client, userdata, flags, rc):
    print(f"[MQTT] 連線至 {MQTT_BROKER_HOST}:{MQTT_BROKER_PORT}，rc={rc}")
    client.subscribe(MQTT_TOPIC)
    print(f"[MQTT] 訂閱 {MQTT_TOPIC}")

def on_mqtt_message(client, userdata, msg):
    # Topic 結構：/WJI/PTT/{Channel}/{Tag}
    # 例：/WJI/PTT/CHANNEL0001/GPS
    parts = msg.topic.split('/')
    # parts: ['', 'WJI', 'PTT', channel, tag]
    if len(parts) >= 5:
        channel = parts[3]
        tag     = parts[4]
        if tag == 'GPS':
            try:
                data = msg.payload.decode('utf-8', errors='ignore')
                # UUID 來自 topic 之前的資料或 payload 格式1
                csv_parts = data.strip().split(',')
                uuid = csv_parts[0] if len(csv_parts) >= 3 else channel
                handle_gps_message(channel, uuid, data)
            except Exception as e:
                print(f"[MQTT] GPS handler error: {e}")

    # 所有 PTT 訊息轉發給前端 PTT WebSocket（保持原有音訊串流功能）
    if fastapi_loop and ptt_manager.active_connections:
        payload_b64 = base64.b64encode(msg.payload).decode('utf-8')
        asyncio.run_coroutine_threadsafe(
            ptt_manager.broadcast({"topic": msg.topic, "payload": payload_b64}),
            fastapi_loop
        )

mqtt_client.on_connect = on_mqtt_connect
mqtt_client.on_message = on_mqtt_message

# ====== WebSocket Endpoints ======
@app.websocket("/ws/map-data")
async def websocket_map(websocket: WebSocket):
    await manager.connect(websocket)
    # 連線時立即推送目前已知的所有設備位置
    if device_positions:
        await websocket.send_json({"type": "telemetry_update", "data": device_positions})
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
            msg = json.loads(data)
            if msg.get("action") == "publish":
                payload_str = msg.get("payload", "")
                mqtt_client.publish(msg.get("topic"), payload_str.encode('utf-8'))
    except WebSocketDisconnect:
        ptt_manager.disconnect(websocket)

# ====== 啟動事件 ======
def auto_init_db():
    db = SessionLocal()
    if not db.query(User).filter(User.username == "admin").first():
        db.add(User(username="admin", password="admin", email="admin@mezzo.com", role="admin"))
        db.commit()
    db.close()

@app.on_event("startup")
async def startup_event():
    global fastapi_loop
    fastapi_loop = asyncio.get_running_loop()
    auto_init_db()
    try:
        mqtt_client.connect(MQTT_BROKER_HOST, MQTT_BROKER_PORT, 60)
        mqtt_client.loop_start()
        print(f"[MQTT] 啟動中，連線至 {MQTT_BROKER_HOST}:{MQTT_BROKER_PORT}")
    except Exception as e:
        print(f"[MQTT] 連線失敗: {e}")

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
def get_users(db: Session = Depends(get_db), _user: dict = Depends(require_admin)):
    return [{"username": u.username, "email": u.email, "role": u.role,
             "manager": u.manager.username if u.manager else None}
            for u in db.query(User).all()]

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
    return [{"device_id": d.device_id, "name": d.name, "mjpeg_url": d.mjpeg_url} for d in devices]

@app.get("/api/admin/all_devices")
def get_all_devices(db: Session = Depends(get_db)):
    return [{"device_id": d.device_id, "name": d.name, "mjpeg_url": d.mjpeg_url}
            for d in db.query(Device).all()]

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
    # admin/group_manager 可幫任何人綁定；operator 只能綁定自己
    if current_user["role"] == "operator" and current_user["username"] != username:
        raise HTTPException(status_code=403, detail="只能綁定自己的帳號")
    user   = db.query(User).filter(User.username == username).first()
    device = db.query(Device).filter(Device.device_id == data.get("device_id")).first()
    if not device: raise HTTPException(status_code=404, detail="找不到此設備 ID，請確認 Device ID 正確")
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
    """
    Operator 登入後自助輸入 Device ID 綁定。
    若設備不在系統中，自動建立（device_id 即名稱，mjpeg_url 留空待 admin 補填）。
    """
    device_id = data.get("device_id", "").strip()
    if not device_id:
        raise HTTPException(status_code=400, detail="device_id 不可為空")
    user = db.query(User).filter(User.username == current_user["username"]).first()
    # operator 只對應單一設備：若已有綁定先解除
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

# ====== NVR 即時 APIs ======
@app.get("/api/nvr/cameras")
def get_nvr_cameras():
    import re
    try:
        url = f"http://{NVR_HOST}/CameraList.cgi?Auth={NVR_AUTH}"
        req = urllib.request.Request(url)
        req.add_header("Authorization", f"Basic {NVR_AUTH}")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = resp.read().decode('utf-8')
            try:
                return json.loads(data)
            except json.JSONDecodeError:
                fixed = re.sub(r'([{,]\s*)([a-zA-Z0-9_]+)\s*:', r'\1"\2":', data)
                return json.loads(fixed)
    except Exception as e:
        print(f"[NVR] CameraList error: {e}")
        raise HTTPException(status_code=500, detail="無法連線至 NVR")

@app.get("/api/nvr/record_status")
def get_nvr_record_status(channel: int, time_str: str):
    try:
        encoded_time = urllib.parse.quote(time_str)
        url = f"http://{NVR_HOST}/GetRecordStatus.cgi?time={encoded_time}&type=month&channels={channel}&Auth={NVR_AUTH}"
        req = urllib.request.Request(url)
        req.add_header("Authorization", f"Basic {NVR_AUTH}")
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
    """
    查詢 NVR 錄影清單。
    begin_time / end_time 格式：YYYY-MM-DD HH:mm:00
    channels：頻道號碼，多頻道用逗號分隔，例如 "0, 1, 2"
    """
    try:
        params = urllib.parse.urlencode({
            "BeginTime": begin_time,
            "EndTime": end_time,
            "Channels": channels,
            "Auth": NVR_AUTH
        })
        url = f"http://{NVR_HOST}/GetBackupList.cgi?{params}"
        req = urllib.request.Request(url)
        req.add_header("Authorization", f"Basic {NVR_AUTH}")
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = resp.read().decode('utf-8')
            try:
                return json.loads(data)
            except json.JSONDecodeError:
                return {"raw": data}
    except Exception as e:
        print(f"[NVR] GetBackupList error: {e}")
        raise HTTPException(status_code=500, detail="無法取得 NVR 歷史清單")

@app.get("/api/nvr/download/avi")
def download_nvr_avi(tag: str):
    """
    下載 NVR AVI 錄影片段（redirect 至 NVR，避免 web server 佔用頻寬）
    tag：從 GetBackupList 回傳的 Tag 欄位
    """
    from fastapi.responses import RedirectResponse
    params = urllib.parse.urlencode({"Tag": tag, "Auth": NVR_AUTH})
    return RedirectResponse(url=f"http://{NVR_HOST}/GetAVIMedia.cgi?{params}")

@app.get("/api/nvr/download/raw")
def download_nvr_raw(tag: str):
    """
    下載 NVR RAW 錄影片段
    tag：從 GetBackupList 回傳的 Tag 欄位
    """
    from fastapi.responses import RedirectResponse
    params = urllib.parse.urlencode({"Tag": tag, "Auth": NVR_AUTH})
    return RedirectResponse(url=f"http://{NVR_HOST}/BackupMedia.cgi?{params}")

# ====== 音檔服務 API (歷史 PTT 音檔，由 NVR 同機儲存端寫入) ======
@app.get("/api/audio/{device_id}/{filename}")
def serve_audio(device_id: str, filename: str):
    """
    回傳指定設備的歷史音檔。
    檔案由 NVR 同機儲存端寫入 AUDIO_BASE_PATH/{device_id}/ 目錄。
    """
    # 安全檢查：防止路徑穿越
    safe_device_id = os.path.basename(device_id)
    safe_filename  = os.path.basename(filename)
    audio_path = os.path.join(AUDIO_BASE_PATH, safe_device_id, safe_filename)
    if not os.path.exists(audio_path):
        raise HTTPException(status_code=404, detail="音檔不存在")
    return FileResponse(audio_path)

@app.get("/api/audio/{device_id}")
def list_audio(device_id: str):
    """
    列出指定設備的所有歷史音檔。
    """
    safe_device_id = os.path.basename(device_id)
    device_audio_dir = os.path.join(AUDIO_BASE_PATH, safe_device_id)
    if not os.path.isdir(device_audio_dir):
        return []
    files = sorted(os.listdir(device_audio_dir))
    return [{"filename": f, "url": f"/api/audio/{safe_device_id}/{f}"} for f in files]

# ====== Geofence APIs ======
@app.get("/api/geofences")
def get_geofences(db: Session = Depends(get_db)):
    return [{"id": g.id, "name": g.name, "points": g.points, "is_enabled": g.is_enabled}
            for g in db.query(Geofence).all()]

@app.post("/api/geofences")
def add_geofence(geo: dict, db: Session = Depends(get_db)):
    db.add(Geofence(name=geo.get("name"), points=geo.get("points")))
    db.commit()
    return {}

@app.put("/api/geofences/{geo_id}")
def update_geofence(geo_id: int, geo: dict, db: Session = Depends(get_db)):
    g = db.query(Geofence).filter(Geofence.id == geo_id).first()
    if not g: raise HTTPException(status_code=404, detail="找不到警戒區")
    if "is_enabled" in geo: g.is_enabled = geo["is_enabled"]
    if "name" in geo: g.name = geo["name"]
    if "points" in geo: g.points = geo["points"]
    db.commit()
    return {}

@app.delete("/api/geofences/{geo_id}")
def del_geofence(geo_id: int, db: Session = Depends(get_db)):
    db.query(Geofence).filter(Geofence.id == geo_id).delete()
    db.commit()
    return {}

# ====== 即時設備狀態 API ======
@app.get("/api/devices/positions")
def get_device_positions():
    """回傳目前所有設備的最新位置（MQTT 接收後存記憶體）"""
    return device_positions

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=5555, reload=True)
