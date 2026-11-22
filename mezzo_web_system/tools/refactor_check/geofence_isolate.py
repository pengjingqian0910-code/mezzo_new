"""檢查 5（警戒區）：刪除一個警戒區，不能影響其他警戒區的進出狀態（不能讓其他區域重複告警）。
兩台裝置、兩個重疊的區域，刪掉其中一個後同位置再回報。
請在全新資料庫的 app 目錄複本裡執行。用法：cd <app 目錄複本> && python geofence_isolate.py
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
    d = m["data"]; alerts.append((d["device_id"], d["geofence_name"], d["event_type"]))
main.manager.broadcast = cap

c.post("/api/register", json={"username": "u", "password": "p"})
H = {"Authorization": "Bearer " + c.post("/api/login", json={"username": "u", "password": "p"}).json()["token"]}
big   = json.dumps([{"lng": 121.0, "lat": 25.0}, {"lng": 121.2, "lat": 25.0},
                    {"lng": 121.2, "lat": 25.2}, {"lng": 121.0, "lat": 25.2}])
small = json.dumps([{"lng": 121.0, "lat": 25.0}, {"lng": 121.1, "lat": 25.0},
                    {"lng": 121.1, "lat": 25.1}, {"lng": 121.0, "lat": 25.1}])
c.post("/api/geofences", json={"name": "大區域", "points": big}, headers=H)     # id 1
c.post("/api/geofences", json={"name": "小區域", "points": small}, headers=H)   # id 2（在大區域內）


def gps(dev):
    asyncio.run(main.check_geofence_and_notify(dev, 25.05, 121.05))


gps("dev1"); gps("dev2"); print("1. 兩台進入兩個重疊區域 ->", alerts); alerts.clear()
small_id = [g for g in c.get("/api/geofences").json() if g["name"] == "小區域"][0]["id"]
c.delete(f"/api/geofences/{small_id}", headers=H)
gps("dev1"); gps("dev2"); print("2. 刪掉小區域後，同位置再回報 ->", alerts or "沒有告警（大區域沒有重複告警）")
