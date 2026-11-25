"""
NVR Viewer 獨立查看器
---------------------
/nvr 頁面（nvr_viewer.html）＋ 10 個 /api/nvrv/* 路由。
- 外部第三方用 /api/nvrv/login 輸入 NVR 位址與帳密，取得 24 小時的 nvrv token（存在 _nvrv_sessions）
- 內部使用者直接帶 Mezzo 的 Bearer token（core.auth._sessions），使用資料庫裡的 NVR 設定

從 main.py 原樣搬出（1750–2016 行，main.py 的最後一段）；唯一的修改是路由的 @app.xxx 改成 @router.xxx
（原本寫法以註解保留）。main.py 在原本的位置（檔案最後）include，路由順序不變。
_nvrv_sessions 只會修改內容、不會重新指定。需要的東西直接從 core/、features.nvr 匯入；這支檔案不 import main。
"""
import asyncio, base64, json, re, secrets, time
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from typing import Optional
from fastapi import APIRouter, HTTPException, Header
from fastapi.responses import FileResponse, HTMLResponse
from core.config import aiohttp, AIOHTTP_AVAILABLE
from core.auth import _sessions
from features.nvr import _get_nvr_cfg, _nvr_auth_b64, _nvr_base_url

router = APIRouter()

# ====== NVR Viewer 獨立查看器 ======
# 第三方 / 外部使用者可用 /api/nvrv/login 取得 token
# 內部使用者直接帶 mezzo Bearer token 即可（使用 DB 中的 NVR 設定）

_nvrv_sessions: dict = {}   # nvrv_token -> {base_url, auth_b64, created_at}

def _resolve_nvrv(nvrv_token: str = "", authorization: str = None):
    """
    回傳 (base_url, auth_b64)。
    優先使用 nvrv_token（外部第三方），否則用 mezzo Bearer token（內部）。
    """
    if nvrv_token and nvrv_token in _nvrv_sessions:
        sess = _nvrv_sessions[nvrv_token]
        if time.time() - sess["created_at"] < 86400:  # 24 小時 TTL
            return sess["base_url"], sess["auth_b64"]
        _nvrv_sessions.pop(nvrv_token, None)
    if authorization and authorization.startswith("Bearer "):
        token = authorization[7:]
        if token in _sessions:
            cfg = _get_nvr_cfg()
            return _nvr_base_url(cfg), _nvr_auth_b64(cfg)
    raise HTTPException(status_code=401, detail="請先登入 NVR 或提供有效的 Mezzo Token")

# 原本：@app.get("/nvr", response_class=HTMLResponse)
@router.get("/nvr", response_class=HTMLResponse)
async def nvr_viewer_page():
    return FileResponse("nvr_viewer.html", media_type="text/html")

# 原本：@app.post("/api/nvrv/login")
@router.post("/api/nvrv/login")
async def nvrv_login(data: dict):
    """第三方登入：驗證 NVR 帳密，回傳 24h session token"""
    ip       = data.get("ip", "").strip()
    port     = int(data.get("port", 80))
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()
    if not ip or not username:
        raise HTTPException(400, "需要提供 IP 與帳號")
    base_url = f"http://{ip}:{port}"
    auth_b64 = base64.b64encode(f"{username}:{password}".encode()).decode()
    # 用 GetServerInfo.cgi 驗證連線
    try:
        req = urllib.request.Request(f"{base_url}/GetServerInfo.cgi?Auth={auth_b64}")
        req.add_header("Authorization", f"Basic {auth_b64}")
        with urllib.request.urlopen(req, timeout=8) as resp:
            if resp.status not in (200, 206):
                raise HTTPException(401, "NVR 帳密錯誤或無法連線")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"無法連線至 NVR ({ip}:{port}): {e}")
    token = secrets.token_hex(32)
    _nvrv_sessions[token] = {"base_url": base_url, "auth_b64": auth_b64, "created_at": time.time()}
    return {"token": token, "msg": "登入成功", "base_url": base_url}

# 原本：@app.post("/api/nvrv/logout")
@router.post("/api/nvrv/logout")
async def nvrv_logout(data: dict):
    _nvrv_sessions.pop(data.get("token", ""), None)
    return {"msg": "已登出"}

