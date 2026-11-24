"""
NVR 模組
--------
- NVR 設定輔助函式：_get_nvr_cfg / _nvr_auth_b64 / _nvr_base_url
  （main.py 的設備 API、WebRTC、v1 API、NVR Viewer 也會用到，從這裡匯入）
- config_router：/api/nvr/config 的 GET / PUT（main.py 原本 775–794 行的位置 include）
- router：其餘 15 個 /api/nvr/* 路由——即時、歷史影像、串流代理、快照、本機磁碟 AVI（main.py 原本 830–1227 行的位置 include）
  分成兩個 router 是為了讓路由順序跟搬移前一樣（中間夾著 MQTT 設定 API 與 TAK 路由）

從 main.py 原樣搬出（119–136、775–794、830–1227 行）；唯一的修改是路由的 @app.xxx 改成
@config_router.xxx / @router.xxx（原本寫法以註解保留）。
需要的東西直接從 core/ 匯入；這支檔案不 import main。
"""
import os, asyncio, base64, json, re
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from core.config import NVR_MEDIA_PATH, aiohttp, AIOHTTP_AVAILABLE
from core.database import SessionLocal, NVRConfig, get_db
from core.auth import require_admin

config_router = APIRouter()
router = APIRouter()

# ====== NVR 動態設定輔助函式 ======
def _get_nvr_cfg():
    db = SessionLocal()
    try:
        cfg = db.query(NVRConfig).first()
        if not cfg:
            cfg = NVRConfig()
            db.add(cfg)
            db.commit()
            db.refresh(cfg)
        return cfg
    finally:
        db.close()

def _nvr_auth_b64(cfg) -> str:
    return base64.b64encode(f"{cfg.username}:{cfg.password}".encode()).decode()

def _nvr_base_url(cfg) -> str:
    return f"http://{cfg.ip}:{cfg.http_port}"

# ====== NVR 動態設定 API ======
# 原本：@app.get("/api/nvr/config")
@config_router.get("/api/nvr/config")
def get_nvr_config_api():
    cfg = _get_nvr_cfg()
    return {"ip": cfg.ip, "http_port": cfg.http_port, "rtsp_port": cfg.rtsp_port,
            "username": cfg.username, "password": cfg.password,
            "auth_b64": _nvr_auth_b64(cfg)}

class NVRConfigBody(BaseModel):
    ip: str; http_port: int; rtsp_port: int; username: str; password: str

# 原本：@app.put("/api/nvr/config")
@config_router.put("/api/nvr/config")
def update_nvr_config(body: NVRConfigBody, db: Session = Depends(get_db),
                      _user: dict = Depends(require_admin)):
    cfg = db.query(NVRConfig).first()
    if not cfg: cfg = NVRConfig(); db.add(cfg)
    cfg.ip = body.ip; cfg.http_port = body.http_port; cfg.rtsp_port = body.rtsp_port
    cfg.username = body.username; cfg.password = body.password
    db.commit()
    return {"msg": "NVR 設定已儲存"}

# ====== NVR 即時 APIs ======
# 原本：@app.get("/api/nvr/server_info")
@router.get("/api/nvr/server_info")
def get_nvr_server_info():
    cfg  = _get_nvr_cfg()
    auth = _nvr_auth_b64(cfg)
    base = _nvr_base_url(cfg)
    try:
        url = f"{base}/GetServerInfo.cgi?Auth={auth}"
        req = urllib.request.Request(url)
        req.add_header("Authorization", f"Basic {auth}")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = resp.read().decode('utf-8')
            try: return json.loads(data)
            except json.JSONDecodeError:
                fixed = re.sub(r'([{,]\s*)([a-zA-Z0-9_]+)\s*:', r'\1"\2":', data)
                return json.loads(fixed)
    except Exception as e:
        print(f"[NVR] GetServerInfo error: {e}")
        raise HTTPException(status_code=500, detail="無法連線至 NVR")

