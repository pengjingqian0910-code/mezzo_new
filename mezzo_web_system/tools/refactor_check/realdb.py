"""檢查 5（真實資料）：用真實 mezzo.db 的「複本」打只讀的 API，確認舊資料在拆分前後顯示一致。
run_checks.py 會先用 sqlite 的 backup API 把 mezzo.db 一致地複製到暫存目錄（不動原檔），再在複本裡執行這支。
會先跑 auto_init_db()（欄位遷移），並在「複本」裡建立一個測試管理員帳號來登入。

輸出只有每個 API 的狀態碼、筆數、內容雜湊值，**不印出實際資料**（裡面有電話號碼、access token 等）。
所有對外網路都被 _guard 擋下。
用法：cd <放了 mezzo.db 複本的 app 目錄> && python realdb.py
"""
import sys, os, io, json, hashlib, contextlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _guard                                      # noqa: E402  先擋網路
sys.path.insert(0, os.getcwd())
if not os.path.exists("mezzo.db"):
    print("NO mezzo.db COPY"); sys.exit(0)
with contextlib.redirect_stdout(io.StringIO()):
    import main
    main.auto_init_db()                            # 跟啟動時一樣做欄位遷移（只影響複本）
from fastapi.testclient import TestClient

c = TestClient(main.app)
TEST_USER = "__refactor_check__"
db = main.SessionLocal()
if not db.query(main.User).filter(main.User.username == TEST_USER).first():
    db.add(main.User(username=TEST_USER, password="check", role="admin"))
    db.commit()
counts = {t: db.execute(main.text(f"SELECT COUNT(*) FROM {t}")).scalar() for t in sorted(main.Base.metadata.tables)}
device_ids = [d.device_id for d in db.query(main.Device).all()]
db.close()
print("table row counts:", counts)

H = {"Authorization": "Bearer " + c.post("/api/login", json={"username": TEST_USER, "password": "check"}).json()["token"]}
V = {"Authorization": "Bearer " + c.post("/api/v1/auth/login", json={"username": TEST_USER, "password": "check"}).json()["token"]}


def summarize(label, r, drop=()):
    try:
        data = r.json()
        if isinstance(data, dict):
            data = {k: v for k, v in data.items() if k not in drop}
        n = len(data) if isinstance(data, (list, dict)) else "-"
        h = hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]
    except Exception:
        n, h = "-", hashlib.sha256(r.content).hexdigest()[:16]
    print(f"{label:44} {r.status_code}  items={n:<6} sha={h}")


ids = ",".join(device_ids)
for label, url, hdr, drop in [
    ("GET /api/devices?username=<admin>",   f"/api/devices?username={TEST_USER}", None, ()),
    ("GET /api/admin/all_devices",          "/api/admin/all_devices", None, ()),
    ("GET /api/users",                      "/api/users", H, ()),
    ("GET /api/geofences",                  "/api/geofences", None, ()),
    ("GET /api/geofences/events",           "/api/geofences/events?limit=5000", H, ()),
    ("GET /api/sos/records",                "/api/sos/records?limit=5000", None, ()),
    ("GET /api/ptt/records",                "/api/ptt/records", None, ()),
    ("GET /api/social/logs",                "/api/social/logs?limit=5000", None, ()),
    ("GET /api/social/config",              "/api/social/config", None, ()),
    ("GET /api/nvr/config",                 "/api/nvr/config", None, ()),
    ("GET /api/mqtt/config",                "/api/mqtt/config", None, ()),
    ("GET /api/tak/config",                 "/api/tak/config", H, ()),
    ("GET /api/gps/history（全部設備）",      f"/api/gps/history?device_ids={ids}&limit=100000", None, ()),
    ("GET /api/v1/devices/status",          "/api/v1/devices/status", V, ("timestamp",)),
]:
    if "device_ids=" in url and not ids:
        print(f"{label:44} (沒有設備，略過)"); continue
    summarize(label, c.get(url, headers=hdr), drop)
_guard.report()
