"""
登入驗證模組
------------
Web UI 的 Session Token（_sessions / create_session / get_current_user / require_admin），
以及 v1 API 的 JWT 驗證（_v1_err / _create_jwt / _decode_jwt / get_v1_user / require_v1_admin）。

從 main.py 原樣搬出，只有函式和 _sessions 這個 dict，沒有 API 路由；
登入 / 登出 / 註冊 / 使用者管理的 API 還留在 main.py，之後再另外拆。

_sessions 在 main.py 還有地方直接讀寫（登出、v1 語音 WebSocket、NVR viewer），
main.py import 進去的是同一個 dict（只改內容、不重新指定），所以兩邊看到的資料一致。

這支檔案不 import main。
"""
import secrets
from datetime import datetime, timedelta
from typing import Optional
from fastapi import Depends, HTTPException, Header
from core.config import _pyjwt, JWT_AVAILABLE, JWT_SECRET, JWT_EXPIRE_HOURS

# ====== Session Token 管理（Web UI 用）======
_sessions: dict = {}

def create_session(username: str, role: str) -> str:
    token = secrets.token_hex(32)
    _sessions[token] = {"username": username, "role": role}
    return token

def get_current_user(authorization: Optional[str] = Header(default=None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="未登入")
    token = authorization[7:]
    user = _sessions.get(token)
    if not user:
        raise HTTPException(status_code=401, detail="Token 無效或已過期，請重新登入")
    return user

# ====== JWT 工具（v1 API 用）======
def _v1_err(code: str, message: str, status: int = 400):
    """回傳標準化 v1 API 錯誤"""
    return HTTPException(status_code=status, detail={
        "error": code,
        "message": message,
        "timestamp": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    })

def _create_jwt(username: str, role: str) -> str:
    if not JWT_AVAILABLE:
        raise _v1_err("SERVER_ERROR", "JWT 模組未安裝", 500)
    payload = {
        "sub": username,
        "role": role,
        "iat": datetime.utcnow(),
        "exp": datetime.utcnow() + timedelta(hours=JWT_EXPIRE_HOURS)
    }
    return _pyjwt.encode(payload, JWT_SECRET, algorithm="HS256")

def _decode_jwt(token: str) -> dict:
    try:
        payload = _pyjwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        return {"username": payload["sub"], "role": payload.get("role", "operator")}
    except _pyjwt.ExpiredSignatureError:
        raise _v1_err("TOKEN_EXPIRED", "Token 已過期，請重新登入", 401)
    except Exception:
        raise _v1_err("INVALID_TOKEN", "Token 無效", 401)

def get_v1_user(authorization: Optional[str] = Header(default=None)):
    """v1 API 認證：接受 JWT（外部）或 Session Token（內部 Web UI）"""
    if not authorization or not authorization.startswith("Bearer "):
        raise _v1_err("UNAUTHORIZED", "需要 Bearer Token", 401)
    token = authorization[7:]
    # JWT（三段式 xxx.yyy.zzz）
    if JWT_AVAILABLE and token.count(".") == 2:
        return _decode_jwt(token)
    # Session token 回退（相容 Web UI）
    user = _sessions.get(token)
    if user:
        return user
    raise _v1_err("UNAUTHORIZED", "Token 無效或已過期", 401)

def require_v1_admin(user: dict = Depends(get_v1_user)):
    if user["role"] != "admin":
        raise _v1_err("FORBIDDEN", "需要管理員權限", 403)
    return user

def require_admin(user: dict = Depends(get_current_user)):
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="需要管理員權限")
    return user