# 原本：@app.get("/api/nvr/cameras")
@router.get("/api/nvr/cameras")
def get_nvr_cameras():
    cfg  = _get_nvr_cfg()
    auth = _nvr_auth_b64(cfg)
    base = _nvr_base_url(cfg)
    try:
        url = f"{base}/CameraList.cgi?Auth={auth}"
        req = urllib.request.Request(url)
        req.add_header("Authorization", f"Basic {auth}")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = resp.read().decode('utf-8')
            try: return json.loads(data)
            except json.JSONDecodeError:
                fixed = re.sub(r'([{,]\s*)([a-zA-Z0-9_]+)\s*:', r'\1"\2":', data)
                return json.loads(fixed)
    except Exception as e:
        print(f"[NVR] CameraList error: {e}")
        raise HTTPException(status_code=500, detail="無法連線至 NVR")

# 原本：@app.get("/api/nvr/record_status")
@router.get("/api/nvr/record_status")
def get_nvr_record_status(channel: int, time_str: str):
    cfg  = _get_nvr_cfg()
    auth = _nvr_auth_b64(cfg)
    base = _nvr_base_url(cfg)
    try:
        url = f"{base}/GetRecordStatus.cgi?time={urllib.parse.quote(time_str)}&type=month&channels={channel}&Auth={auth}"
        req = urllib.request.Request(url)
        req.add_header("Authorization", f"Basic {auth}")
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
# 原本：@app.get("/api/nvr/history")
@router.get("/api/nvr/history")
def get_nvr_history(channels: str, begin_time: str, end_time: str):
    cfg  = _get_nvr_cfg()
    auth = _nvr_auth_b64(cfg)
    base = _nvr_base_url(cfg)
    try:
        params = urllib.parse.urlencode({
            "BeginTime": begin_time, "EndTime": end_time,
            "Channels": channels, "Auth": auth
        }, quote_via=urllib.parse.quote)
        req = urllib.request.Request(f"{base}/GetBackupList.cgi?{params}")
        req.add_header("Authorization", f"Basic {auth}")
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = resp.read().decode('utf-8')
            try: return json.loads(data)
            except json.JSONDecodeError: return {"raw": data}
    except Exception as e:
        print(f"[NVR] GetBackupList error: {e}")
        raise HTTPException(status_code=500, detail="無法取得 NVR 歷史清單")

# 原本：@app.get("/api/nvr/query_event")
@router.get("/api/nvr/query_event")
def query_nvr_events(begin_time: str, end_time: str, event_type: str = "",
                     device_id: str = "", start: int = 0, limit: int = 100):
    cfg  = _get_nvr_cfg()
    auth = _nvr_auth_b64(cfg)
    base = _nvr_base_url(cfg)
    try:
        params = {"BeginTime": begin_time, "EndTime": end_time, "Auth": auth,
                  "Start": start, "Limit": limit}
        if event_type: params["EventType"] = event_type
        if device_id:  params["DeviceID"] = device_id
        qs  = urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
        req = urllib.request.Request(f"{base}/QueryEvent.cgi?{qs}")
        req.add_header("Authorization", f"Basic {auth}")
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = resp.read().decode('utf-8')
            try: return json.loads(data)
            except json.JSONDecodeError: return {"raw": data}
    except Exception as e:
        print(f"[NVR] QueryEvent error: {e}")
        raise HTTPException(status_code=500, detail="無法查詢 NVR 事件")

# 原本：@app.get("/api/nvr/download/avi")
@router.get("/api/nvr/download/avi")
def download_nvr_avi(tag: str):
    from fastapi.responses import RedirectResponse
    cfg  = _get_nvr_cfg()
    auth = _nvr_auth_b64(cfg)
    base = _nvr_base_url(cfg)
    params = urllib.parse.urlencode({"Tag": tag, "Auth": auth})
    return RedirectResponse(url=f"{base}/GetAVIMedia.cgi?{params}")

