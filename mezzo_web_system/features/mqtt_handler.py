"""
MQTT（設備即時資料）
--------------------
- _get_mqtt_cfg、設備即時狀態（devices_state、ptt_buffers、_audio_ws_queues）
- mqtt_client、fastapi_loop、on_mqtt_connect、on_mqtt_message（GPS／SOS／PTT 音訊；轉送 TAK、警戒區偵測、/ws/ptt、v1 語音、STT 緩衝）
- /ws/map-data、/ws/ptt 兩個 WebSocket（router）
- GPS／SOS 寫入資料庫、telemetry_broadcaster（每秒廣播位置）、mqtt_stt_worker（PTT 音訊送 STT）
- 3 個 /api/mqtt/* 路由（config_router）

從 main.py 原樣搬出 8 段：108–118、137–144、146–265、267–288、290–320、324–337、363–378、607–634 行；
路由的 @app.xxx 改成 @router.xxx／@config_router.xxx（原本寫法以註解保留）。路由在 main.py 分兩段，
所以用兩個 router，main.py 各在原本的位置 include，路由順序不變。startup_event 留在 main.py。

新增（最下面）：
- set_fastapi_loop()：fastapi_loop 原本由 main 的 startup 用 global 設定；搬過來後 main 的 global 改不到這裡，
  改由 startup 呼叫這個函式設定。沒設定時 on_mqtt_message 會因為 `if fastapi_loop:` 而什麼都不做（不會報錯）。
- check_geofence_and_notify／set_geofence_checker()：它是 main 用 geofence.init_router() 產生的，這支檔案不能 import main，
  所以 main 產生後呼叫 set_geofence_checker() 交給這裡（在 startup 連上 MQTT 之前就會設定好）。
devices_state、ptt_buffers、_audio_ws_queues 只會修改內容、不會重新指定，main.py 匯入後是同一個物件。
這支檔案不 import main。
"""
import asyncio, base64, json, re, time, uuid
from datetime import datetime
import paho.mqtt.client as mqtt
from pydantic import BaseModel
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, HTTPException
from sqlalchemy.orm import Session
from core.database import SessionLocal, MqttConfig, GpsRecord, SosRecord, get_db
from core.auth import require_admin
from core.ws_manager import manager, ptt_manager
from features.tak import forward_gps_to_tak
from features import stt
from features.stt import transcribe_pcm_bytes
from features.social import process_transcript_and_notify

router = APIRouter()          # /ws/map-data、/ws/ptt（main.py 原本 267 行的位置）
config_router = APIRouter()   # /api/mqtt/*（main.py 原本 607 行的位置）

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
        # [拆分 stt.py] STT_AVAILABLE 會在啟動後改變，改用 stt.is_available() 在當下讀取
        # 原本：if STT_AVAILABLE and msg.payload and fastapi_loop:
        if stt.is_available() and msg.payload and fastapi_loop:
            if topic not in ptt_buffers:
                p = topic.split('/')
                ptt_buffers[topic] = {"data": bytearray(), "last_update": 0.0,
                                      "device_id": p[-1] if len(p) > 2 else "unknown"}
            ptt_buffers[topic]["data"]        += msg.payload
            ptt_buffers[topic]["last_update"]  = time.time()

mqtt_client.on_connect = on_mqtt_connect
mqtt_client.on_message = on_mqtt_message

# ====== WebSocket Endpoints ======
# 原本：@app.websocket("/ws/map-data")
@router.websocket("/ws/map-data")
async def websocket_map(websocket: WebSocket):
    await manager.connect(websocket)
    if devices_state:
        await websocket.send_json({"type": "telemetry_update", "data": devices_state})
    try:
        while True: await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)

# 原本：@app.websocket("/ws/ptt")
@router.websocket("/ws/ptt")
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

async def mqtt_stt_worker():
    while True:
        await asyncio.sleep(1.0)
        # [拆分 stt.py] STT_AVAILABLE 會在啟動後改變，改用 stt.is_available() 在當下讀取
        # 原本：if not STT_AVAILABLE: continue
        if not stt.is_available(): continue
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

# ====== MQTT 動態設定 API ======
# 原本：@app.get("/api/mqtt/config")
@config_router.get("/api/mqtt/config")
def get_mqtt_config_api():
    cfg = _get_mqtt_cfg()
    return {"ip": cfg.ip, "port": cfg.port}

class MqttConfigBody(BaseModel):
    ip: str; port: int

# 原本：@app.put("/api/mqtt/config")
@config_router.put("/api/mqtt/config")
def update_mqtt_config(body: MqttConfigBody, db: Session = Depends(get_db),
                       _user: dict = Depends(require_admin)):
    cfg = db.query(MqttConfig).first()
    if not cfg: cfg = MqttConfig(); db.add(cfg)
    cfg.ip = body.ip; cfg.port = body.port
    db.commit()
    return {"msg": "MQTT 設定已儲存"}

# 原本：@app.post("/api/mqtt/reconnect")
@config_router.post("/api/mqtt/reconnect")
def mqtt_reconnect_api(_user: dict = Depends(require_admin)):
    # [修正 2026-11-25] 原本 disconnect() 會讓 paho 的背景網路執行緒（loop_start 開的 loop_forever）結束，
    # 之後 connect() 只建立連線、沒有執行緒處理收發 → 連線完成不了、再也收不到 GPS/SOS/PTT，要重啟伺服器。
    # 啟動時 broker 連不上（startup 沒執行到 loop_start）的情況，按重新連線也一樣收不到。
    # 改成：disconnect 後 loop_stop() 等舊執行緒結束，connect 成功後 loop_start() 重新啟動執行緒。
    # 連線失敗時照舊回 500。
    cfg = _get_mqtt_cfg()
    try:
        mqtt_client.disconnect()
        mqtt_client.loop_stop()     # [修正] 新增
        time.sleep(0.5)
        mqtt_client.connect(cfg.ip, cfg.port, 60)
        mqtt_client.loop_start()    # [修正] 新增
        return {"msg": f"Reconnecting to {cfg.ip}:{cfg.port}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ====== [拆分 mqtt_handler.py 新增] 由 main.py 設定的兩個依賴 ======
# check_geofence_and_notify 由 main 的 geofence.init_router() 產生，產生後呼叫 set_geofence_checker() 交給這裡
check_geofence_and_notify = None

def set_geofence_checker(func):
    global check_geofence_and_notify
    check_geofence_and_notify = func

# fastapi_loop 原本由 main 的 startup 用 global 設定，搬過來後改由 startup 呼叫這個函式
def set_fastapi_loop(loop):
    global fastapi_loop
    fastapi_loop = loop
