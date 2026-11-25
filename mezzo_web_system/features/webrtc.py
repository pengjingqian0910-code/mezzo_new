"""
WebRTC 影像串流
---------------
- WebRTC 選裝檢查（av、aiortc；沒裝時 WEBRTC_AVAILABLE = False，WebRTC 停用）
- MJPEG／RTSP 轉 WebRTC 影像軌（MJPEGStreamTrack、RTSPStreamTrack，只在 WEBRTC_AVAILABLE 時定義）
- /view/{device_id} 獨立影像檢視頁（WhatsApp 連結用，VIEWER_HTML_TEMPLATE）＋ 4 個 /api/webrtc/* 路由

從 main.py 原樣搬出三段：72–84 行（選裝檢查）、518–546 行（VIEWER_HTML_TEMPLATE）、961–1165 行（/view 頁面與 WebRTC API）；
唯一的修改是路由的 @app.xxx 改成 @router.xxx（原本寫法以註解保留）。main.py 在原本 /view 路由的位置 include，路由順序不變。
v1 API（/api/v1/live/...）還留在 main.py，它用到的 WEBRTC_AVAILABLE、DeviceOfferBody、webrtc_offer_by_device 由 main.py 從這裡匯入
（這三個名稱不管有沒有裝 aiortc 都存在）。WEBRTC_AVAILABLE 只在載入時設定一次，沒有用 global 修改。
webrtc_pcs 只會修改內容、不會重新指定。需要的東西直接從 core/、features.nvr 匯入；這支檔案不 import main。
注意：python main.py（reload 模式）會讓 main.py 執行兩次，但這個模組只載入一次，所以啟動日誌裡 [WebRTC] 那行會比搬移前少印一次。
"""
import asyncio, io, uuid, re
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from core.config import aiohttp, AIOHTTP_AVAILABLE
from core.database import Device, SocialMediaConfig, get_db
from features.nvr import _get_nvr_cfg

router = APIRouter()

# ====== WebRTC 相依套件（選裝）======
try:
    import av
    from aiortc import RTCPeerConnection, RTCSessionDescription
    from aiortc.mediastreams import VideoStreamTrack
    WEBRTC_AVAILABLE = AIOHTTP_AVAILABLE  # WebRTC 也需要 aiohttp
    if WEBRTC_AVAILABLE:
        print("[WebRTC] aiortc loaded, WebRTC enabled")
    else:
        print("[WebRTC] aiohttp required, WebRTC disabled")
except ImportError:
    WEBRTC_AVAILABLE = False
    print("[WebRTC] aiortc not installed, WebRTC disabled. Run: pip install aiortc aiohttp")