# 原本：@app.get("/api/nvr/download/raw")
@router.get("/api/nvr/download/raw")
def download_nvr_raw(tag: str):
    from fastapi.responses import RedirectResponse
    cfg  = _get_nvr_cfg()
    auth = _nvr_auth_b64(cfg)
    base = _nvr_base_url(cfg)
    params = urllib.parse.urlencode({"Tag": tag, "Auth": auth})
    return RedirectResponse(url=f"{base}/BackupMedia.cgi?{params}")

# 原本：@app.get("/api/nvr/live_stream/{channel}")
@router.get("/api/nvr/live_stream/{channel}")
async def get_nvr_live_stream(channel: int):
    from fastapi.responses import StreamingResponse
    cfg  = _get_nvr_cfg()
    auth = _nvr_auth_b64(cfg)
    base = _nvr_base_url(cfg)
    nvr_url = f"{base}/mjpeg_stream.cgi?Auth={auth}&ch={channel}&metadata=0"
    sess = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(connect=10, total=None))
    try:
        resp = await sess.get(nvr_url, headers={"Authorization": f"Basic {auth}"})
        if resp.status != 200:
            await resp.release(); await sess.close()
            raise HTTPException(502, f"NVR MJPEG 回應 {resp.status}")
        ct = resp.headers.get("Content-Type", "multipart/x-mixed-replace; boundary=ipcamera")
        async def gen():
            try:
                async for chunk in resp.content.iter_chunked(8192):
                    yield chunk
            except (asyncio.CancelledError, Exception):
                pass
            finally:
                try: resp.release()
                except Exception: pass
                try: await sess.close()
                except Exception: pass
        return StreamingResponse(gen(), media_type=ct,
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
    except HTTPException:
        await sess.close(); raise
    except Exception as e:
        await sess.close()
        raise HTTPException(502, f"MJPEG 即時串流代理失敗: {e}")

# 原本：@app.get("/api/nvr/playback_stream/{channel}")
@router.get("/api/nvr/playback_stream/{channel}")
async def get_nvr_playback_stream(channel: int, time: str):
    from fastapi.responses import StreamingResponse
    cfg  = _get_nvr_cfg()
    auth = _nvr_auth_b64(cfg)
    base = _nvr_base_url(cfg)
    params = urllib.parse.urlencode({"Auth": auth, "ch": channel, "clientid": "web",
                                     "playback": time}, quote_via=urllib.parse.quote)
    nvr_url = f"{base}/mjpeg_stream.cgi?{params}"
    sess = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(connect=10, total=None))
    try:
        resp = await sess.get(nvr_url, headers={"Authorization": f"Basic {auth}"})
        if resp.status != 200:
            await resp.release(); await sess.close()
            raise HTTPException(502, f"NVR 回放回應 {resp.status}")
        ct = resp.headers.get("Content-Type", "multipart/x-mixed-replace; boundary=ipcamera")
        async def gen():
            try:
                async for chunk in resp.content.iter_chunked(8192):
                    yield chunk
            except (asyncio.CancelledError, Exception):
                pass
            finally:
                try: resp.release()
                except Exception: pass
                try: await sess.close()
                except Exception: pass
        return StreamingResponse(gen(), media_type=ct,
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
    except HTTPException:
        await sess.close(); raise
    except Exception as e:
        await sess.close()
        raise HTTPException(502, f"MJPEG 回放串流代理失敗: {e}")

# 原本：@app.get("/api/nvr/fmp4_stream/{channel}")
@router.get("/api/nvr/fmp4_stream/{channel}")
async def get_nvr_fmp4_stream(channel: int):
    """FMP4 即時串流代理（解決 CORS 問題，供 fmp4_stream_player_module.js 使用）"""
    from fastapi.responses import StreamingResponse
    cfg  = _get_nvr_cfg()
    auth = _nvr_auth_b64(cfg)
    base = _nvr_base_url(cfg)
    nvr_url = f"{base}/fmp4_stream.cgi?ch={channel}&Auth={urllib.parse.quote(auth)}"

    if not AIOHTTP_AVAILABLE:
        from fastapi.responses import RedirectResponse
        return RedirectResponse(nvr_url)

    sess = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(connect=10, total=None))
    try:
        resp = await sess.get(nvr_url, headers={"Authorization": f"Basic {auth}"})
        if resp.status != 200:
            await resp.release(); await sess.close()
            raise HTTPException(502, f"NVR FMP4 串流回應 {resp.status}")

        async def gen():
            try:
                async for chunk in resp.content.iter_chunked(32768):
                    yield chunk
            except (asyncio.CancelledError, Exception):
                pass
            finally:
                try: resp.release()
                except Exception: pass
                try: await sess.close()
                except Exception: pass

        return StreamingResponse(gen(), media_type="video/mp4",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
    except HTTPException:
        await sess.close(); raise
    except Exception as e:
        await sess.close()
        raise HTTPException(502, f"FMP4 即時串流代理失敗: {e}")

# 原本：@app.get("/api/nvr/fmp4_playback/{channel}")
@router.get("/api/nvr/fmp4_playback/{channel}")
async def get_nvr_fmp4_playback(channel: int, t: int):
    """FMP4 回放串流代理（t = Unix timestamp 秒）"""
    from fastapi.responses import StreamingResponse
    cfg  = _get_nvr_cfg()
    auth = _nvr_auth_b64(cfg)
    base = _nvr_base_url(cfg)
    nvr_url = (f"{base}/fmp4_stream.cgi"
               f"?ch={channel}&Auth={urllib.parse.quote(auth)}&playback=1&t={t}")

    if not AIOHTTP_AVAILABLE:
        from fastapi.responses import RedirectResponse
        return RedirectResponse(nvr_url)

    sess = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(connect=10, total=None))
    try:
        resp = await sess.get(nvr_url, headers={"Authorization": f"Basic {auth}"})
        if resp.status != 200:
            await resp.release(); await sess.close()
            raise HTTPException(502, f"NVR FMP4 回放回應 {resp.status}")

        async def gen():
            try:
                async for chunk in resp.content.iter_chunked(32768):
                    yield chunk
            except (asyncio.CancelledError, Exception):
                pass
            finally:
                try: resp.release()
                except Exception: pass
                try: await sess.close()
                except Exception: pass

        return StreamingResponse(gen(), media_type="video/mp4",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
    except HTTPException:
        await sess.close(); raise
    except Exception as e:
        await sess.close()
        raise HTTPException(502, f"FMP4 回放串流代理失敗: {e}")

# 原本：@app.get("/api/nvr/snapshot/{channel}")
@router.get("/api/nvr/snapshot/{channel}")
async def get_nvr_snapshot(channel: int, time: str = ""):
    from fastapi.responses import Response
    cfg  = _get_nvr_cfg()
    auth = _nvr_auth_b64(cfg)
    base = _nvr_base_url(cfg)
    time_part = f"&Time={urllib.parse.quote(time)}" if time else ""
    nvr_url = f"{base}/Snapshot.cgi?Ch={channel}&Auth={auth}{time_part}"
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=8)) as sess:
            async with sess.get(nvr_url, headers={"Authorization": f"Basic {auth}"}) as resp:
                data = await resp.read()
                ct = resp.headers.get("Content-Type", "image/jpeg")
        return Response(content=data, media_type=ct)
    except Exception as e:
        raise HTTPException(502, f"Snapshot 代理失敗: {e}")

