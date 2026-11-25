"""檢查 5（WebSocket + v1 API / JWT）。
WebSocket：/ws/map-data（連線時的 telemetry、警戒區告警、SOS 廣播）、/ws/ptt（收 PTT 音訊、publish 給 MQTT）、
           /api/v1/live/{id}/audio/ws（token 驗證、設備權限、收語音封包）——訊息都從真正的來源觸發（MQTT 處理函式）。
v1 API：JWT 登入、錯誤帳密、權限（operator / admin）、建立使用者、設備綁定與解除、設備狀態、GPS 歷史、Session token 相容。
所有對外網路都被 _guard 擋下。請在全新資料庫的 app 目錄複本裡執行。
用法：cd <app 目錄複本> && python ws_v1.py

注意：腳本透過 main.xxx 存取內部狀態（fastapi_loop、devices_state、mqtt_client…）。之後拆模組時如果這些名稱
搬走了，輸出會跟基準不同（run_checks 會標出來），屆時要確認是行為改變還是測試需要跟著更新。
"""
import sys, os, io, json, asyncio, contextlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _guard                                      # noqa: E402  先擋網路
sys.path.insert(0, os.getcwd())
with contextlib.redirect_stdout(io.StringIO()):
    import main
# [更新] 拆 mqtt_handler.py 後，fastapi_loop、on_mqtt_message、ptt_buffers 在 features/mqtt_handler.py：
#        設定 main.fastapi_loop 已經影響不到 MQTT 處理函式。有這個模組就用它，沒有（拆分前的版本）就用 main。
#        devices_state、_audio_ws_queues、mqtt_client、manager 是同一個物件（main 匯入共用），照舊從 main 存取。
import importlib.util
if importlib.util.find_spec("features.mqtt_handler"):
    from features import mqtt_handler as M
else:
    M = main
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

DROP = {"timestamp", "id", "iat", "exp", "token", "last_heartbeat"}


def clean(o):
    if isinstance(o, dict):
        return {k: clean(v) for k, v in o.items() if k not in DROP}
    if isinstance(o, list):
        return [clean(x) for x in o]
    return o


def show(label, r):
    try:
        body = json.dumps(clean(r.json()), ensure_ascii=False)
    except Exception:
        body = r.text
    print(f"{label:40} {r.status_code} {body[:300]}")


class Msg:
    def __init__(self, topic, payload):
        self.topic, self.payload = topic, payload


c = TestClient(main.app)

# ---- 準備資料 ----
db = main.SessionLocal()
db.add(main.User(username="admin", password="admin", role="admin"))
db.add(main.User(username="op1", password="p", role="operator"))
db.add(main.Device(device_id="DEV1", name="巡邏車1"))
db.add(main.Device(device_id="DEV2", name="巡邏車2"))
db.add(main.Geofence(name="管制區A", points=json.dumps(
    [{"lng": 121.0, "lat": 25.0}, {"lng": 121.1, "lat": 25.0}, {"lng": 121.1, "lat": 25.1}, {"lng": 121.0, "lat": 25.1}])))
for i, ts in enumerate(["2026-01-01 10:00:00", "2026-01-01 11:00:00", "2026-01-02 10:00:00"]):
    db.add(main.GpsRecord(device_id="DEV1", lat=str(25 + i / 100), lng=str(121 + i / 100), battery=90 - i,
                          status="Online", source="mqtt", timestamp=ts))
db.commit(); db.close()

# ================= v1 API / JWT =================
print("== v1 API ==")
show("v1 login 錯誤帳密", c.post("/api/v1/auth/login", json={"username": "admin", "password": "x"}))
r = c.post("/api/v1/auth/login", json={"username": "admin", "password": "admin"}); show("v1 login admin", r)
A = {"Authorization": "Bearer " + r.json()["token"]}
admin_jwt = r.json()["token"]
r = c.post("/api/v1/auth/login", json={"username": "op1", "password": "p"}); show("v1 login op1", r)
O = {"Authorization": "Bearer " + r.json()["token"]}
op_jwt = r.json()["token"]
print("jwt 三段式:", admin_jwt.count(".") == 2, op_jwt.count(".") == 2)

show("devices/status 沒帶 token", c.get("/api/v1/devices/status"))
show("devices/status 壞 token", c.get("/api/v1/devices/status", headers={"Authorization": "Bearer a.b.c"}))
show("devices/status admin", c.get("/api/v1/devices/status", headers=A))
show("devices/status op1（未綁定）", c.get("/api/v1/devices/status", headers=O))
show("建立使用者 op1 權限不足", c.post("/api/v1/users", json={"username": "x", "password": "y"}, headers=O))
show("建立使用者 role 錯誤", c.post("/api/v1/users", json={"username": "x", "password": "y", "role": "boss"}, headers=A))
show("建立使用者 成功", c.post("/api/v1/users", json={"username": "gm1", "password": "y", "role": "group_manager"}, headers=A))
show("建立使用者 重複", c.post("/api/v1/users", json={"username": "gm1", "password": "y"}, headers=A))
show("綁定 不存在的設備", c.post("/api/v1/mapping/assign", json={"userId": "op1", "deviceId": "NOPE"}, headers=A))
show("綁定 DEV1 → op1", c.post("/api/v1/mapping/assign", json={"userId": "op1", "deviceId": "DEV1"}, headers=A))
show("op1 查自己的設備", c.get("/api/v1/mapping/devices/op1", headers=O))
show("op1 查別人的設備", c.get("/api/v1/mapping/devices/admin", headers=O))
show("GPS 歷史 op1 DEV1", c.get("/api/v1/history/DEV1/gps?start_time=2026-01-01T00:00:00&end_time=2026-01-01T23:59:59", headers=O))
show("GPS 歷史 op1 DEV2（無權限）", c.get("/api/v1/history/DEV2/gps?start_time=2026-01-01T00:00:00&end_time=2026-01-02T23:59:59", headers=O))
show("GPS 歷史 limit=1", c.get("/api/v1/history/DEV1/gps?start_time=2026-01-01&end_time=2026-12-31&limit=1", headers=A))

