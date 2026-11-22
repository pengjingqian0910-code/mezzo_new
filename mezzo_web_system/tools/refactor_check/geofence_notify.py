"""檢查 5（警戒區）：進入警戒區 → WhatsApp 通知。
urllib.request.urlopen 會被換成假的，**不會對外發出任何請求**。
情境：通知啟用、3 個使用者（有號碼 / 空字串 / None）、已登記與未登記的裝置、離開、通知關閉。
請在全新資料庫的 app 目錄複本裡執行。用法：cd <app 目錄複本> && python geofence_notify.py
"""
import sys, os, io, json, asyncio, contextlib, urllib.request
import _guard                                      # noqa: E402  擋下所有對外網路（同目錄的 _guard.py）
sys.path.insert(0, os.getcwd())
with contextlib.redirect_stdout(io.StringIO()):
    import main

captured = []


class FakeResp:
    status = 200
    def read(self): return b'{"ok":true}'
    def __enter__(self): return self
    def __exit__(self, *a): return False


def fake_urlopen(req, timeout=None):
    body = json.loads(req.data.decode())
    captured.append({"url": req.full_url, "to": body["to"], "text": body["text"]["body"]})
    return FakeResp()
urllib.request.urlopen = fake_urlopen          # 擋掉所有真正的 HTTP 請求


async def nob(msg): pass
main.manager.broadcast = nob

db = main.SessionLocal()
db.add(main.SocialMediaConfig(provider="meta", access_token="T", phone_number_id="PNID",
                              public_url="https://eoc.example/", is_enabled=True))
db.add(main.User(username="a", password="p", whatsapp="+886900000001"))
db.add(main.User(username="b", password="p", whatsapp=""))
db.add(main.User(username="c", password="p", whatsapp=None))
db.add(main.Device(device_id="dev1", name="巡邏車1"))
db.add(main.Geofence(name="管制區A", points=json.dumps(
    [{"lng": 121.0, "lat": 25.0}, {"lng": 121.1, "lat": 25.0}, {"lng": 121.1, "lat": 25.1}, {"lng": 121.0, "lat": 25.1}])))
db.commit(); db.close()


def gps(dev, lng, lat): asyncio.run(main.check_geofence_and_notify(dev, lat, lng))


def strip_time(msgs):
    return [dict(m, text="\n".join(l for l in m["text"].splitlines() if not l.startswith("時間:"))) for m in msgs]


gps("dev1", 121.05, 25.05); print("enter (known device):", json.dumps(strip_time(captured), ensure_ascii=False)); captured.clear()
gps("dev1", 122.0, 26.0);   print("exit:", captured); captured.clear()
gps("devX", 121.05, 25.05); print("enter (unknown device):", json.dumps(strip_time(captured), ensure_ascii=False)); captured.clear()

db = main.SessionLocal(); db.query(main.SocialMediaConfig).first().is_enabled = False; db.commit(); db.close()
gps("dev1", 121.05, 25.05); print("enter (notify disabled):", captured)
