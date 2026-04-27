"""
create_test_data.py
-------------------
產生模擬測試資料，讓你在沒有真實設備的情況下測試所有 API。

執行方式（在 mezzo_web_system 目錄下）：
  python create_test_data.py

或指定伺服器位址：
  python create_test_data.py --base http://52.194.210.107:5555
  python create_test_data.py --base http://localhost:5555

產生的資料：
  1. 模擬 WAV 語音檔（3 個設備 × 5 筆 = 15 個檔案）
  2. 透過 API 建立測試帳號與設備
  3. 透過 API 綁定設備到帳號
  4. 印出所有 API 測試指令
"""

import wave, struct, math, os, time, json, sys, argparse
import urllib.request, urllib.parse
from datetime import datetime, timedelta

# ── 設定 ────────────────────────────────────────────────────────────────
parser = argparse.ArgumentParser()
parser.add_argument("--base", default="http://localhost:5555", help="伺服器位址")
parser.add_argument("--admin-user", default="admin", help="管理員帳號")
parser.add_argument("--admin-pass", default="admin", help="管理員密碼")
args = parser.parse_args()

BASE       = args.base.rstrip("/")
ADMIN_USER = args.admin_user
ADMIN_PASS = args.admin_pass

# 測試設備（device_id, 顯示名稱, NVR channel）
TEST_DEVICES = [
    {"device_id": "TEST_DEV_001", "name": "模擬執法儀 A", "channel": 0},
    {"device_id": "TEST_DEV_002", "name": "模擬執法儀 B", "channel": 1},
    {"device_id": "TEST_DEV_003", "name": "模擬執法儀 C", "channel": 2},
]

# 測試帳號
TEST_USERS = [
    {"username": "officer_a", "password": "test1234", "role": "operator"},
    {"username": "sergeant",  "password": "test1234", "role": "group_manager"},
]

AUDIO_DIR = os.path.join(os.path.dirname(__file__), "static", "audio")


# ── 工具函式 ─────────────────────────────────────────────────────────────
def api(method, path, body=None, token=None):
    url = f"{BASE}{path}"
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body else None
    req  = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        err = e.read().decode()
        try:
            return {"_error": json.loads(err)}
        except Exception:
            return {"_error": err, "_status": e.code}
    except Exception as e:
        return {"_error": str(e)}


