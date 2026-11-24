"""
TAK / ATAK 整合模組
-------------------
- TAK TCP Server：讓 ATAK 客戶端直接連進來（TAK_TCP_PORT，預設 8087），收到 GPS 時推 CoT 給它們
- CoT 產生與送出：build_gps_cot / build_video_cot、UDP multicast（send_cot_udp）、TCP（send_cot）
- forward_gps_to_tak：MQTT 收到 GPS 時由 main.py 呼叫
- 5 個 /api/tak/* 路由（router），main.py 在原本的位置 app.include_router()，路由順序不變

從 main.py 原樣搬出（104–240 行、957–1046 行）；唯一的修改是路由的 @app.xxx 改成 @router.xxx（原本寫法以註解保留）。
TAK TCP Server 在 main.py 的 startup 事件才啟動（_start_tak_tcp_server），不是在 import 時。
需要的東西直接從 core/ 匯入；這支檔案不 import main。
"""
import os, asyncio, base64, json
import urllib.request
from datetime import datetime, timedelta
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from core.config import NVR_AUTH
from core.database import SessionLocal, TakServerConfig, NVRConfig, get_db
from core.auth import get_current_user

router = APIRouter()

# ====== TAK TCP Server（供 ATAK 客戶端連線）======
TAK_TCP_PORT = int(os.getenv("TAK_TCP_PORT", "8087"))
_tak_clients: list = []  # list of asyncio.StreamWriter

async def _tak_tcp_handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    addr = writer.get_extra_info('peername')
    print(f"[TAK] ATAK connected from {addr}")
    _tak_clients.append(writer)
    try:
        while True:
            data = await reader.read(4096)
            if not data:
                break
    except Exception:
        pass
    finally:
        _tak_clients.remove(writer)
        try: writer.close()
        except Exception: pass
        print(f"[TAK] ATAK disconnected {addr}")

async def _start_tak_tcp_server():
    server = await asyncio.start_server(_tak_tcp_handler, "0.0.0.0", TAK_TCP_PORT)
    print(f"[TAK] TCP server listening on port {TAK_TCP_PORT}")
    async with server:
        await server.serve_forever()

async def broadcast_cot_to_atak(xml: str):
    """把 CoT XML 推送給所有已連線的 ATAK 客戶端"""
    data = xml.encode('utf-8')
    dead = []
    for writer in list(_tak_clients):
        try:
            writer.write(data)
            await writer.drain()
        except Exception:
            dead.append(writer)
    for w in dead:
        try: _tak_clients.remove(w)
        except ValueError: pass

# ====== TAK / CoT 模組 ======
def _tak_cfg() -> TakServerConfig:
    db = SessionLocal()
    cfg = db.query(TakServerConfig).first()
    db.close()
    return cfg

def _cot_time(dt: datetime, stale_minutes: int = 5) -> tuple:
    fmt = "%Y-%m-%dT%H:%M:%S.00Z"
    t = dt.strftime(fmt)
    s = (dt + timedelta(minutes=stale_minutes)).strftime(fmt)
    return t, s

def build_gps_cot(device_id: str, lat: float, lon: float,
                  battery: int = 0, callsign: str = "") -> str:
    now = datetime.utcnow()
    t, stale = _cot_time(now)
    cs = callsign or device_id
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<event version="2.0" uid="{device_id}" type="a-f-G-U-C" how="m-g"'
        f' time="{t}" start="{t}" stale="{stale}">'
        f'<point lat="{lat}" lon="{lon}" hae="0" ce="9999999" le="9999999"/>'
        f'<detail>'
        f'<contact callsign="{cs}"/>'
        f'<remarks>battery={battery}</remarks>'
        f'</detail>'
        f'</event>'
    )

def build_video_cot(uid: str, alias: str, address: str,
                    rtsp_port: int, channel: int,
                    lat: float = 0.0, lon: float = 0.0) -> str:
    now = datetime.utcnow()
    t, stale = _cot_time(now, stale_minutes=60)
    path = f"/ch{channel}"
    rtsp_url = f"rtsp://{address}:{rtsp_port}{path}"
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<event version="2.0" uid="{uid}" type="b-i-v" how="h-e"'
        f' time="{t}" start="{t}" stale="{stale}">'
        f'<point lat="{lat}" lon="{lon}" hae="0" ce="9999999" le="9999999"/>'
        f'<detail>'
        f'<__video uid="{uid}" url="{rtsp_url}"/>'
        f'<ConnectionEntry networkTimeout="12000" uid="{uid}"'
        f' path="{path}" protocol="raw" address="{address}" port="{rtsp_port}"'
        f' roverPort="-1" remotePath="" bufferTime="-1" rtspReliable="0"'
        f' ignoreEmbeddedKLV="false" alias="{alias}"/>'
        f'</detail>'
        f'</event>'
    )

ATAK_MULTICAST_GROUP = "239.2.3.1"
ATAK_MULTICAST_PORT  = 6969

async def send_cot_udp(xml: str, host: str = ATAK_MULTICAST_GROUP,
                       port: int = ATAK_MULTICAST_PORT) -> bool:
    import socket, struct
    try:
        data = xml.encode('utf-8')
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 32)
        sock.sendto(data, (host, port))
        sock.close()
        return True
    except Exception as e:
        print(f"[TAK] UDP send failed ({host}:{port}): {e}")
        return False

async def send_cot(xml: str, host: str, port: int) -> bool:
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=5
        )
        writer.write(xml.encode('utf-8'))
        await writer.drain()
        writer.close()
        await writer.wait_closed()
        return True
    except Exception as e:
        print(f"[TAK] TCP send failed ({host}:{port}): {e}")
        return False

