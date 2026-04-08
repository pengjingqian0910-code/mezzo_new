import asyncio, random, json, os, time, shutil
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET # <--- 修正了這裡的拼字錯誤
from datetime import datetime
from pydantic import BaseModel
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends, HTTPException, File, UploadFile, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import create_engine, Column, Integer, String, ForeignKey, Table, Boolean
from sqlalchemy.orm import declarative_base, sessionmaker, relationship, Session

os.makedirs("static/audio", exist_ok=True)
SQLALCHEMY_DATABASE_URL = "sqlite:///./mezzo.db"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

user_device_link = Table('user_device_link', Base.metadata, 
    Column('user_id', Integer, ForeignKey('users.id'), primary_key=True), 
    Column('device_id', Integer, ForeignKey('devices.id'), primary_key=True)
)

class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    password = Column(String)
    email = Column(String, nullable=True) 
    role = Column(String, default="operator") 
    manager_id = Column(Integer, ForeignKey('users.id'), nullable=True) 

    managed_users = relationship("User", backref="manager", remote_side=[id])
    devices = relationship("Device", secondary=user_device_link, backref="users")

class Device(Base):
    __tablename__ = 'devices'
    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(String, unique=True, index=True)
    name = Column(String)
    mjpeg_url = Column(String)

class Geofence(Base):
    __tablename__ = 'geofences'
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String)
    points = Column(String) 
    is_enabled = Column(Boolean, default=True)

class PttRecord(Base):
    __tablename__ = 'ptt_records'
    id = Column(Integer, primary_key=True, index=True)
    group_id = Column(Integer)
    sender = Column(String)
    text = Column(String)       
    audio_url = Column(String)  
    timestamp = Column(String)  

Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()

app = FastAPI(title="WiB VMS Web System")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.mount("/static", StaticFiles(directory="static"), name="static")

class ConnectionManager:
    def __init__(self): self.active_connections = []
    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active_connections.append(ws)
    def disconnect(self, ws: WebSocket): self.active_connections.remove(ws)
    async def broadcast(self, msg: dict):
        for conn in self.active_connections:
            try: await conn.send_json(msg)
            except: pass

manager = ConnectionManager()
@app.websocket("/ws/map-data")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True: await websocket.receive_text()
    except WebSocketDisconnect: manager.disconnect(websocket)

async def mock_gps_generator():
    devices_state = { "CAM_001": {"lng": 121.5644, "lat": 25.0339, "battery": 98, "status": "錄影中"}, "CAM_002": {"lng": 121.5170, "lat": 25.0478, "battery": 75, "status": "待機"} }
    while True:
        payload = {}
        for dev_id, state in devices_state.items():
            if state["status"] != "離線":
                state["lng"] += random.uniform(-0.0002, 0.0002)
                state["lat"] += random.uniform(-0.0002, 0.0002)
            payload[dev_id] = state.copy()
        await manager.broadcast({"type": "telemetry_update", "data": payload})
        await asyncio.sleep(1)

def auto_init_db():
    db = SessionLocal()
    if not db.query(User).filter(User.username == "admin").first():
        db.add(User(username="admin", password="admin", email="admin@mezzo.com", role="admin"))
        db.add_all([
            Device(device_id="CAM_001", name="信義特勤 101", mjpeg_url="http://fake/stream1"),
            Device(device_id="CAM_002", name="中正一分局 北車", mjpeg_url="http://fake/stream2")
        ])
        db.commit()
    db.close()

@app.on_event("startup")
async def startup_event():
    auto_init_db()
    asyncio.create_task(mock_gps_generator())

# ====== Auth & User APIs ======
@app.post("/api/login")
def login(data: dict, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == data.get("username"), User.password == data.get("password")).first()
    if not user: raise HTTPException(status_code=401, detail="帳密錯誤")
    return {"token": "fake-jwt", "username": user.username, "role": user.role}

@app.post("/api/register")
def register(data: dict, db: Session = Depends(get_db)):
    if db.query(User).filter(User.username == data.get("username")).first():
        raise HTTPException(status_code=400, detail="帳號已存在")
    new_user = User(username=data.get("username"), password=data.get("password"), email=data.get("email"), role="operator")
    db.add(new_user)
    db.commit()
    return {"msg": "註冊成功"}

