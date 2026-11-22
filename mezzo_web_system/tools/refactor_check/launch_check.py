"""檢查 4：照使用者的方式用 `python main.py`（reload 模式）實際啟動，等服務起來後打幾個 API，
最後把整個程序樹關掉。使用 port 8765 / TAK 18087，不會跟正在跑的 8000 衝突。
注意：startup 會照常連線 MQTT broker（跟平常啟動一樣），資料只寫進複本裡的資料庫。
用法：python launch_check.py <app 目錄複本> <log 檔>
"""
import os, sys, time, subprocess, urllib.request

app_dir, log_path = sys.argv[1], sys.argv[2]
env = dict(os.environ, PORT="8765", PYTHONIOENCODING="utf-8", TAK_TCP_PORT="18087")
log = open(log_path, "w", encoding="utf-8")
p = subprocess.Popen([sys.executable, "main.py"], cwd=app_dir, env=env, stdout=log, stderr=subprocess.STDOUT)


def get(path):
    with urllib.request.urlopen("http://127.0.0.1:8765" + path, timeout=3) as r:
        return r.status, r.read().decode("utf-8")[:60].replace("\n", " ")


ok = False
try:
    deadline = time.time() + 40
    while time.time() < deadline:
        try:
            get("/api/geofences"); ok = True; break
        except Exception:
            time.sleep(1)
    if ok:
        for path in ["/api/geofences", "/api/devices", "/api/sos/records", "/api/ptt/records",
                     "/api/webrtc/status", "/api/social/stt_status", "/"]:
            try:
                print("GET", path, *get(path))
            except Exception as e:
                print("GET", path, "ERROR", e)
finally:
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(p.pid)], capture_output=True)
    else:
        p.kill()
    log.close()

text = open(log_path, encoding="utf-8").read()
errors = [l for l in text.splitlines() if "Error" in l and "WebRTC" not in l and "aiohttp" not in l]
print("SERVER STARTED" if ok else "SERVER DID NOT START")
print("error lines in log:", len(errors))
for l in errors[:10]:
    print("  ", l)