# Session token（Web UI 登入）也能用在 v1
st = c.post("/api/login", json={"username": "admin", "password": "admin"}).json()["token"]
show("devices/status 用 session token", c.get("/api/v1/devices/status", headers={"Authorization": f"Bearer {st}"}))

# ================= WebSocket =================
print("== WebSocket ==")
main.devices_state.clear()
main.devices_state["DEV1"] = {"lng": 121.5, "lat": 25.5, "battery": 50, "status": "Online", "last_real_time": 0}
published = []
main.mqtt_client.publish = lambda topic, payload=None, *a, **k: published.append((topic, payload))

with c.websocket_connect("/ws/map-data") as ws_map, c.websocket_connect("/ws/ptt") as ws_ptt:
    print("map-data 連線後第一則:", json.dumps(clean(ws_map.receive_json()), ensure_ascii=False))
    # 原本：main.fastapi_loop = ws_map.portal.call(asyncio.get_running_loop)   # 跟 startup 一樣：MQTT 執行緒把工作丟回 app 的迴圈
    M.fastapi_loop = ws_map.portal.call(asyncio.get_running_loop)   # 跟 startup 一樣：MQTT 執行緒把工作丟回 app 的迴圈

    def feed(topic, payload):
        with contextlib.redirect_stdout(io.StringIO()):
            # 原本：main.on_mqtt_message(None, None, Msg(topic, payload))
            M.on_mqtt_message(None, None, Msg(topic, payload))

    feed("WJI/GPS/DEV1", json.dumps({"device_id": "DEV1", "lat": 25.05, "lng": 121.05, "battery": 49}).encode())
    print("map-data 收到（GPS 進警戒區）:", json.dumps(clean(ws_map.receive_json()), ensure_ascii=False))
    feed("WJI/PTT/CH1/SOS", b"\x00" * 32 + b"DEV1".ljust(128, b"\x00") + b"25.07,121.07")
    print("map-data 收到（SOS）:", json.dumps(clean(ws_map.receive_json()), ensure_ascii=False))
    print("ptt 收到（SOS 封包也會轉發）:", clean(ws_ptt.receive_json())["topic"])
    feed("WJI/PTT/G1/DEV1", b"\x01\x02\x03")
    print("ptt 收到（PTT 音訊）:", clean(ws_ptt.receive_json()))
    ws_ptt.send_text(json.dumps({"action": "publish", "topic": "WJI/PTT/G1/WEB", "payload": "hello"}))
    ws_ptt.send_text(json.dumps({"action": "noop"}))
    ws_map.portal.call(asyncio.sleep, 0.2)
    print("ptt publish 給 MQTT:", published)
# [更新] 拆 mqtt_handler.py 後 main.py 不再匯入 ptt_manager，改從 M 取（同一個物件）
# 原本：print("關閉後 manager 連線數:", len(main.manager.active_connections), "ptt_manager:", len(main.ptt_manager.active_connections))
print("關閉後 manager 連線數:", len(main.manager.active_connections), "ptt_manager:", len(M.ptt_manager.active_connections))

# v1 即時語音 WebSocket
for label, url in [("沒帶 token", "/api/v1/live/DEV1/audio/ws"),
                   ("壞 token", "/api/v1/live/DEV1/audio/ws?token=bad"),
                   ("op1 無權限的設備", f"/api/v1/live/DEV2/audio/ws?token={op_jwt}")]:
    try:
        with c.websocket_connect(url) as w:
            print(f"audio ws {label}: 連上了（不應該）", w.receive_json())
    except WebSocketDisconnect as e:
        print(f"audio ws {label}: 被拒絕 code={e.code} reason={e.reason}")

with c.websocket_connect(f"/api/v1/live/DEV1/audio/ws?token={op_jwt}") as w:
    print("audio ws op1 DEV1:", clean(w.receive_json()))
    # 原本：main.fastapi_loop = w.portal.call(asyncio.get_running_loop)
    M.fastapi_loop = w.portal.call(asyncio.get_running_loop)
    with contextlib.redirect_stdout(io.StringIO()):
        # 原本：main.on_mqtt_message(None, None, Msg("WJI/PTT/G1/DEV1", b"\x0a\x0b"))
        M.on_mqtt_message(None, None, Msg("WJI/PTT/G1/DEV1", b"\x0a\x0b"))
    print("audio ws 收到:", clean(w.receive_json()))
with c.websocket_connect(f"/api/v1/live/DEV1/audio/ws?token={st}") as w:
    print("audio ws 用 session token:", clean(w.receive_json()))
print("關閉後語音訂閱佇列:", {k: len(v) for k, v in main._audio_ws_queues.items()})
_guard.report()
