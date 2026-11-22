"""檢查 2：用 TestClient 打幾個會用到資料庫的 API，印出狀態碼與回應。
不觸發 startup（不連 MQTT / NVR）。請在全新資料庫的 app 目錄複本裡執行。
用法：cd <app 目錄複本> && python smoke.py
"""
import sys, os, io, contextlib
import _guard                                      # noqa: E402  擋下所有對外網路（同目錄的 _guard.py）
sys.path.insert(0, os.getcwd())
with contextlib.redirect_stdout(io.StringIO()):
    import main
from fastapi.testclient import TestClient

c = TestClient(main.app)   # 不用 with → 不觸發 startup
calls = [("post", "/api/register", {"username": "t1", "password": "p"}),
         ("post", "/api/login", {"username": "t1", "password": "p"}),
         ("post", "/api/login", {"username": "t1", "password": "bad"}),
         ("get", "/api/devices", None), ("get", "/api/geofences", None),
         ("get", "/api/sos/records", None), ("get", "/api/ptt/records", None),
         ("get", "/api/geofences/events", None), ("get", "/api/social/logs", None)]
for m, u, b in calls:
    r = getattr(c, m)(u, json=b) if b else getattr(c, m)(u)
    body = r.text
    if '"token"' in body:
        body = "<has token>"
    print(m.upper(), u, r.status_code, body[:80])
