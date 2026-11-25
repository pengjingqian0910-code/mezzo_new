"""
使用者與登入（Web UI 用）
-------------------------
/api/login、/api/logout、/api/register、/api/users，以及使用者的 WhatsApp 號碼、重設密碼、指派管理者，共 7 個路由。
（外部廠商用的 JWT 登入在 api/v1.py；Session Token 的建立與驗證在 core/auth.py）

從 main.py 原樣搬出 283–341 行；唯一的修改是路由的 @app.xxx 改成 @router.xxx（原本寫法以註解保留）。
main.py 在原本的位置 include，路由順序不變。沒有 global；需要的東西直接從 core/ 匯入；這支檔案不 import main。
"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.orm import Session
from core.database import User, get_db
from core.auth import _sessions, create_session, get_current_user, require_admin

router = APIRouter()


# ====== Auth & User APIs ======
# 原本：@app.post("/api/login")
@router.post("/api/login")
def login(data: dict, db: Session = Depends(get_db)):
    user = db.query(User).filter(
        User.username == data.get("username"),
        User.password == data.get("password")
    ).first()
    if not user: raise HTTPException(status_code=401, detail="帳密錯誤")
    token = create_session(user.username, user.role)
    return {"token": token, "username": user.username, "role": user.role}

# 原本：@app.post("/api/logout")
@router.post("/api/logout")
def logout(authorization: Optional[str] = Header(default=None)):
    if authorization and authorization.startswith("Bearer "):
        _sessions.pop(authorization[7:], None)
    return {"msg": "已登出"}

# 原本：@app.post("/api/register")
@router.post("/api/register")
def register(data: dict, db: Session = Depends(get_db)):
    if db.query(User).filter(User.username == data.get("username")).first():
        raise HTTPException(status_code=400, detail="帳號已存在")
    db.add(User(username=data.get("username"), password=data.get("password"),
                email=data.get("email"), role="operator"))
    db.commit()
    return {"msg": "註冊成功"}

# 原本：@app.get("/api/users")
@router.get("/api/users")
def get_users(db: Session = Depends(get_db), _user: dict = Depends(get_current_user)):
    return [{"username": u.username, "email": u.email, "role": u.role,
             "whatsapp": u.whatsapp or "",
             "manager": u.manager.username if u.manager else None}
            for u in db.query(User).all()]

# 原本：@app.put("/api/users/{username}/whatsapp")
@router.put("/api/users/{username}/whatsapp")
def update_whatsapp(username: str, data: dict, db: Session = Depends(get_db),
                    _user: dict = Depends(get_current_user)):
    user = db.query(User).filter(User.username == username).first()
    if not user: raise HTTPException(status_code=404, detail="使用者不存在")
    user.whatsapp = data.get("whatsapp", "").strip()
    db.commit()
    return {"msg": "WhatsApp 號碼已更新"}

# 原本：@app.put("/api/users/{username}/reset_password")
@router.put("/api/users/{username}/reset_password")
def reset_pwd(username: str, data: dict, db: Session = Depends(get_db),
              _user: dict = Depends(require_admin)):
    user = db.query(User).filter(User.username == username).first()
    if user: user.password = data.get("new_password")
    db.commit()
    return {"msg": "密碼已重設"}

# 原本：@app.put("/api/users/{username}/assign_manager")
@router.put("/api/users/{username}/assign_manager")
def assign_mgr(username: str, data: dict, db: Session = Depends(get_db),
               _user: dict = Depends(require_admin)):
    user = db.query(User).filter(User.username == username).first()
    mgr  = db.query(User).filter(User.username == data.get("manager_username")).first()
    user.manager_id = mgr.id if mgr else None
    user.role = data.get("role", user.role)
    db.commit()
    return {"msg": "權限與群組已更新"}