def make_wav(path: str, freq: int = 440, duration: float = 3.0,
             sample_rate: int = 8000, amplitude: int = 16000):
    """產生一個純音調（正弦波）WAV 檔案"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    n_samples = int(sample_rate * duration)
    with wave.open(path, "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)        # 16-bit
        wf.setframerate(sample_rate)
        frames = bytearray()
        for i in range(n_samples):
            val = int(amplitude * math.sin(2 * math.pi * freq * i / sample_rate))
            frames += struct.pack("<h", val)
        wf.writeframes(bytes(frames))


def ok(label, result):
    if "_error" in result:
        print(f"  ❌ {label}: {result['_error']}")
    else:
        print(f"  ✅ {label}")
    return result


# ════════════════════════════════════════════════════════════════════════
print("\n" + "="*60)
print("  WiB EOC — 測試資料產生器")
print("="*60)

# ── Step 1: 取得 Admin Token ────────────────────────────────────────────
print(f"\n[1] 連線至 {BASE} ...")
res = api("POST", "/api/v1/auth/login",
          {"username": ADMIN_USER, "password": ADMIN_PASS})
if "_error" in res:
    print(f"  ❌ 無法登入（{res['_error']}）")
    print(f"     請確認伺服器已啟動並且帳號密碼正確。")
    sys.exit(1)

ADMIN_TOKEN = res["token"]
print(f"  ✅ Admin 登入成功，JWT 有效期：{res['expires_in']//3600} 小時")

# ── Step 2: 建立測試帳號 ────────────────────────────────────────────────
print("\n[2] 建立測試帳號 ...")
for u in TEST_USERS:
    r = api("POST", "/api/v1/users", u, token=ADMIN_TOKEN)
    ok(f"建立帳號 {u['username']} ({u['role']})", r)

# ── Step 3: 建立設備 + 綁定 NVR Channel ────────────────────────────────
print("\n[3] 建立模擬設備並設定 NVR Channel ...")
for dev in TEST_DEVICES:
    # 先在系統設備庫建立
    r = api("POST", "/api/devices",
            {"device_id": dev["device_id"], "name": dev["name"]},
            token=ADMIN_TOKEN)
    ok(f"建立設備 {dev['device_id']}", r)

    # 設定對應的 NVR Channel
    r = api("PUT", f"/api/v1/devices/{dev['device_id']}/nvr_channel",
            {"channel": dev["channel"], "name": dev["name"]},
            token=ADMIN_TOKEN)
    ok(f"綁定 NVR CH{dev['channel']}", r)

# ── Step 4: 綁定設備到帳號 ─────────────────────────────────────────────
print("\n[4] 綁定設備到帳號 ...")
bindings = [
    ("officer_a", "TEST_DEV_001"),
    ("sergeant",  "TEST_DEV_001"),
    ("sergeant",  "TEST_DEV_002"),
    ("sergeant",  "TEST_DEV_003"),
    ("admin",     "TEST_DEV_001"),
    ("admin",     "TEST_DEV_002"),
    ("admin",     "TEST_DEV_003"),
]
for user, dev_id in bindings:
    r = api("POST", "/api/v1/mapping/assign",
            {"userId": user, "deviceId": dev_id},
            token=ADMIN_TOKEN)
    ok(f"{user} ← {dev_id}", r)

# ── Step 5: 產生模擬語音檔案 ────────────────────────────────────────────
print("\n[5] 產生模擬 WAV 語音檔案 ...")
now = datetime.now()
freqs  = [440, 523, 659, 784, 880]   # 不同音調代表不同人說話
labels = ["巡邏回報", "狀況確認", "位置更新", "任務完成", "緊急警報"]

for dev in TEST_DEVICES:
    dev_dir = os.path.join(AUDIO_DIR, dev["device_id"])
    os.makedirs(dev_dir, exist_ok=True)
    for i, (freq, label) in enumerate(zip(freqs, labels)):
        ts   = now - timedelta(hours=i*2, minutes=i*7)
        name = f"ptt_{ts.strftime('%Y%m%d_%H%M%S')}_{label}.wav"
        path = os.path.join(dev_dir, name)
        make_wav(path, freq=freq, duration=2.5 + i * 0.5)
        print(f"  ✅ {dev['device_id']}/{name}")

total_files = len(TEST_DEVICES) * len(freqs)
print(f"\n  共產生 {total_files} 個 WAV 檔案於 {AUDIO_DIR}/")

# ── Step 6: 取得各帳號 Token ────────────────────────────────────────────
print("\n[6] 取得測試帳號 Token ...")
tokens = {"admin": ADMIN_TOKEN}
for u in TEST_USERS:
    r = api("POST", "/api/v1/auth/login",
            {"username": u["username"], "password": u["password"]})
    if "_error" not in r:
        tokens[u["username"]] = r["token"]
        print(f"  ✅ {u['username']}: {r['token'][:40]}...")

# ── Step 7: 印出測試指令 ────────────────────────────────────────────────
print("\n" + "="*60)
print("  測試指令（複製貼上到終端機執行）")
print("="*60)

admin_tok = ADMIN_TOKEN[:60] + "..."
officer_tok = tokens.get("officer_a", "")[:60] + "..."

print(f"""
# ── 認證 ──────────────────────────────────────────────────
# 取得 JWT
curl -X POST {BASE}/api/v1/auth/login \\
  -H "Content-Type: application/json" \\
  -d '{{"username":"admin","password":"admin"}}'

# ── 設備狀態 ───────────────────────────────────────────────
curl "{BASE}/api/v1/devices/status" \\
  -H "Authorization: Bearer {ADMIN_TOKEN}"

# ── 查詢設備清單 ────────────────────────────────────────────
curl "{BASE}/api/v1/mapping/devices/officer_a" \\
  -H "Authorization: Bearer {ADMIN_TOKEN}"

# ── 歷史語音 ───────────────────────────────────────────────
START={( now - timedelta(days=1)).strftime('%Y-%m-%dT00:00:00')}
END={now.strftime('%Y-%m-%dT23:59:59')}

curl "{BASE}/api/v1/history/TEST_DEV_001/audio?start_time=$START&end_time=$END" \\
  -H "Authorization: Bearer {ADMIN_TOKEN}"

# ── 歷史 GPS（目前無模擬資料，回傳空陣列）──────────────────
curl "{BASE}/api/v1/history/TEST_DEV_001/gps?start_time=$START&end_time=$END" \\
  -H "Authorization: Bearer {ADMIN_TOKEN}"

# ── 即時串流資訊 ────────────────────────────────────────────
curl "{BASE}/api/v1/live/TEST_DEV_001/stream" \\
  -H "Authorization: Bearer {ADMIN_TOKEN}"

# ── MQTT 訂閱資訊 ───────────────────────────────────────────
curl "{BASE}/api/v1/live/TEST_DEV_001/subscribe" \\
  -H "Authorization: Bearer {ADMIN_TOKEN}"

# ── 即時語音 WebSocket（需要 wscat 或 websocat）────────────
# 安裝：npm install -g wscat
wscat -c "ws://{BASE.replace('http://','')}/api/v1/live/TEST_DEV_001/audio/ws?token={ADMIN_TOKEN}"
""")

print("="*60)
print("  ✅ 測試資料準備完成！")
print(f"  🌐 開啟瀏覽器：{BASE}")
print(f"  📹 NVR Viewer：{BASE}/nvr")
print("="*60 + "\n")