@app.get("/api/users")
def get_users(db: Session = Depends(get_db)):
    return [{
        "username": u.username, "email": u.email, "role": u.role, 
        "manager": u.manager.username if u.manager else None
    } for u in db.query(User).all()]

@app.put("/api/users/{username}/reset_password")
def reset_pwd(username: str, data: dict, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == username).first()
    if user: user.password = data.get("new_password")
    db.commit()
    return {"msg": "密碼已重設"}

@app.put("/api/users/{username}/assign_manager")
def assign_mgr(username: str, data: dict, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == username).first()
    manager = db.query(User).filter(User.username == data.get("manager_username")).first()
    user.manager_id = manager.id if manager else None
    user.role = data.get("role", user.role) 
    db.commit()
    return {"msg": "權限與群組已更新"}

# ====== 整合回放 (Playback) API ======
@app.get("/api/playback_data/{device_id}")
def get_playback_data(device_id: str):
    """
    模擬回傳設備的歷史回放資料。
    實務上應從資料庫撈取特定時段的 mp4 網址與 GPS 座標表。
    """
    # 模擬產生一條長度約 5 分鐘 (300秒) 的 GPS 軌跡
    base_lng, base_lat = 121.5644, 25.0339
    gps_track = []
    
    # 製造一點曲線移動的感覺
    import math
    for i in range(300):
        lng_offset = math.sin(i / 20.0) * 0.002
        lat_offset = math.cos(i / 20.0) * 0.002
        gps_track.append({
            "timeOffset": i, # 影片播放的第幾秒
            "lng": base_lng + lng_offset,
            "lat": base_lat + lat_offset
        })
        
    return {
        "device_id": device_id,
        # 使用開源的測試影片作為展示 (自帶影像與聲音)
        "video_url": "https://www.w3schools.com/html/mov_bbb.mp4", 
        "audio_url": "", # 如果影像已含聲音則留空；若有獨立音檔則提供網址
        "duration": 300, # 總時長(秒)
        "gps_track": gps_track
    }


# ====== Device & NVR Proxy APIs ======
@app.get("/api/nvr/cameras")
def get_nvr_cameras():
    try:
        url = "http://118.163.141.80/CameraList.cgi?Auth=YWRtaW46MTIzNA=="
        req = urllib.request.Request(url)
        req.add_header("Authorization", "Basic YWRtaW46MTIzNA==")
        with urllib.request.urlopen(req, timeout=5) as response:
            data = response.read().decode('utf-8')
            return json.loads(data)
    except Exception as e:
        print(f"NVR Proxy Error: {e}")
        raise HTTPException(status_code=500, detail="無法連線至 NVR API")

# ====== 修正：錄影狀態 Proxy API ======
@app.get("/api/nvr/record_status")
def get_nvr_record_status(channel: int, time_str: str):
    try:
        # 將前端傳來的時間進行 URL Encode
        encoded_time = urllib.parse.quote(time_str)
        # 組裝 API 網址 [cite: 146-155]
        url = f"http://118.163.141.80/GetRecordStatus.cgi?time={encoded_time}&type=month&channels={channel}&Auth=YWRtaW46MTIzNA=="
        
        req = urllib.request.Request(url)
        req.add_header("Authorization", "Basic YWRtaW46MTIzNA==")
        
        with urllib.request.urlopen(req, timeout=5) as response:
            xml_data = response.read().decode('utf-8')
            
            # 透過 ElementTree 解析回傳的 XML [cite: 157-164]
            root = ET.fromstring(xml_data)
            data_node = root.find(".//Data")
            
            if data_node is not None and data_node.text:
                status_list = list(data_node.text.strip())
                # 防呆：確保陣列至少有 31 天，不足補 0
                while len(status_list) < 31:
                    status_list.append('0')
                return {"status_array": status_list[:31]}
            else:
                return {"status_array": ["0"] * 31}
                
    except Exception as e:
        print(f"NVR Record Status Proxy Error: {e}")
        # 連線或解析失敗時，回傳全 0 的陣列防呆
        return {"status_array": ["0"] * 31}

