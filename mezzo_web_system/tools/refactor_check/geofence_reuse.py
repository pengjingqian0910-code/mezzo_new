"""檢查 5（警戒區）：刪除警戒區後新建的區域重用同一個 id，裝置在新區域內必須收到「進入」告警。
（7364feb 修正的 bug 的回歸測試；修正前第 3 行會印「沒有任何告警」）
請在全新資料庫的 app 目錄複本裡執行。用法：cd <app 目錄複本> && python geofence_reuse.py
"""
import sys, os, io, json, asyncio, contextlib
import _guard                                      # noqa: E402  擋下所有對外網路（同目錄的 _guard.py）
sys.path.insert(0, os.getcwd())
with contextlib.redirect_stdout(io.StringIO()):
    import main
from fastapi.testclient import TestClient

c = TestClient(main.app)
alerts = []


async def cap(m):
    alerts.append((m["data"]["geofence_id"], m["data"]["geofence_name"], m["data"]["event_type"]))
main.manager.broadcast = cap

c.post("/api/register", json={"username": "u", "password": "p"})
H = {"Authorization": "Bearer " + c.post("/api/login", json={"username": "u", "password": "p"}).json()["token"]}
sq = json.dumps([{"lng": 121.0, "lat": 25.0}, {"lng": 121.1, "lat": 25.0},
                 {"lng": 121.1, "lat": 25.1}, {"lng": 121.0, "lat": 25.1}])


def gps():
    asyncio.run(main.check_geofence_and_notify("dev1", 25.05, 121.05))


c.post("/api/geofences", json={"name": "舊區域", "points": sq}, headers=H)
gps(); print("1. 進入舊區域 ->", alerts); alerts.clear()
old_id = c.get("/api/geofences").json()[0]["id"]
c.delete(f"/api/geofences/{old_id}", headers=H)
c.post("/api/geofences", json={"name": "新區域", "points": sq}, headers=H)
new_id = c.get("/api/geofences").json()[0]["id"]
print(f"2. 刪掉 id={old_id}，新建的區域 id={new_id}")
gps(); print("3. 裝置還在同位置、在新區域內 ->", alerts or "沒有任何告警")
