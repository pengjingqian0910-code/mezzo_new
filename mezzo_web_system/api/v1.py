"""
EOC Web Service RESTful API v1（對外：外部合作廠商）
--------------------------------------------------
路徑前綴 /api/v1/，認證用 Bearer JWT（外部廠商）或 Session Token（內部 Web UI）。
- _v1_device_status、_get_user_devices（只有 v1 在用）
- Module 1 Auth／Mapping、Module 2 Device Status、Module 3 Live（訂閱資訊、串流、WebRTC、即時語音 WebSocket）、
  Module 4 History（GPS、音檔、NVR 影片列表與下載）、Device ↔ NVR Channel 對應，共 16 個路由

從 main.py 原樣搬出 566–1150 行（一整段）；唯一的修改是路由的 @app.xxx 改成 @router.xxx（原本寫法以註解保留）。
main.py 在原本的位置（NVR Viewer 前面）include，路由順序不變。
這是給外部廠商用的對外合約，跟 features/ 裡給自己前端用的 API 分開放；修改時要注意不要破壞廠商的使用方式。
之後如果檔案變大或要出 v2，可以照上面的 Module 分區拆成 api/v1/ 底下多個檔案。
沒有 global、沒有共用狀態的重新指定；需要的東西直接從 core/、features/ 匯入；這支檔案不 import main。
"""
import asyncio, json, os, re, time
import urllib.request
import urllib.parse
from datetime import datetime
from fastapi import APIRouter, WebSocket, Depends, HTTPException
from sqlalchemy.orm import Session
from core.config import JWT_AVAILABLE, JWT_EXPIRE_HOURS, AUDIO_BASE_PATH, aiohttp, AIOHTTP_AVAILABLE
from core.database import SessionLocal, User, Device, GpsRecord, get_db
from core.auth import _sessions, _v1_err, _create_jwt, _decode_jwt, get_v1_user, require_v1_admin
from features.nvr import _get_nvr_cfg, _nvr_auth_b64, _nvr_base_url
from features.mqtt_handler import _get_mqtt_cfg, devices_state, _audio_ws_queues
from features.webrtc import WEBRTC_AVAILABLE, DeviceOfferBody, webrtc_offer_by_device

router = APIRouter()


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

# 原本：@app.post("/api/v1/auth/login")
@router.post("/api/v1/auth/login")
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

# 原本：@app.post("/api/v1/users")
@router.post("/api/v1/users")
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

# 原本：@app.post("/api/v1/mapping/assign")
@router.post("/api/v1/mapping/assign")
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

# 原本：@app.delete("/api/v1/mapping/assign")
@router.delete("/api/v1/mapping/assign")
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

# 原本：@app.get("/api/v1/mapping/devices/{userId}")
@router.get("/api/v1/mapping/devices/{userId}")
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

# 原本：@app.get("/api/v1/devices/status")
@router.get("/api/v1/devices/status")
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

# 原本：@app.get("/api/v1/live/{deviceId}/subscribe")
@router.get("/api/v1/live/{deviceId}/subscribe")
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

# 原本：@app.get("/api/v1/live/{deviceId}/stream")
@router.get("/api/v1/live/{deviceId}/stream")
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

# 原本：@app.post("/api/v1/live/{deviceId}/webrtc/offer")
@router.post("/api/v1/live/{deviceId}/webrtc/offer")
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

# 原本：@app.get("/api/v1/history/{deviceId}/gps")
@router.get("/api/v1/history/{deviceId}/gps")
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

# 原本：@app.get("/api/v1/history/{deviceId}/audio")
@router.get("/api/v1/history/{deviceId}/audio")
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

# 原本：@app.get("/api/v1/history/{deviceId}/videos")
@router.get("/api/v1/history/{deviceId}/videos")
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

# 原本：@app.get("/api/v1/history/{deviceId}/videos/download")
@router.get("/api/v1/history/{deviceId}/videos/download")
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

# 原本：@app.websocket("/api/v1/live/{deviceId}/audio/ws")
@router.websocket("/api/v1/live/{deviceId}/audio/ws")
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

# 原本：@app.put("/api/v1/devices/{deviceId}/nvr_channel")
@router.put("/api/v1/devices/{deviceId}/nvr_channel")
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

# 原本：@app.get("/api/v1/devices/{deviceId}/nvr_channel")
@router.get("/api/v1/devices/{deviceId}/nvr_channel")
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
