"""檢查 5（警戒區）：完整流程，送出的資料格式與 js/GeofenceTab.js 相同。
新增 / 列表 / 停用 / 啟用 / 改名 / 刪除、權限（401/404）、進出偵測、事件查詢、WebSocket 廣播內容。
請在全新資料庫的 app 目錄複本裡執行。用法：cd <app 目錄複本> && python geofence_flow.py
"""
import sys, os, io, json, asyncio, contextlib
import _guard                                      # noqa: E402  擋下所有對外網路（同目錄的 _guard.py）
sys.path.insert(0, os.getcwd())
with contextlib.redirect_stdout(io.StringIO()):
    import main
from fastapi.testclient import TestClient

c = TestClient(main.app)          # 不用 with → 不觸發 startup
sent = []


async def fake_broadcast(msg):    # 攔截 WebSocket 廣播，記錄內容
    d = dict(msg["data"]); d.pop("timestamp", None); sent.append((msg["type"], d))
main.manager.broadcast = fake_broadcast


def show(label, r):
    print(f"{label:42} {r.status_code} {r.text[:110]}")


c.post("/api/register", json={"username": "u1", "password": "p"})
tok = c.post("/api/login", json={"username": "u1", "password": "p"}).json()["token"]
H = {"Authorization": f"Bearer {tok}"}

square = [{"lng": 121.0, "lat": 25.0}, {"lng": 121.1, "lat": 25.0},
          {"lng": 121.1, "lat": 25.1}, {"lng": 121.0, "lat": 25.1}]
body = {"name": "管制區A", "points": json.dumps(square)}

show("POST 未登入", c.post("/api/geofences", json=body))
show("POST 錯誤 token", c.post("/api/geofences", json=body, headers={"Authorization": "Bearer x"}))
show("POST 新增", c.post("/api/geofences", json=body, headers=H))
show("GET 列表(不需登入)", c.get("/api/geofences"))
gid = c.get("/api/geofences").json()[0]["id"]


def gps(dev, lng, lat):
    asyncio.run(main.check_geofence_and_notify(dev, lat, lng))


gps("dev1", 121.05, 25.05)   # 進入
gps("dev1", 121.06, 25.06)   # 還在裡面 → 不觸發
gps("dev1", 122.0, 26.0)     # 離開
gps("dev2", 120.0, 24.0)     # 一開始就在外面 → 不觸發
show("PUT 停用", c.put(f"/api/geofences/{gid}", json={"is_enabled": False}, headers=H))
gps("dev1", 121.05, 25.05)   # 停用中 → 不觸發
show("PUT 啟用", c.put(f"/api/geofences/{gid}", json={"is_enabled": True}, headers=H))
gps("dev1", 121.05, 25.05)   # 再次進入
show("PUT 改名", c.put(f"/api/geofences/{gid}", json={"name": "管制區B"}, headers=H))
gps("dev1", 122.0, 26.0)     # 離開，應使用新名稱
show("PUT 未登入", c.put(f"/api/geofences/{gid}", json={"name": "x"}))
show("PUT 不存在的 id", c.put("/api/geofences/999", json={"name": "x"}, headers=H))
show("GET 列表", c.get("/api/geofences"))

ev = c.get("/api/geofences/events", headers=H).json()
for e in ev:
    e.pop("timestamp", None)
print("GET events:", json.dumps(ev, ensure_ascii=False))
show("GET events 未登入", c.get("/api/geofences/events"))
show("GET events device_id=dev2", c.get("/api/geofences/events?device_id=dev2", headers=H))
show("GET events limit=1 筆數", c.get("/api/geofences/events?limit=1", headers=H))
print("broadcasts:", json.dumps(sent, ensure_ascii=False))

show("DELETE 未登入", c.delete(f"/api/geofences/{gid}"))
show("DELETE", c.delete(f"/api/geofences/{gid}", headers=H))
show("GET 列表(刪除後)", c.get("/api/geofences"))
show("DELETE 不存在的 id", c.delete("/api/geofences/999", headers=H))
