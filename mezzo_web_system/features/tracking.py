"""
即時位置、GPS 歷史、SOS 紀錄（Web UI 用）
-----------------------------------------
/api/devices/positions、/api/gps/realtime（讀 mqtt_handler 的 devices_state）、
/api/gps/history、/api/gps/history/{device_id}（GpsRecord）、/api/sos/records（SosRecord），共 5 個路由。
（寫入這些資料的是 features/mqtt_handler.py；外部廠商用的 GPS 歷史在 api/v1.py）

從 main.py 原樣搬出 324–372 行；唯一的修改是路由的 @app.xxx 改成 @router.xxx（原本寫法以註解保留）。
main.py 在原本的位置 include，路由順序不變。devices_state 只讀取、是同一個物件。
沒有 global；需要的東西直接從 core/、features/ 匯入；這支檔案不 import main。
"""
import time
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from core.database import GpsRecord, SosRecord, get_db
from features.mqtt_handler import devices_state

router = APIRouter()


# ====== 即時設備位置 API ======
# 原本：@app.get("/api/devices/positions")
@router.get("/api/devices/positions")
def get_device_positions():
    return devices_state

# 原本：@app.get("/api/gps/realtime")
@router.get("/api/gps/realtime")
def gps_realtime():
    return {dev_id: {"lat": s["lat"], "lng": s["lng"],
                     "battery": s["battery"], "status": s["status"],
                     "is_realtime": time.time() - s.get("last_real_time", 0) <= 10}
            for dev_id, s in devices_state.items()}

# 原本：@app.get("/api/gps/history")
@router.get("/api/gps/history")
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

# 原本：@app.get("/api/gps/history/{device_id}")
@router.get("/api/gps/history/{device_id}")
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
# 原本：@app.get("/api/sos/records")
@router.get("/api/sos/records")
def get_sos_records(limit: int = 100, db: Session = Depends(get_db)):
    rows = db.query(SosRecord).order_by(SosRecord.id.desc()).limit(limit).all()
    return [{"id": r.id, "device_id": r.device_id, "channel": r.channel,
             "lat": float(r.lat or 0), "lng": float(r.lng or 0),
             "timestamp": r.timestamp} for r in rows]
