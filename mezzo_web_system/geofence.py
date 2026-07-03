"""
警戒區（Geofence）模組
----------------------
資料模型、伺服器端進出偵測、WhatsApp 通知、CRUD API 全部獨立在這支檔案。

跟 main.py 之間刻意不用 `import main` 互相 import（那樣在 `python main.py`
直接執行時，main.py 會以 "__main__" 身分執行，geofence.py 若 `from main import X`
會觸發 Python 把 main.py 當成另一個叫 "main" 的模組重新載入一次，產生兩份
main 模組實例，導致像 ConnectionManager 這種需要單例的東西整個對不起來）。

改用「依賴注入」：main.py 呼叫 init_models() / init_router()，把它已經定義好
的東西（Base、SessionLocal、get_current_user...）當參數傳進來，這裡完全不
反向 import main，兩邊各自獨立、沒有循環匯入的問題。
"""
import json
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends, Header
from sqlalchemy import Column, Integer, String, Boolean
from sqlalchemy.orm import Session


def init_models(Base):
    """在 Base.metadata.create_all() 執行前呼叫，註冊 Geofence / GeofenceEvent 兩張表"""

    class Geofence(Base):
        __tablename__ = 'geofences'
        id         = Column(Integer, primary_key=True, index=True)
        name       = Column(String)
        points     = Column(String)
        is_enabled = Column(Boolean, default=True)

    class GeofenceEvent(Base):
        __tablename__ = 'geofence_events'
        id            = Column(Integer, primary_key=True, index=True)
        device_id     = Column(String, index=True)
        geofence_id   = Column(Integer)
        geofence_name = Column(String)
        event_type    = Column(String)   # "enter" / "exit"
        lat           = Column(String)
        lng           = Column(String)
        timestamp     = Column(String, index=True)

    return Geofence, GeofenceEvent


def _point_in_polygon(lng: float, lat: float, points: list) -> bool:
    """Ray-casting 演算法，跟 js/store.js 的 isPointInPolygon 邏輯一致"""
    inside = False
    n = len(points)
    j = n - 1
    for i in range(n):
        xi, yi = points[i]["lng"], points[i]["lat"]
        xj, yj = points[j]["lng"], points[j]["lat"]
        if ((yi > lat) != (yj > lat)) and (lng < (xj - xi) * (lat - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def init_router(Geofence, GeofenceEvent, SessionLocal, get_current_user, manager,
                User, Device, get_social_config, send_whatsapp_message, generate_viewer_url):
    """在 main.py 裡上面這些依賴都定義好之後呼叫，回傳 (router, check_geofence_and_notify)"""

    router = APIRouter()
    _geofence_inside_state: dict = {}   # (device_id, geofence_id) -> bool，記錄上次偵測時裝置是否在區域內

    def _db_dep():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    def _user_dep(authorization: Optional[str] = Header(default=None)):
        return get_current_user(authorization)

    def _notify_geofence_enter(device_id: str, fence_name: str, lat, lng, ts: str):
        cfg = get_social_config()
        if not cfg or not cfg.is_enabled:
            return
        db = SessionLocal()
        try:
            users_wa = db.query(User).filter(User.whatsapp != None, User.whatsapp != "").all()
            if not users_wa:
                return
            dev = db.query(Device).filter(Device.device_id == device_id).first()
            dev_name = dev.name if dev else device_id
            stream_url = generate_viewer_url(device_id, cfg)
            msg = (f"⚠️ *WiB EOC 警戒區告警*\n設備: {dev_name} ({device_id})\n"
                   f"已進入警戒區:「{fence_name}」\n時間: {ts}\n座標: {lat}, {lng}\n"
                   f"──────────────\n📹 即時影像：\n{stream_url}\n"
                   f"──────────────\nWiB EOC 緊急調度指揮系統")
            for u in users_wa:
                send_whatsapp_message(u.whatsapp, msg, cfg)
        finally:
            db.close()

    async def check_geofence_and_notify(device_id: str, lat: float, lng: float):
        db = SessionLocal()
        try:
            fences = db.query(Geofence).filter(Geofence.is_enabled == True).all()
            for fence in fences:
                try:
                    points = json.loads(fence.points)
                except Exception:
                    continue
                key = (device_id, fence.id)
                was_inside = _geofence_inside_state.get(key, False)
                now_inside = _point_in_polygon(lng, lat, points)
                if now_inside == was_inside:
                    continue
                _geofence_inside_state[key] = now_inside
                event_type = "enter" if now_inside else "exit"
                ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                db.add(GeofenceEvent(device_id=device_id, geofence_id=fence.id,
                                     geofence_name=fence.name, event_type=event_type,
                                     lat=str(lat), lng=str(lng), timestamp=ts))
                db.commit()
                await manager.broadcast({"type": "geofence_alert", "data": {
                    "device_id": device_id, "geofence_id": fence.id,
                    "geofence_name": fence.name, "event_type": event_type,
                    "lat": lat, "lng": lng, "timestamp": ts
                }})
                if event_type == "enter":
                    _notify_geofence_enter(device_id, fence.name, lat, lng, ts)
        finally:
            db.close()

    @router.get("/api/geofences")
    def get_geofences(db: Session = Depends(_db_dep)):
        return [{"id": g.id, "name": g.name, "points": g.points, "is_enabled": g.is_enabled}
                for g in db.query(Geofence).all()]

    @router.get("/api/geofences/events")
    def get_geofence_events(device_id: Optional[str] = None, limit: int = 200,
                            db: Session = Depends(_db_dep),
                            _user: dict = Depends(_user_dep)):
        q = db.query(GeofenceEvent)
        if device_id:
            q = q.filter(GeofenceEvent.device_id == device_id)
        rows = q.order_by(GeofenceEvent.id.desc()).limit(limit).all()
        return [{"id": r.id, "device_id": r.device_id, "geofence_id": r.geofence_id,
                 "geofence_name": r.geofence_name, "event_type": r.event_type,
                 "lat": r.lat, "lng": r.lng, "timestamp": r.timestamp} for r in rows]

    @router.post("/api/geofences")
    def add_geofence(geo: dict, db: Session = Depends(_db_dep),
                     _user: dict = Depends(_user_dep)):
        db.add(Geofence(name=geo.get("name"), points=geo.get("points"))); db.commit(); return {}

    @router.put("/api/geofences/{geo_id}")
    def update_geofence(geo_id: int, geo: dict, db: Session = Depends(_db_dep),
                        _user: dict = Depends(_user_dep)):
        g = db.query(Geofence).filter(Geofence.id == geo_id).first()
        if not g: raise HTTPException(status_code=404, detail="找不到警戒區")
        if "is_enabled" in geo: g.is_enabled = geo["is_enabled"]
        if "name" in geo:       g.name = geo["name"]
        if "points" in geo:     g.points = geo["points"]
        db.commit(); return {}

    @router.delete("/api/geofences/{geo_id}")
    def del_geofence(geo_id: int, db: Session = Depends(_db_dep),
                     _user: dict = Depends(_user_dep)):
        db.query(Geofence).filter(Geofence.id == geo_id).delete(); db.commit(); return {}

    return router, check_geofence_and_notify