# 原本：@app.get("/api/nvrv/server_info")
@router.get("/api/nvrv/server_info")
def nvrv_server_info(token: str = "", authorization: Optional[str] = Header(default=None)):
    base_url, auth_b64 = _resolve_nvrv(token, authorization)
    try:
        req = urllib.request.Request(f"{base_url}/GetServerInfo.cgi?Auth={auth_b64}")
        req.add_header("Authorization", f"Basic {auth_b64}")
        with urllib.request.urlopen(req, timeout=8) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            try:
                return json.loads(raw)
            except Exception:
                fixed = re.sub(r'([{,]\s*)([a-zA-Z0-9_]+)\s*:', r'\1"\2":', raw)
                try:
                    return json.loads(fixed)
                except Exception:
                    return {"raw": raw}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"NVR server_info 錯誤: {e}")

# 原本：@app.get("/api/nvrv/cameras")
@router.get("/api/nvrv/cameras")
def nvrv_cameras(token: str = "", authorization: Optional[str] = Header(default=None)):
    base_url, auth_b64 = _resolve_nvrv(token, authorization)
    try:
        req = urllib.request.Request(f"{base_url}/CameraList.cgi?Auth={auth_b64}")
        req.add_header("Authorization", f"Basic {auth_b64}")
        with urllib.request.urlopen(req, timeout=8) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            try:
                return json.loads(raw)
            except Exception:
                fixed = re.sub(r'([{,]\s*)([a-zA-Z0-9_]+)\s*:', r'\1"\2":', raw)
                try:
                    return json.loads(fixed)
                except Exception:
                    return {"raw": raw}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"NVR cameras 錯誤: {e}")

# 原本：@app.get("/api/nvrv/mjpeg/{ch}")
@router.get("/api/nvrv/mjpeg/{ch}")
async def nvrv_mjpeg(ch: int, token: str = "",
                     authorization: Optional[str] = Header(default=None)):
    """MJPEG 即時串流代理（解決 CORS 及跨網路存取問題）"""
    from fastapi.responses import StreamingResponse as SR
    base_url, auth_b64 = _resolve_nvrv(token, authorization)
    nvr_url = f"{base_url}/mjpeg_stream.cgi?Auth={auth_b64}&ch={ch}&metadata=0"

    if not AIOHTTP_AVAILABLE:
        from fastapi.responses import RedirectResponse
        return RedirectResponse(nvr_url)

    sess = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(connect=10, total=None))
    try:
        resp = await sess.get(nvr_url)
        if resp.status != 200:
            await resp.release(); await sess.close()
            raise HTTPException(502, f"NVR MJPEG 回應 {resp.status}")
        content_type = resp.headers.get("Content-Type", "multipart/x-mixed-replace; boundary=ipcamera")

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

        return SR(gen(), media_type=content_type,
                  headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
    except HTTPException:
        await sess.close(); raise
    except Exception as e:
        await sess.close()
        raise HTTPException(502, f"MJPEG 代理連線失敗: {e}")

# 原本：@app.get("/api/nvrv/playback/{ch}")
@router.get("/api/nvrv/playback/{ch}")
async def nvrv_playback(ch: int, time_str: str, token: str = "",
                        authorization: Optional[str] = Header(default=None)):
    """MJPEG 回放串流代理"""
    from fastapi.responses import StreamingResponse as SR
    base_url, auth_b64 = _resolve_nvrv(token, authorization)
    params = urllib.parse.urlencode({
        "Auth": auth_b64, "ch": ch, "clientid": "web",
        "playback": time_str
    }, quote_via=urllib.parse.quote)
    nvr_url = f"{base_url}/mjpeg_stream.cgi?{params}"

    if not AIOHTTP_AVAILABLE:
        from fastapi.responses import RedirectResponse
        return RedirectResponse(nvr_url)

    sess = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(connect=10, total=None))
    try:
        resp = await sess.get(nvr_url)
        if resp.status != 200:
            await resp.release(); await sess.close()
            raise HTTPException(502, f"NVR 回放回應 {resp.status}")
        content_type = resp.headers.get("Content-Type", "multipart/x-mixed-replace; boundary=ipcamera")

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

        return SR(gen(), media_type=content_type,
                  headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
    except HTTPException:
        await sess.close(); raise
    except Exception as e:
        await sess.close()
        raise HTTPException(502, f"回放代理連線失敗: {e}")

# 原本：@app.get("/api/nvrv/snapshot/{ch}")
@router.get("/api/nvrv/snapshot/{ch}")
async def nvrv_snapshot(ch: int, time_str: str = "", token: str = "",
                        authorization: Optional[str] = Header(default=None)):
    """擷取單張 JPEG 截圖"""
    from fastapi.responses import Response as Resp
    base_url, auth_b64 = _resolve_nvrv(token, authorization)
    params: dict = {"Ch": ch, "Auth": auth_b64}
    if time_str:
        params["Time"] = time_str
    nvr_url = f"{base_url}/Snapshot.cgi?{urllib.parse.urlencode(params, quote_via=urllib.parse.quote)}"

    if not AIOHTTP_AVAILABLE:
        from fastapi.responses import RedirectResponse
        return RedirectResponse(nvr_url)

    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=8)) as sess:
            async with sess.get(nvr_url) as resp:
                data = await resp.read()
                ct = resp.headers.get("Content-Type", "image/jpeg")
        return Resp(content=data, media_type=ct)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"Snapshot 失敗: {e}")

