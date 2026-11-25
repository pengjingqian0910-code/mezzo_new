"""
Social Media／WhatsApp 通知
---------------------------
- get_social_config、send_whatsapp_message（Meta／Twilio）、generate_viewer_url（/view/{device_id} 連結）
- process_transcript_and_notify：語音辨識文字含關鍵字 → 對有填 WhatsApp 的使用者發通知 → 寫 WhatsAppLog
- 5 個 /api/social/* 路由（設定讀寫、通知紀錄、測試發送、stt_status）

從 main.py 原樣搬出三段：341–377 行（WhatsApp 發送函式）、387–429 行（process_transcript_and_notify）、
824–866 行（Social Media／WhatsApp API）；唯一的修改是路由的 @app.xxx 改成 @router.xxx（原本寫法以註解保留）。
main.py 在原本 /api/social 路由的位置 include，路由順序不變。
中間的 geofence.init_router(...) 刻意留在 main.py（警戒區 router 在那個位置 include，跟路由順序有關），
它需要的 get_social_config、send_whatsapp_message、generate_viewer_url 由 main.py 從這裡匯入。
沒有共用狀態、沒有 global。需要的東西直接從 core/、features.stt 匯入；這支檔案不 import main。
"""
import base64, json
import urllib.parse
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from core.database import SessionLocal, User, Device, SocialMediaConfig, WhatsAppLog, get_db
from core.auth import require_admin
from features import stt

router = APIRouter()

# ====== WhatsApp 發送函式 ======
def get_social_config():
    db = SessionLocal()
    cfg = db.query(SocialMediaConfig).first()
    db.close()
    return cfg

def send_whatsapp_message(phone: str, message: str, cfg: SocialMediaConfig) -> tuple:
    phone = phone.strip().lstrip('+')
    if not phone: return False, "no phone"
    try:
        import urllib.request as _ur
        if cfg.provider == "meta":
            url     = f"https://graph.facebook.com/v19.0/{cfg.phone_number_id}/messages"
            headers = {"Authorization": f"Bearer {cfg.access_token}", "Content-Type": "application/json"}
            payload = {"messaging_product": "whatsapp", "to": phone, "type": "text", "text": {"body": message}}
            req = _ur.Request(url, data=json.dumps(payload).encode(), headers=headers, method='POST')
            with _ur.urlopen(req, timeout=10) as resp:
                return resp.status in (200, 201), resp.read().decode()
        elif cfg.provider == "twilio":
            from_num = f"whatsapp:+{cfg.phone_number_id.strip().lstrip('+')}"
            to_num   = f"whatsapp:+{phone}"
            auth_str = base64.b64encode(f"{cfg.account_sid}:{cfg.access_token}".encode()).decode()
            data = urllib.parse.urlencode({"From": from_num, "To": to_num, "Body": message}).encode()
            req  = _ur.Request(
                f"https://api.twilio.com/2010-04-01/Accounts/{cfg.account_sid}/Messages.json",
                data=data, headers={"Authorization": f"Basic {auth_str}"}, method='POST'
            )
            with _ur.urlopen(req, timeout=10) as resp:
                return resp.status in (200, 201), resp.read().decode()
    except Exception as e:
        return False, str(e)
    return False, "unknown provider"

def generate_viewer_url(device_id: str, cfg: SocialMediaConfig) -> str:
    base = (cfg.public_url or "").rstrip('/')
    return f"{base}/view/{device_id}" if base else f"/view/{device_id}"

