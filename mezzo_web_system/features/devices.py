"""
設備管理（Web UI 用）
---------------------
_device_dict（設備資料＋由 NVR 設定組出 rtsp_url）、設備清單（依角色）、全部設備、可綁定的設備、新增／刪除設備、
使用者綁定／解除綁定設備、/api/me/bind_device（自己綁定），共 8 個路由。
（外部廠商用的設備 API 在 api/v1.py）

從 main.py 原樣搬出 295–386 行；唯一的修改是路由的 @app.xxx 改成 @router.xxx（原本寫法以註解保留）。
main.py 在原本的位置 include，路由順序不變。沒有 global；需要的東西直接從 core/、features/ 匯入；這支檔案不 import main。
注意：get_devices 的 group_manager 分支用到 user.managed_users，這個關聯方向有既有 bug，見 core/database.py 的 TODO。
"""
import re
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from core.database import User, Device, get_db
from core.auth import get_current_user
from features.nvr import _get_nvr_cfg

router = APIRouter()


# ====== Device APIs ======
def _device_dict(d):
    rtsp_url = ""
    if d.mjpeg_url:
        m = re.search(r"ch=(\d+)", d.mjpeg_url)
        if m:
            cfg = _get_nvr_cfg()
            ch_rtsp = int(m.group(1)) + 1
            rtsp_url = f"rtsp://{cfg.username}:{cfg.password}@{cfg.ip}:{cfg.rtsp_port}/ch{ch_rtsp}"
    return {"device_id": d.device_id, "name": d.name,
            "mjpeg_url": d.mjpeg_url or "", "rtsp_url": rtsp_url}

# 原本：@app.get("/api/devices")
@router.get("/api/devices")
def get_devices(username: str = None, db: Session = Depends(get_db)):
    if not username: return []
    user = db.query(User).filter(User.username == username).first()
    if not user: return []
    if user.role == "admin":
        devices = db.query(Device).all()
    elif user.role == "group_manager":
        dev_set = set(user.devices)
        for u in user.managed_users:
            for d in u.devices: dev_set.add(d)
        devices = list(dev_set)
    else:
        devices = user.devices
    return [_device_dict(d) for d in devices]

# 原本：@app.get("/api/admin/all_devices")
@router.get("/api/admin/all_devices")
def get_all_devices(db: Session = Depends(get_db)):
    return [_device_dict(d) for d in db.query(Device).all()]

# 原本：@app.get("/api/devices/available")
@router.get("/api/devices/available")
def get_available_devices(username: str, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == username).first()
    if not user: return []
    bound_ids = {d.device_id for d in user.devices}
    return [{"device_id": d.device_id, "name": d.name}
            for d in db.query(Device).all() if d.device_id not in bound_ids]

# 原本：@app.post("/api/devices")
@router.post("/api/devices")
def add_device(dev: dict, db: Session = Depends(get_db)):
    if db.query(Device).filter(Device.device_id == dev.get("device_id")).first():
        raise HTTPException(status_code=400, detail="DeviceID 已存在系統")
    db.add(Device(device_id=dev.get("device_id"), name=dev.get("name"),
                  mjpeg_url=dev.get("mjpeg_url", "")))
    db.commit()
    return {"msg": "設備註冊成功"}

# 原本：@app.delete("/api/devices/{device_id}")
@router.delete("/api/devices/{device_id}")
def del_device(device_id: str, db: Session = Depends(get_db)):
    db.query(Device).filter(Device.device_id == device_id).delete()
    db.commit()
    return {"msg": "刪除成功"}

# 原本：@app.post("/api/users/{username}/bind")
@router.post("/api/users/{username}/bind")
def bind_device(username: str, data: dict, db: Session = Depends(get_db),
                current_user: dict = Depends(get_current_user)):
    if current_user["role"] == "operator" and current_user["username"] != username:
        raise HTTPException(status_code=403, detail="只能綁定自己的帳號")
    user   = db.query(User).filter(User.username == username).first()
    device = db.query(Device).filter(Device.device_id == data.get("device_id")).first()
    if not device: raise HTTPException(status_code=404, detail="找不到此設備 ID")
    if device not in user.devices: user.devices.append(device); db.commit()
    return {"msg": "設備綁定成功"}

# 原本：@app.delete("/api/users/{username}/unbind/{device_id}")
@router.delete("/api/users/{username}/unbind/{device_id}")
def unbind_device(username: str, device_id: str, db: Session = Depends(get_db),
                  current_user: dict = Depends(get_current_user)):
    if current_user["role"] == "operator" and current_user["username"] != username:
        raise HTTPException(status_code=403, detail="只能解除綁定自己的帳號")
    user   = db.query(User).filter(User.username == username).first()
    device = db.query(Device).filter(Device.device_id == device_id).first()
    if device in user.devices: user.devices.remove(device); db.commit()
    return {"msg": "解除綁定成功"}

# 原本：@app.post("/api/me/bind_device")
@router.post("/api/me/bind_device")
def operator_self_bind(data: dict, db: Session = Depends(get_db),
                       current_user: dict = Depends(get_current_user)):
    device_id = data.get("device_id", "").strip()
    if not device_id: raise HTTPException(status_code=400, detail="device_id 不可為空")
    user = db.query(User).filter(User.username == current_user["username"]).first()
    if current_user["role"] == "operator" and user.devices:
        user.devices.clear()
    device = db.query(Device).filter(Device.device_id == device_id).first()
    if not device:
        device = Device(device_id=device_id, name=device_id, mjpeg_url="")
        db.add(device)
    if device not in user.devices:
        user.devices.append(device)
    db.commit()
    return {"msg": f"已綁定設備 {device_id}", "device_id": device_id}