# ====== 獨立影像檢視頁面 (WhatsApp 連結用) ======
VIEWER_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-TW">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>WiB 即時影像 — {device_name}</title>
<style>*{{margin:0;padding:0;box-sizing:border-box}}body{{background:#000;color:#fff;font-family:sans-serif;display:flex;flex-direction:column;height:100vh}}
header{{background:#0d1117;padding:10px 20px;display:flex;align-items:center;gap:12px;border-bottom:1px solid #1f2937}}
.logo{{color:#00f6ff;font-weight:bold;font-size:16px}}.dev{{color:#9ca3af;font-size:13px}}
#status{{margin-left:auto;font-size:11px;padding:3px 10px;border-radius:10px;font-weight:bold}}
.connecting{{background:#374151;color:#9ca3af}}.connected{{background:#14532d;color:#4ade80}}.error{{background:#450a0a;color:#f87171}}
video{{flex:1;width:100%;background:#000;display:block}}</style></head>
<body>
<header><div class="logo">WiB EOC</div><div class="dev">即時影像 | {device_name} ({device_id})</div>
<div id="status" class="status connecting">● 連線建立中…</div></header>
<video id="v" autoplay playsinline muted></video>
<script>(async()=>{{const statusEl=document.getElementById('status');const videoEl=document.getElementById('v');
const BACKEND='{backend_url}';const DEVICE_ID='{device_id}';
async function connect(){{const pc=new RTCPeerConnection({{iceServers:[{{urls:'stun:stun.l.google.com:19302'}}]}});
pc.addTransceiver('video',{{direction:'recvonly'}});pc.ontrack=e=>{{if(e.streams[0])videoEl.srcObject=e.streams[0];}};
pc.oniceconnectionstatechange=()=>{{const s=pc.iceConnectionState;
if(s==='connected'||s==='completed'){{statusEl.className='status connected';statusEl.textContent='● 串流播放中';}}
else if(s==='failed'||s==='disconnected'){{statusEl.className='status error';statusEl.textContent='✕ 連線中斷';setTimeout(()=>{{pc.close();connect();}},3000);}}}};
const offer=await pc.createOffer();await pc.setLocalDescription(offer);
await new Promise(r=>{{if(pc.iceGatheringState==='complete')return r();pc.addEventListener('icegatheringstatechange',()=>{{if(pc.iceGatheringState==='complete')r();}});setTimeout(r,5000);}});
const res=await fetch(BACKEND+'/api/webrtc/offer/device/'+DEVICE_ID,{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{sdp:pc.localDescription.sdp,type:pc.localDescription.type}})}});
if(!res.ok)throw new Error('HTTP '+res.status);const ans=await res.json();
await pc.setRemoteDescription(new RTCSessionDescription({{sdp:ans.sdp,type:ans.type}}));}}
try{{await connect();}}catch(e){{statusEl.className='status error';statusEl.textContent='✕ '+e.message;}}
}})();</script></body></html>"""

# ====== 獨立影像檢視頁面 ======
# 原本：@app.get("/view/{device_id}", response_class=HTMLResponse)
@router.get("/view/{device_id}", response_class=HTMLResponse)
def viewer_page(device_id: str, db: Session = Depends(get_db)):
    dev = db.query(Device).filter(Device.device_id == device_id).first()
    if not dev: raise HTTPException(404, "設備不存在")
    cfg = db.query(SocialMediaConfig).first()
    backend_url = (cfg.public_url if cfg else "").rstrip('/')
    html = VIEWER_HTML_TEMPLATE.format(
        device_id=device_id, device_name=dev.name, backend_url=backend_url)
    return HTMLResponse(html)

# ====== WebRTC API ======
webrtc_pcs: dict = {}

if WEBRTC_AVAILABLE:
    class MJPEGStreamTrack(VideoStreamTrack):
        kind = "video"
        def __init__(self, mjpeg_url: str):
            super().__init__()
            self.mjpeg_url = mjpeg_url
            self._queue: asyncio.Queue = asyncio.Queue(maxsize=5)
            self._fetch_task = None

        async def _fetch_frames(self):
            while True:
                buf = b""
                try:
                    timeout = aiohttp.ClientTimeout(connect=10, total=None)
                    async with aiohttp.ClientSession(timeout=timeout) as sess:
                        async with sess.get(self.mjpeg_url) as resp:
                            if resp.status != 200:
                                await asyncio.sleep(3); continue
                            async for chunk in resp.content.iter_chunked(8192):
                                buf += chunk
                                while True:
                                    s = buf.find(b'\xff\xd8')
                                    if s == -1: buf = b""; break
                                    e = buf.find(b'\xff\xd9', s + 2)
                                    if e == -1: buf = buf[s:]; break
                                    jpeg = buf[s:e + 2]; buf = buf[e + 2:]
                                    if not self._queue.full():
                                        await self._queue.put(jpeg)
                except asyncio.CancelledError: return
                except Exception as ex:
                    print(f"[WebRTC] MJPEG 擷取錯誤，重連: {ex}")
                    await asyncio.sleep(3)

        def _make_black_frame(self, pts, time_base):
            frame = av.VideoFrame(640, 360, "yuv420p")
            for p in frame.planes: p.update(bytes(p.buffer_size))
            frame.pts = pts; frame.time_base = time_base; return frame

        async def recv(self):
            if self._fetch_task is None:
                self._fetch_task = asyncio.ensure_future(self._fetch_frames())
            pts, time_base = await self.next_timestamp()
            try:
                jpeg = await asyncio.wait_for(self._queue.get(), timeout=5.0)
            except asyncio.TimeoutError:
                return self._make_black_frame(pts, time_base)
            try:
                container = av.open(io.BytesIO(jpeg), format="mjpeg")
                for pkt in container.demux(video=0):
                    for frm in pkt.decode():
                        out = frm.reformat(format="yuv420p")
                        out.pts = pts; out.time_base = time_base; return out
            except Exception: pass
            return self._make_black_frame(pts, time_base)

        def stop(self):
            if self._fetch_task and not self._fetch_task.done():
                self._fetch_task.cancel()
            super().stop()

    # TODO（2026-11-25 拆 webrtc.py 實測時發現，拆分前就有，之後回來修）：
    #   RTSP 來源的 WebRTC 連線關閉時（DELETE /api/webrtc/{pc_id} 或客戶端斷線），整個伺服器程序偶發崩潰
    #   （exit code 0xC0000005 access violation，之後所有連線被拒）。隨機發生；MJPEG 來源不會。
    #   推測（未證實）：_fetch_frames 被取消時在事件迴圈執行緒 container.close()，
    #   但 _stream_worker 執行緒還在 demux 同一個 av container（PyAV 不是執行緒安全）。
    #   重現：系統 Python（有 aiortc），offer 用 RTSP 來源、收到畫面後 DELETE，重複幾次。
    class RTSPStreamTrack(VideoStreamTrack):
        kind = "video"
        def __init__(self, rtsp_url: str):
            super().__init__()
            self.rtsp_url = rtsp_url
            self._queue: asyncio.Queue = asyncio.Queue(maxsize=5)
            self._fetch_task = None

        async def _fetch_frames(self):
            loop = asyncio.get_running_loop()
            while True:
                stop_flag = {"stop": False}
                container = None
                try:
                    def _stream_worker():
                        nonlocal container
                        container = av.open(self.rtsp_url, options={"rtsp_transport": "tcp", "stimeout": "5000000"})
                        vs = container.streams.video[0]; vs.thread_type = "AUTO"
                        for packet in container.demux(vs):
                            if stop_flag["stop"] or packet.size == 0: break
                            for frame in packet.decode():
                                out = frame.reformat(format="yuv420p")
                                asyncio.run_coroutine_threadsafe(self._put_frame(out), loop)
                    await loop.run_in_executor(None, _stream_worker)
                except asyncio.CancelledError: stop_flag["stop"] = True; break
                except Exception as ex:
                    print(f"[WebRTC/RTSP] 擷取錯誤，重連: {ex}"); await asyncio.sleep(3)
                finally:
                    stop_flag["stop"] = True
                    if container:
                        try: container.close()
                        except Exception: pass

        async def _put_frame(self, frame):
            if not self._queue.full(): await self._queue.put(frame)

        async def recv(self):
            if self._fetch_task is None:
                self._fetch_task = asyncio.ensure_future(self._fetch_frames())
            pts, time_base = await self.next_timestamp()
            try:
                frame = await asyncio.wait_for(self._queue.get(), timeout=8.0)
                frame.pts = pts; frame.time_base = time_base; return frame
            except asyncio.TimeoutError:
                f = av.VideoFrame(640, 360, "yuv420p")
                for p in f.planes: p.update(bytes(p.buffer_size))
                f.pts = pts; f.time_base = time_base; return f

        def stop(self):
            if self._fetch_task and not self._fetch_task.done():
                self._fetch_task.cancel()
            super().stop()

    def _make_video_track(stream_url: str):
        if stream_url.startswith("rtsp://") or stream_url.startswith("rtsps://"):
            return RTSPStreamTrack(stream_url)
        return MJPEGStreamTrack(stream_url)

class WebRTCOfferBody(BaseModel):
    sdp: str; type: str
    mjpeg_url: str = ""; rtsp_url: str = ""

# 原本：@app.post("/api/webrtc/offer")
@router.post("/api/webrtc/offer")
async def webrtc_offer(body: WebRTCOfferBody):
    if not WEBRTC_AVAILABLE:
        raise HTTPException(status_code=503, detail="WebRTC 模組未安裝")
    stream_url = body.rtsp_url or body.mjpeg_url
    if not stream_url:
        raise HTTPException(status_code=400, detail="需提供 rtsp_url 或 mjpeg_url")
    offer = RTCSessionDescription(sdp=body.sdp, type=body.type)
    pc    = RTCPeerConnection()
    pc_id = str(uuid.uuid4())
    webrtc_pcs[pc_id] = pc
    track = _make_video_track(stream_url)
    pc.addTrack(track)
    @pc.on("connectionstatechange")
    async def on_conn_state():
        if pc.connectionState in ("failed", "closed"):
            track.stop(); await pc.close(); webrtc_pcs.pop(pc_id, None)
    await pc.setRemoteDescription(offer)
    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)
    elapsed = 0.0
    while pc.iceGatheringState != "complete" and elapsed < 10.0:
        await asyncio.sleep(0.1); elapsed += 0.1
    return {"sdp": pc.localDescription.sdp, "type": pc.localDescription.type, "pc_id": pc_id}

# 原本：@app.delete("/api/webrtc/{pc_id}")
@router.delete("/api/webrtc/{pc_id}")
async def webrtc_close(pc_id: str):
    pc = webrtc_pcs.pop(pc_id, None)
    if pc: await pc.close()
    return {"msg": "closed"}

# 原本：@app.get("/api/webrtc/status")
@router.get("/api/webrtc/status")
def webrtc_status():
    return {"available": WEBRTC_AVAILABLE, "active_connections": len(webrtc_pcs)}

class DeviceOfferBody(BaseModel):
    sdp: str; type: str

# 原本：@app.post("/api/webrtc/offer/device/{device_id}")
@router.post("/api/webrtc/offer/device/{device_id}")
async def webrtc_offer_by_device(device_id: str, body: DeviceOfferBody,
                                  db: Session = Depends(get_db)):
    dev = db.query(Device).filter(Device.device_id == device_id).first()
    if not dev: raise HTTPException(404, "設備不存在")
    if not WEBRTC_AVAILABLE: raise HTTPException(503, "WebRTC 模組未安裝")
    stream_url = dev.mjpeg_url or ""
    if stream_url:
        m = re.search(r"ch=(\d+)", stream_url)
        if m:
            cfg = _get_nvr_cfg()
            ch_rtsp = int(m.group(1)) + 1
            stream_url = f"rtsp://{cfg.username}:{cfg.password}@{cfg.ip}:{cfg.rtsp_port}/ch{ch_rtsp}"
    if not stream_url: raise HTTPException(400, "此設備無可用串流 URL")
    offer = RTCSessionDescription(sdp=body.sdp, type=body.type)
    pc    = RTCPeerConnection()
    pc_id = str(uuid.uuid4())
    webrtc_pcs[pc_id] = pc
    track = _make_video_track(stream_url)
    pc.addTrack(track)
    @pc.on("connectionstatechange")
    async def on_state():
        if pc.connectionState in ("failed", "closed"):
            track.stop(); await pc.close(); webrtc_pcs.pop(pc_id, None)
    await pc.setRemoteDescription(offer)
    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)
    elapsed = 0.0
    while pc.iceGatheringState != "complete" and elapsed < 10.0:
        await asyncio.sleep(0.1); elapsed += 0.1
    return {"sdp": pc.localDescription.sdp, "type": pc.localDescription.type, "pc_id": pc_id}