async def process_transcript_and_notify(device_id: str, transcript: str, source: str = "mqtt"):
    if not transcript: return
    cfg         = get_social_config()
    keyword     = (cfg.stt_keyword if cfg else None) or "影像傳送"
    keyword_hit = keyword in transcript
    stream_url  = ""
    status      = "keyword_not_found"
    recipients  = ""

    if keyword_hit and cfg and cfg.is_enabled:
        stream_url = generate_viewer_url(device_id, cfg)
        db = SessionLocal()
        users_wa = db.query(User).filter(User.whatsapp != None, User.whatsapp != "").all()
        db.close()
        if not users_wa:
            status = "no_recipients"
        else:
            db2 = SessionLocal()
            dev = db2.query(Device).filter(Device.device_id == device_id).first()
            db2.close()
            dev_name = dev.name if dev else device_id
            msg = (f"🚨 *WiB EOC 緊急通知*\n設備: {dev_name} ({device_id})\n"
                   f"時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                   f"語音內容: {transcript}\n──────────────\n"
                   f"📹 即時影像：\n{stream_url}\n──────────────\nWiB EOC 緊急調度指揮系統")
            results = []
            for u in users_wa:
                ok, err = send_whatsapp_message(u.whatsapp, msg, cfg)
                results.append(f"{u.whatsapp}:{'ok' if ok else err[:30]}")
            recipients = ",".join(u.whatsapp for u in users_wa)
            status = "sent" if all(r.endswith(":ok") for r in results) else "partial"
    elif keyword_hit and (not cfg or not cfg.is_enabled):
        status = "disabled"

    db3 = SessionLocal()
    db3.add(WhatsAppLog(
        timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        device_id=device_id, source=source,
        transcript=transcript, keyword_detected=keyword_hit,
        stream_url=stream_url, recipients=recipients, status=status
    ))
    db3.commit()
    db3.close()

# ====== Social Media / WhatsApp API ======
# 原本：@app.get("/api/social/config")
@router.get("/api/social/config")
def get_social_cfg(db: Session = Depends(get_db)):
    cfg = db.query(SocialMediaConfig).first()
    if not cfg: return {}
    return {"provider": cfg.provider, "access_token": cfg.access_token,
            "phone_number_id": cfg.phone_number_id, "account_sid": cfg.account_sid,
            "public_url": cfg.public_url, "stt_keyword": cfg.stt_keyword,
            "is_enabled": cfg.is_enabled}

# 原本：@app.put("/api/social/config")
@router.put("/api/social/config")
def update_social_cfg(data: dict, db: Session = Depends(get_db),
                      _user: dict = Depends(require_admin)):
    cfg = db.query(SocialMediaConfig).first()
    if not cfg: cfg = SocialMediaConfig(); db.add(cfg)
    for field in ("provider", "access_token", "phone_number_id", "account_sid",
                  "public_url", "stt_keyword", "is_enabled"):
        if field in data: setattr(cfg, field, data[field])
    db.commit()
    return {"msg": "設定已儲存"}

# 原本：@app.get("/api/social/logs")
@router.get("/api/social/logs")
def get_social_logs(limit: int = 50, db: Session = Depends(get_db)):
    logs = db.query(WhatsAppLog).order_by(WhatsAppLog.id.desc()).limit(limit).all()
    return [{"id": l.id, "timestamp": l.timestamp, "device_id": l.device_id,
             "source": l.source, "transcript": l.transcript,
             "keyword_detected": l.keyword_detected, "stream_url": l.stream_url,
             "recipients": l.recipients, "status": l.status} for l in logs]

# 原本：@app.post("/api/social/test")
@router.post("/api/social/test")
async def test_whatsapp(data: dict, db: Session = Depends(get_db)):
    cfg = db.query(SocialMediaConfig).first()
    if not cfg: raise HTTPException(400, "尚未設定 WhatsApp 參數")
    phone = data.get("phone", "").strip()
    msg   = data.get("message", "WiB EOC 測試訊息 — 系統運作正常 ✅")
    ok, detail = send_whatsapp_message(phone, msg, cfg)
    return {"success": ok, "detail": detail}

# 原本：@app.get("/api/social/stt_status")
@router.get("/api/social/stt_status")
def stt_status():
    # [拆分 stt.py] STT_AVAILABLE 會在啟動後改變，改用 stt.is_available() 在當下讀取
    # 原本：return {"available": STT_AVAILABLE, "model": "faster-whisper base" if STT_AVAILABLE else None}
    return {"available": stt.is_available(), "model": "faster-whisper base" if stt.is_available() else None}