@app.get("/api/devices")
def get_devices(username: str = None, db: Session = Depends(get_db)):
    if not username: return []
    user = db.query(User).filter(User.username == username).first()
    if not user: return []

    if user.role == "admin":
        devices = db.query(Device).all()
    elif user.role == "group_manager":
        dev_set = set(user.devices)
        for managed_user in user.managed_users:
            for d in managed_user.devices: dev_set.add(d)
        devices = list(dev_set)
    else:
        devices = user.devices

    return [{"device_id": d.device_id, "name": d.name, "mjpeg_url": d.mjpeg_url} for d in devices]

@app.get("/api/admin/all_devices")
def get_all_devices_admin(db: Session = Depends(get_db)):
    return [{"device_id": d.device_id, "name": d.name, "mjpeg_url": d.mjpeg_url} for d in db.query(Device).all()]

@app.post("/api/devices")
def add_device(dev: dict, db: Session = Depends(get_db)):
    if db.query(Device).filter(Device.device_id == dev.get("device_id")).first(): 
        raise HTTPException(status_code=400, detail="DeviceID 已存在系統")
    db.add(Device(device_id=dev.get("device_id"), name=dev.get("name"), mjpeg_url=dev.get("mjpeg_url", "")))
    db.commit()
    return {"msg": "設備註冊成功"}

@app.delete("/api/devices/{device_id}")
def del_device(device_id: str, db: Session = Depends(get_db)):
    db.query(Device).filter(Device.device_id == device_id).delete()
    db.commit()
    return {"msg": "刪除成功"}

@app.post("/api/users/{username}/bind")
def bind_device(username: str, data: dict, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == username).first()
    device = db.query(Device).filter(Device.device_id == data.get("device_id")).first()
    if not device: raise HTTPException(status_code=404, detail="找不到此設備 ID，請確認是否輸入正確")
    
    if device not in user.devices:
        user.devices.append(device)
        db.commit()
    return {"msg": "設備綁定成功"}

@app.delete("/api/users/{username}/unbind/{device_id}")
def unbind_device(username: str, device_id: str, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == username).first()
    device = db.query(Device).filter(Device.device_id == device_id).first()
    if device in user.devices:
        user.devices.remove(device)
        db.commit()
    return {"msg": "解除綁定成功"}

# ====== Geofence & PTT APIs ======
@app.get("/api/geofences")
def get_geofences(db: Session = Depends(get_db)): return [{"id": g.id, "name": g.name, "points": g.points, "is_enabled": g.is_enabled} for g in db.query(Geofence).all()]
@app.post("/api/geofences")
def add_geofence(geo: dict, db: Session = Depends(get_db)): db.add(Geofence(name=geo.get("name"), points=geo.get("points"))); db.commit(); return {}
@app.delete("/api/geofences/{geo_id}")
def del_geofence(geo_id: int, db: Session = Depends(get_db)): db.query(Geofence).filter(Geofence.id == geo_id).delete(); db.commit(); return {}

@app.post("/api/ptt/records")
async def upload_ptt_record(group_id: int = Form(...), sender: str = Form(...), text: str = Form(""), audio: UploadFile = File(...), db: Session = Depends(get_db)):
    file_name = f"ptt_{int(time.time())}_{audio.filename}"
    file_path = f"static/audio/{file_name}"
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(audio.file, buffer)
    db.add(PttRecord(group_id=group_id, sender=sender, text=text, audio_url=f"http://localhost:5555/{file_path}", timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    db.commit()
    return {"msg": "錄音儲存成功"}

@app.get("/api/ptt/records")
def get_ptt_records(group_id: int = None, db: Session = Depends(get_db)):
    query = db.query(PttRecord)
    if group_id: query = query.filter(PttRecord.group_id == group_id)
    records = query.order_by(PttRecord.id.desc()).all()
    return [{"id": r.id, "group_id": r.group_id, "sender": r.sender, "text": r.text, "audio_url": r.audio_url, "timestamp": r.timestamp} for r in records]

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=5555, reload=True)