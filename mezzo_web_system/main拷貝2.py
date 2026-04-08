import asyncio, random, json, os, time, shutil, base64
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
import paho.mqtt.client as mqtt # 新增 MQTT 客戶端
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

user_device_link = Table('user_device_link', Base.metadata, Column('user_id', Integer, ForeignKey('users.id'), primary_key=True), Column('device_id', Integer, ForeignKey('devices.id'), primary_key=True))

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

# ====== WebSocket 管理器 ======
class ConnectionManager:
    def __init__(self): self.active_connections = []
    async def connect(self, ws: WebSocket): await ws.accept(); self.active_connections.append(ws)
    def disconnect(self, ws: WebSocket): self.active_connections.remove(ws)
    async def broadcast(self, msg: dict):
        for conn in self.active_connections:
            try: await conn.send_json(msg)
            except: pass

manager = ConnectionManager()
ptt_manager = ConnectionManager() # 專門給 PTT 的 WebSocket

@app.websocket("/ws/map-data")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True: await websocket.receive_text()
    except WebSocketDisconnect: manager.disconnect(websocket)

# ====== 新增：MQTT TCP 連線與 WebSocket 代理 ======
mqtt_client = mqtt.Client()
fastapi_loop = None

def on_mqtt_connect(client, userdata, flags, rc):
    print("🟢 [MQTT TCP] 成功連線至 Broker (118.163.141.80:1688)！")
    # 訂閱所有 CHANNEL0001 底下的主題
    client.subscribe("/WJI/PTT/CHANNEL0001/#")

def on_mqtt_message(client, userdata, msg):
    # 將原始的 Binary Payload 轉成 Base64，再透過 WS 丟給前端
    if fastapi_loop and ptt_manager.active_connections:
        payload_b64 = base64.b64encode(msg.payload).decode('utf-8')
        asyncio.run_coroutine_threadsafe(
            ptt_manager.broadcast({"topic": msg.topic, "payload": payload_b64}),
            fastapi_loop
        )

mqtt_client.on_connect = on_mqtt_connect
mqtt_client.on_message = on_mqtt_message

@app.websocket("/ws/ptt")
async def ptt_websocket_endpoint(websocket: WebSocket):
    await ptt_manager.connect(websocket)
    try:
        while True:
            # 接收前端發來的 Publish 請求，代為發送至 TCP Broker
            data = await websocket.receive_text()
            msg = json.loads(data)
            if msg.get("action") == "publish":
                mqtt_client.publish(msg.get("topic"), msg.get("payload"))
    except WebSocketDisconnect:
        ptt_manager.disconnect(websocket)

async def mock_gps_generator():
    devices_state = { "CAM_001": {"lng": 121.5644, "lat": 25.0339, "battery": 98, "status": "錄影中"} }
    while True:
        payload = {dev_id: state.copy() for dev_id, state in devices_state.items()}
        await manager.broadcast({"type": "telemetry_update", "data": payload})
        await asyncio.sleep(1)

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
    asyncio.create_task(mock_gps_generator())
    
    # 啟動 MQTT TCP 連線
    try:
        mqtt_client.connect("118.163.141.80", 1688, 60)
        mqtt_client.loop_start() # 在背景執行緒運行
    except Exception as e:
        print(f"❌ [MQTT TCP] 連線失敗: {e}")

# ... (保留其餘的所有 API 如 /api/login, /api/devices, /api/playback_data, /api/ptt/records 等) ...
@app.post("/api/login")
def login(data: dict, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == data.get("username"), User.password == data.get("password")).first()
    if not user: raise HTTPException(status_code=401, detail="帳密錯誤")
    return {"token": "fake-jwt", "username": user.username, "role": user.role}

@app.get("/api/devices")
def get_devices(username: str = None, db: Session = Depends(get_db)): return [{"device_id": d.device_id, "name": d.name, "mjpeg_url": d.mjpeg_url} for d in db.query(Device).all()]

@app.get("/api/admin/all_devices")
def get_all_devices_admin(db: Session = Depends(get_db)): return [{"device_id": d.device_id, "name": d.name, "mjpeg_url": d.mjpeg_url} for d in db.query(Device).all()]

@app.post("/api/ptt/records")
async def upload_ptt_record(group_id: int = Form(...), sender: str = Form(...), text: str = Form(""), audio: UploadFile = File(...), db: Session = Depends(get_db)):
    file_name = f"ptt_{int(time.time())}_{audio.filename}"
    file_path = f"static/audio/{file_name}"
    with open(file_path, "wb") as buffer: shutil.copyfileobj(audio.file, buffer)
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