async def forward_gps_to_tak(device_id: str, lat: float, lon: float, battery: int):
    cfg = _tak_cfg()
    if not cfg or not cfg.enabled:
        return
    xml = build_gps_cot(device_id, lat, lon, battery, cfg.callsign)
    # 推給所有已連線的 ATAK TCP 客戶端
    if _tak_clients:
        await broadcast_cot_to_atak(xml)
    # UDP multicast（ATAK 直接收，不需要 TAK Server）
    await send_cot_udp(xml)
    # 如果有設 TAK Server host，也走 TCP
    if cfg.host:
        await send_cot(xml, cfg.host, cfg.port)

# ====== TAK Server APIs ======
# 原本：@app.get("/api/tak/config")
@router.get("/api/tak/config")
def get_tak_config(_user: dict = Depends(get_current_user)):
    cfg = _tak_cfg()
    if not cfg:
        return {"host": "", "port": 8087, "enabled": False, "callsign": "Mezzo-EOC"}
    return {"host": cfg.host, "port": cfg.port, "enabled": cfg.enabled, "callsign": cfg.callsign}

class TakConfigBody(BaseModel):
    host: str
    port: int = 8087
    enabled: bool = False
    callsign: str = "Mezzo-EOC"

# 原本：@app.put("/api/tak/config")
@router.put("/api/tak/config")
def update_tak_config(body: TakConfigBody, db: Session = Depends(get_db),
                      _user: dict = Depends(get_current_user)):
    cfg = db.query(TakServerConfig).first()
    if not cfg:
        cfg = TakServerConfig(); db.add(cfg)
    cfg.host = body.host; cfg.port = body.port
    cfg.enabled = body.enabled; cfg.callsign = body.callsign
    db.commit()
    return {"msg": "TAK Server 設定已儲存"}

# 原本：@app.post("/api/tak/push_video")
@router.post("/api/tak/push_video")
async def tak_push_video(_user: dict = Depends(get_current_user),
                         db: Session = Depends(get_db)):
    """將 NVR 所有頻道的 RTSP URL 推送至 TAK Server 作為 Video Link"""
    tak_cfg = _tak_cfg()
    if not tak_cfg or not tak_cfg.enabled or not tak_cfg.host:
        raise HTTPException(400, "TAK Server 未啟用，請先在設定中填寫 host 並開啟")
    nvr_cfg = db.query(NVRConfig).first()
    if not nvr_cfg:
        raise HTTPException(400, "NVR 尚未設定")
    results = []
    # 取攝影機清單決定頻道數
    try:
        base = f"http://{nvr_cfg.ip}:{nvr_cfg.http_port}"
        auth = base64.b64decode(NVR_AUTH).decode() if NVR_AUTH else f"{nvr_cfg.username}:{nvr_cfg.password}"
        auth_b64 = base64.b64encode(auth.encode()).decode()
        req = urllib.request.Request(f"{base}/CameraList.cgi")
        req.add_header("Authorization", f"Basic {auth_b64}")
        with urllib.request.urlopen(req, timeout=5) as resp:
            cameras = json.loads(resp.read().decode())
    except Exception as e:
        cameras = [{"Ch": str(i)} for i in range(1, 4)]
    for cam in cameras:
        ch = int(cam.get("channelID", cam.get("Ch", cam.get("ch", 0))))
        uid = f"NVR-CH{ch}"
        alias = cam.get("desc", cam.get("Name", cam.get("name", f"Camera {ch}")))
        xml = build_video_cot(uid, alias, nvr_cfg.ip, nvr_cfg.rtsp_port, ch)
        ok = await send_cot_udp(xml)
        if tak_cfg.host:
            ok = await send_cot(xml, tak_cfg.host, tak_cfg.port) or ok
        results.append({"channel": ch, "uid": uid, "alias": alias, "sent": ok})
    return {"pushed": len(results), "results": results}

# 原本：@app.post("/api/tak/test_send")
@router.post("/api/tak/test_send")
async def tak_test_send(lat: float = 25.0, lon: float = 121.5,
                        callsign: str = "TEST-MEZZO",
                        _user: dict = Depends(get_current_user)):
    """送一筆測試 CoT GPS 到 UDP multicast，用來驗證 ATAK 能否收到"""
    xml = build_gps_cot("TEST-MEZZO-001", lat, lon, 100, callsign)
    ok_udp = await send_cot_udp(xml)
    ok_tcp = False
    if _tak_clients:
        await broadcast_cot_to_atak(xml)
        ok_tcp = True
    return {"sent_udp": ok_udp, "sent_tcp": ok_tcp,
            "atak_clients_connected": len(_tak_clients),
            "lat": lat, "lon": lon, "callsign": callsign,
            "multicast": f"{ATAK_MULTICAST_GROUP}:{ATAK_MULTICAST_PORT}",
            "xml_preview": xml[:200]}

# 原本：@app.get("/api/tak/status")
@router.get("/api/tak/status")
async def tak_status(_user: dict = Depends(get_current_user)):
    """測試與 TAK Server 的 TCP 連線"""
    cfg = _tak_cfg()
    if not cfg or not cfg.host:
        return {"connected": False, "reason": "未設定 TAK Server host"}
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(cfg.host, cfg.port), timeout=5
        )
        writer.close()
        await writer.wait_closed()
        return {"connected": True, "host": cfg.host, "port": cfg.port}
    except Exception as e:
        return {"connected": False, "host": cfg.host, "port": cfg.port, "reason": str(e)}
