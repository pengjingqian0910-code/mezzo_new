"""
音檔與 PTT 紀錄（Web UI 用）
---------------------------
/api/audio/{device_id}/{filename}、/api/audio/{device_id}（AUDIO_BASE_PATH 底下的設備錄音檔）、
POST /api/ptt/records（上傳錄音 → .raw 轉 WAV → STT 雙語辨識 → 存 PttRecord → 語音關鍵字通知）、GET /api/ptt/records，共 4 個路由。

從 main.py 原樣搬出 336–392 行；唯一的修改是路由的 @app.xxx 改成 @router.xxx（原本寫法以註解保留）。
main.py 在原本的位置 include，路由順序不變。STT 是否可用照拆 stt.py 時的做法用 stt.is_available() 在當下讀取。
上傳的錄音存到相對路徑 static/audio/（跟搬移前一樣，以伺服器的工作目錄為準）。
沒有 global；需要的東西直接從 core/、features/ 匯入；這支檔案不 import main。
"""
import asyncio, os, time
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, File, UploadFile, Form
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from core.config import AUDIO_BASE_PATH
from core.database import PttRecord, get_db
from features import stt
from features.stt import pcm_to_wav_bytes, transcribe_bilingual
from features.social import process_transcript_and_notify

router = APIRouter()


# ====== 音檔服務 API ======
# 原本：@app.get("/api/audio/{device_id}/{filename}")
@router.get("/api/audio/{device_id}/{filename}")
def serve_audio(device_id: str, filename: str):
    safe_device_id = os.path.basename(device_id)
    safe_filename  = os.path.basename(filename)
    audio_path = os.path.join(AUDIO_BASE_PATH, safe_device_id, safe_filename)
    if not os.path.exists(audio_path):
        raise HTTPException(status_code=404, detail="音檔不存在")
    return FileResponse(audio_path)

# 原本：@app.get("/api/audio/{device_id}")
@router.get("/api/audio/{device_id}")
def list_audio(device_id: str):
    safe_device_id = os.path.basename(device_id)
    device_audio_dir = os.path.join(AUDIO_BASE_PATH, safe_device_id)
    if not os.path.isdir(device_audio_dir): return []
    files = sorted(os.listdir(device_audio_dir))
    return [{"filename": f, "url": f"/api/audio/{safe_device_id}/{f}"} for f in files]

# ====== PTT 記錄 API ======
# 原本：@app.post("/api/ptt/records")
@router.post("/api/ptt/records")
async def upload_ptt_record(group_id: int = Form(...), sender: str = Form(...),
                            text: str = Form(""), audio: UploadFile = File(...),
                            db: Session = Depends(get_db)):
    raw_bytes = await audio.read()
    orig_name = audio.filename or "audio"
    if orig_name.endswith('.raw'):
        raw_bytes = pcm_to_wav_bytes(raw_bytes, sample_rate=8000, channels=1, sampwidth=2)
        orig_name = orig_name[:-4] + '.wav'
    file_name = f"ptt_{int(time.time())}_{orig_name}"
    file_path = f"static/audio/{file_name}"
    with open(file_path, "wb") as f:
        f.write(raw_bytes)
    text_zh, text_en = ("", "")
    # [拆分 stt.py] STT_AVAILABLE 會在啟動後改變，改用 stt.is_available() 在當下讀取
    # 原本：if STT_AVAILABLE:
    if stt.is_available():
        loop = asyncio.get_running_loop()
        text_zh, text_en = await loop.run_in_executor(None, transcribe_bilingual, file_path)
    elif text.strip():
        text_zh = text
    final_text = text_zh or text_en or text
    db.add(PttRecord(group_id=group_id, sender=sender, text=final_text,
                     text_zh=text_zh, text_en=text_en,
                     audio_url=f"/{file_path}",
                     timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    db.commit()
    asyncio.create_task(process_transcript_and_notify(sender, final_text, source="upload"))
    return {"msg": "錄音儲存成功", "transcript": final_text, "text_zh": text_zh, "text_en": text_en}

# 原本：@app.get("/api/ptt/records")
@router.get("/api/ptt/records")
def get_ptt_records(group_id: int = None, db: Session = Depends(get_db)):
    query = db.query(PttRecord)
    if group_id: query = query.filter(PttRecord.group_id == group_id)
    records = query.order_by(PttRecord.id.desc()).all()
    return [{"id": r.id, "group_id": r.group_id, "sender": r.sender, "text": r.text,
             "text_zh": r.text_zh or "", "text_en": r.text_en or "",
             "audio_url": r.audio_url, "timestamp": r.timestamp} for r in records]
