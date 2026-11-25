"""檢查 5（MQTT）：把假的 MQTT 訊息直接餵給 on_mqtt_message，比對處理結果。
涵蓋：GPS（JSON 與 ASCII 兩種格式）、GPS 存檔節流、警戒區偵測、TAK 轉送（啟用時，封包被 _guard 擋下並記錄）、
SOS（存檔＋廣播）、PTT 音訊轉發給 /ws/ptt 與 v1 語音訂閱佇列、無法解析的訊息。
不連真的 broker；所有對外網路都被 _guard 擋下。請在全新資料庫的 app 目錄複本裡執行。
用法：cd <app 目錄複本> && python mqtt_flow.py

注意：腳本透過 main.xxx 存取內部狀態（fastapi_loop、devices_state、manager…）。之後拆模組時如果這些名稱
搬走了，輸出會跟基準不同（run_checks 會標出來），屆時要確認是行為改變還是測試需要跟著更新。
"""
import sys, os, io, json, asyncio, threading, contextlib
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

# ---- 背景事件迴圈，模擬 startup 設定的 fastapi_loop ----
loop = asyncio.new_event_loop()
threading.Thread(target=loop.run_forever, daemon=True).start()
# 原本：main.fastapi_loop = loop
M.fastapi_loop = loop


def drain():
    """等背景迴圈把 run_coroutine_threadsafe 排進去的工作做完"""
    for _ in range(5):
        asyncio.run_coroutine_threadsafe(asyncio.sleep(0.05), loop).result()


# ---- 攔截兩個 ConnectionManager 的廣播 ----
sent = []


def strip(d):
    return {k: v for k, v in d.items() if k not in ("id", "timestamp")}


async def map_bc(msg):
    sent.append(("manager", msg["type"], strip(msg["data"])))


async def ptt_bc(msg):
    sent.append(("ptt_manager", msg["topic"], msg["payload"][:24]))


main.manager.broadcast = map_bc
# [更新] 拆 mqtt_handler.py 後 main.py 不再匯入 ptt_manager（只有 MQTT 程式在用），改從 M 取（同一個物件）
# 原本：main.ptt_manager.broadcast = ptt_bc
# 原本：main.ptt_manager.active_connections.append(object())        # 讓「有 /ws/ptt 連線」的分支會跑
M.ptt_manager.broadcast = ptt_bc
M.ptt_manager.active_connections.append(object())        # 讓「有 /ws/ptt 連線」的分支會跑


class Msg:
    def __init__(self, topic, payload):
        self.topic, self.payload = topic, payload


def feed(topic, payload):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        # 原本：main.on_mqtt_message(None, None, Msg(topic, payload))
        M.on_mqtt_message(None, None, Msg(topic, payload))
        drain()
    out = [l for l in buf.getvalue().splitlines() if l.strip()]
    print(f"feed {topic:24} -> printed {out}")


# ---- 準備資料：一個警戒區、TAK 啟用（測試 TAK 轉送路徑，封包會被 _guard 擋下） ----
db = main.SessionLocal()
db.add(main.Geofence(name="管制區A", points=json.dumps(
    [{"lng": 121.0, "lat": 25.0}, {"lng": 121.1, "lat": 25.0}, {"lng": 121.1, "lat": 25.1}, {"lng": 121.0, "lat": 25.1}])))
db.add(main.TakServerConfig(host="203.0.113.10", port=8087, enabled=True, callsign="TEST"))
db.commit(); db.close()

# v1 語音訂閱佇列（模擬一個 /api/v1/live/DEVPTT/audio/ws 連線）
async def _make_queue():
    return asyncio.Queue(maxsize=100)          # 在背景迴圈裡建立，跟正式執行時一樣


audio_q = asyncio.run_coroutine_threadsafe(_make_queue(), loop).result()
# [更新] 拆 api/v1.py 後 main.py 不再匯入 _audio_ws_queues（只有 v1 語音 WebSocket 與 MQTT 程式在用），改從 M 取（同一個物件）
# 原本：main._audio_ws_queues.setdefault("DEVPTT", set()).add(audio_q)
M._audio_ws_queues.setdefault("DEVPTT", set()).add(audio_q)

# ---- 1. GPS ----
feed("WJI/GPS/dev1", json.dumps({"device_id": "dev1", "lat": 25.05, "lng": 121.05, "battery": 80}).encode())
feed("WJI/GPS/dev1", json.dumps({"device_id": "dev1", "lat": 25.06, "lng": 121.06, "battery": 79}).encode())  # 5 秒內 → 不存檔
feed("/WJI/GPS/x",   b"AABBCCDDEEFF,25.20,121.20 tail")             # ASCII 格式、前面有斜線
feed("SOME/DEV/GPS", json.dumps({"device_id": "dev2", "lat": 24.0, "lng": 120.0, "status": "Busy"}).encode())
feed("WJI/GPS/bad",  b"not a gps payload")                           # 無法解析 → 忽略

# ---- 2. SOS ----
sos = b"\x00" * 32 + b"SOSDEV01".ljust(128, b"\x00") + b"25.07,121.07"
feed("WJI/PTT/CH9/SOS", sos)
feed("WJI/PTT/CH9/SOS", b"\x00" * 32 + b"SOSDEV02".ljust(128, b"\x00") + b"garbage")   # 座標壞掉 → exception 分支

# ---- 3. PTT 音訊 ----
feed("WJI/PTT/G1/DEVPTT", b"\x01\x02\x03\x04")
feed("WJI/PTT/G1/OTHER", b"\x05\x06")

# ---- 結果 ----
print("devices_state:", json.dumps({k: {kk: vv for kk, vv in v.items() if kk != "last_real_time"}
                                    for k, v in sorted(main.devices_state.items())}, ensure_ascii=False))
db = main.SessionLocal()
print("gps_records:", [(r.device_id, r.lat, r.lng, r.battery, r.status, r.source) for r in db.query(main.GpsRecord).order_by(main.GpsRecord.id)])
print("sos_records:", [(r.device_id, r.channel, r.lat, r.lng) for r in db.query(main.SosRecord).order_by(main.SosRecord.id)])
print("geofence_events:", [(r.device_id, r.geofence_name, r.event_type) for r in db.query(main.GeofenceEvent).order_by(main.GeofenceEvent.id)])
db.close()
print("broadcasts:", json.dumps(sent, ensure_ascii=False))
async def _drain_queue():
    out = []
    while not audio_q.empty():
        p = audio_q.get_nowait(); p.pop("timestamp", None); out.append(p)
    return out


print("v1 audio queue:", asyncio.run_coroutine_threadsafe(_drain_queue(), loop).result())
# 原本：print("ptt_buffers (STT):", sorted(main.ptt_buffers))
print("ptt_buffers (STT):", sorted(M.ptt_buffers))
_guard.report()