# ====== NVR 本機磁碟影像 API ======
# 原本：@app.get("/api/nvr/local/history")
@router.get("/api/nvr/local/history")
def nvr_local_history(ch: int, date: str):
    """
    直接掃描本機磁碟列出歷史 AVI 檔案。
    date 格式：YYYY-MM-DD
    路徑規則：NVR_MEDIA_PATH/Ch{ch}/{year}/{month}/{day}/
    """
    try:
        year, month, day = date.split("-")
        month = str(int(month))  # 去掉前導零（1 不是 01）
        day   = str(int(day))
    except Exception:
        raise HTTPException(400, "date 格式錯誤，請用 YYYY-MM-DD")

    dir_path = os.path.join(NVR_MEDIA_PATH, f"Ch{ch}", year, month, day)

    if not os.path.isdir(dir_path):
        return {"ch": ch, "date": date, "path": dir_path, "total": 0, "files": []}

    files = []
    for fname in sorted(os.listdir(dir_path)):
        if not fname.lower().endswith(".avi"):
            continue
        fpath = os.path.join(dir_path, fname)
        size  = os.path.getsize(fpath)
        files.append({
            "filename": fname,
            "size_bytes": size,
            "size_mb": round(size / 1024 / 1024, 2),
            "download_url": f"/api/nvr/local/file?ch={ch}&date={date}&filename={fname}",
            "stream_url": f"/api/nvr/local/stream?ch={ch}&date={date}&filename={fname}"
        })

    return {"ch": ch, "date": date, "path": dir_path, "total": len(files), "files": files}