# 原本：@app.get("/api/nvrv/recordings")
@router.get("/api/nvrv/recordings")
def nvrv_recordings(ch: int, begin_time: str, end_time: str,
                    token: str = "", authorization: Optional[str] = Header(default=None)):
    """取得指定時間段的錄影清單"""
    base_url, auth_b64 = _resolve_nvrv(token, authorization)
    params = urllib.parse.urlencode({
        "BeginTime": begin_time, "EndTime": end_time,
        "Channels": ch, "Auth": auth_b64
    }, quote_via=urllib.parse.quote)
    try:
        req = urllib.request.Request(f"{base_url}/GetBackupList.cgi?{params}")
        req.add_header("Authorization", f"Basic {auth_b64}")
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            try:
                return json.loads(raw)
            except Exception:
                return {"raw": raw}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"錄影清單查詢失敗: {e}")

# 原本：@app.get("/api/nvrv/download")
@router.get("/api/nvrv/download")
def nvrv_download(tag: str, fmt: str = "avi", token: str = "",
                  authorization: Optional[str] = Header(default=None)):
    """下載錄影檔案（AVI 壓縮版或 RAW 原始檔）"""
    from fastapi.responses import RedirectResponse
    base_url, auth_b64 = _resolve_nvrv(token, authorization)
    if fmt == "raw":
        params = urllib.parse.urlencode({"Tag": tag, "Auth": auth_b64})
        return RedirectResponse(f"{base_url}/BackupMedia.cgi?{params}")
    params = urllib.parse.urlencode({"Tag": tag, "Auth": auth_b64})
    return RedirectResponse(f"{base_url}/GetAVIMedia.cgi?{params}")

# 原本：@app.get("/api/nvrv/record_status")
@router.get("/api/nvrv/record_status")
def nvrv_record_status(ch: int, time_str: str, token: str = "",
                       authorization: Optional[str] = Header(default=None)):
    """取得月份錄影狀態陣列"""
    base_url, auth_b64 = _resolve_nvrv(token, authorization)
    try:
        url = (f"{base_url}/GetRecordStatus.cgi"
               f"?time={urllib.parse.quote(time_str)}&type=month&channels={ch}&Auth={auth_b64}")
        req = urllib.request.Request(url)
        req.add_header("Authorization", f"Basic {auth_b64}")
        with urllib.request.urlopen(req, timeout=8) as resp:
            root = ET.fromstring(resp.read().decode("utf-8", errors="replace"))
            node = root.find(".//Data")
            if node is not None and node.text:
                sl = list(node.text.strip())
                while len(sl) < 31: sl.append("0")
                return {"status_array": sl[:31]}
    except HTTPException:
        raise
    except Exception as e:
        print(f"[NVRv] record_status 錯誤: {e}")
    return {"status_array": ["0"] * 31}