# 原本：@app.get("/api/nvr/local/file")
@router.get("/api/nvr/local/file")
async def nvr_local_file(ch: int, date: str, filename: str):
    """直接從本機磁碟下載 AVI 檔案"""
    from fastapi.responses import FileResponse

    # 防止路徑穿越攻擊
    safe_filename = os.path.basename(filename)
    if not safe_filename.lower().endswith(".avi"):
        raise HTTPException(400, "只支援 AVI 檔案")

    try:
        year, month, day = date.split("-")
        month = str(int(month))
        day   = str(int(day))
    except Exception:
        raise HTTPException(400, "date 格式錯誤")

    file_path = os.path.join(NVR_MEDIA_PATH, f"Ch{ch}", year, month, day, safe_filename)

    if not os.path.isfile(file_path):
        raise HTTPException(404, f"檔案不存在：{file_path}")

    return FileResponse(file_path, media_type="video/avi",
                        filename=safe_filename)

# TODO（2026-11-25 拆 nvr.py 實測時發現，拆分前就有，之後回來修）：
#   Windows 上用 `python main.py`（reload 模式）啟動時，這個 API 一律回 500 NotImplementedError。
#   原因：reload 模式在 Windows 用的事件迴圈不支援 asyncio.create_subprocess_exec，ffmpeg 啟動不了。
#   Docker（Linux）部署應該正常，未實測。重現：有 AVI 檔時打 /api/nvr/local/stream?ch=..&date=..&filename=xxx.avi
# 原本：@app.get("/api/nvr/local/stream")
@router.get("/api/nvr/local/stream")
async def nvr_local_stream(ch: int, date: str, filename: str):
    """用 ffmpeg 將本機 AVI 即時轉碼為 MP4 串流，供瀏覽器直接播放"""
    from fastapi.responses import StreamingResponse

    safe_filename = os.path.basename(filename)
    if not safe_filename.lower().endswith(".avi"):
        raise HTTPException(400, "只支援 AVI 檔案")

    try:
        year, month, day = date.split("-")
        month = str(int(month))
        day   = str(int(day))
    except Exception:
        raise HTTPException(400, "date 格式錯誤")

    file_path = os.path.join(NVR_MEDIA_PATH, f"Ch{ch}", year, month, day, safe_filename)
    if not os.path.isfile(file_path):
        raise HTTPException(404, f"檔案不存在：{file_path}")

    cmd = [
        "ffmpeg", "-y", "-i", file_path,
        "-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency",
        "-c:a", "aac",
        "-f", "mp4", "-movflags", "frag_keyframe+empty_moov+default_base_moof",
        "pipe:1"
    ]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL
        )
    except FileNotFoundError:
        raise HTTPException(503, "伺服器未安裝 ffmpeg，請先安裝後重啟")

    async def gen():
        try:
            while True:
                chunk = await proc.stdout.read(65536)
                if not chunk:
                    break
                yield chunk
        finally:
            try: proc.kill()
            except Exception: pass

    return StreamingResponse(gen(), media_type="video/mp4",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})
