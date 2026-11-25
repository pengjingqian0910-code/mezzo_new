"""檢查 11：扮演外部合作廠商，透過真的 HTTP / WebSocket 連線使用 v1 API（JWT）。
伺服器用 `uvicorn main:app` 啟動（沒有 reload，跟 Docker 部署的 entrypoint.sh 同一種啟動方式）。

測試內容：
- 登入：錯誤帳密、admin 拿 JWT（檢查 token_type / expires_in / payload 的 sub、role、有效時間）
- admin 建帳號、建設備（PUT nvr_channel）、綁定設備
- 廠商帳號（operator）用 JWT 打每個 v1 API：有權限的設備、沒權限的設備、管理員 API（應 403）
- 不正常的 token：沒帶、Basic、空的、亂寫、竄改 payload、用錯的 secret 簽、已過期、alg=none、缺 sub
- Web UI 的 session token 也能用在 v1；登出後不能再用
- v1 語音 WebSocket：JWT、session token、沒權限的設備、壞 token、過期 token
- 解除綁定後，廠商就不能再存取那台設備
- 伺服器重新啟動後：JWT 還能用（不存在記憶體），session token 失效

伺服器啟動時 NVR / MQTT 指到 127.0.0.1，不碰實際設備；JWT_SECRET 設成固定的測試值，用來產生過期 / 竄改的 token。
輸出會遮掉 token、時間戳記、含帳密的網址。

用法：
  本機：python vendor_jwt.py local <app 目錄複本> <啟動伺服器用的 python>
  只跑用戶端（例如對 Docker 容器）：python vendor_jwt.py client <base_url> <1|2> <狀態檔.json>
     第 1 階段：完整測試並把 token 存進狀態檔；重新啟動伺服器後跑第 2 階段：檢查 JWT / session token 是否還有效。
"""
import os, re, sys, json, time, hmac, base64, hashlib, subprocess, urllib.request, urllib.error, urllib.parse

# 不 import _guard：_guard 會擋掉「打本機 HTTP」（給在同一個程序裡 import main 的測試用），
# 這支就是要透過真的 HTTP 打伺服器。改成在下面檢查目標一定是 127.0.0.1 / localhost。

TEST_SECRET = "refactor-check-jwt-secret"
PORT = 8767
DROP = {"timestamp", "token", "iat", "exp", "last_heartbeat", "created_at"}
MASK = {"mjpeg_url", "rtsp_url", "url", "download_url", "stream_url"}


# ---------------- 輸出整理 ----------------
def clean(o):
    if isinstance(o, dict):
        return {k: ("<有>" if (k in MASK and v) else clean(v)) for k, v in o.items() if k not in DROP}
    if isinstance(o, list):
        return [clean(x) for x in o]
    return o


def http(base, method, path, body=None, token=None, raw_auth=None):
    headers = {"Content-Type": "application/json"}
    if raw_auth is not None:
        headers["Authorization"] = raw_auth
    elif token:
        headers["Authorization"] = "Bearer " + token
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            status, text = r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        status, text = e.code, e.read().decode("utf-8", "replace")
    except Exception as e:
        return 0, f"<連線錯誤 {type(e).__name__}>"
    try:
        return status, json.loads(text)
    except Exception:
        return status, text[:120]


def show(label, res):
    status, body = res
    s = json.dumps(clean(body), ensure_ascii=False) if not isinstance(body, str) else body
    print(f"{label:44} {status} {s[:260]}")
    return body


# ---------------- 自己產生 JWT（過期、竄改、alg=none） ----------------
def b64(d):
    return base64.urlsafe_b64encode(d).rstrip(b"=").decode()


def make_jwt(payload, secret=TEST_SECRET, alg="HS256"):
    head = b64(json.dumps({"alg": alg, "typ": "JWT"}).encode())
    body = b64(json.dumps(payload).encode())
    if alg == "none":
        return f"{head}.{body}."
    sig = hmac.new(secret.encode(), f"{head}.{body}".encode(), hashlib.sha256).digest()
    return f"{head}.{body}.{b64(sig)}"


def jwt_payload(tok):
    p = tok.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(p + "=" * (-len(p) % 4)))


# ---------------- WebSocket ----------------
def ws_try(base, label, path):
    from websockets.sync.client import connect
    url = "ws" + base[4:] + path
    try:
        with connect(url, open_timeout=10, close_timeout=2) as w:
            try:
                msg = w.recv(timeout=5)
                try:
                    msg = json.dumps(clean(json.loads(msg)), ensure_ascii=False)
                except Exception:
                    msg = repr(msg)[:80]
                print(f"ws {label:41} 連上，第一則：{msg[:200]}")
            except Exception as e:
                code = getattr(getattr(e, "rcvd", None), "code", None)
                print(f"ws {label:41} 連上後被關閉 {type(e).__name__} code={code}")
    except Exception as e:
        status = getattr(getattr(e, "response", None), "status_code", None)
        print(f"ws {label:41} 連線被拒 {type(e).__name__} status={status}")


# ---------------- 第 1 階段：完整測試 ----------------
def phase1(base, state_path):
    print("== 登入 ==")
    show("v1 login 錯誤帳密", http(base, "POST", "/api/v1/auth/login", {"username": "admin", "password": "x"}))
    show("v1 login 沒帶帳密", http(base, "POST", "/api/v1/auth/login", {}))
    r = show("v1 login admin", http(base, "POST", "/api/v1/auth/login", {"username": "admin", "password": "admin"}))
    admin = r["token"]
    p = jwt_payload(admin)
    h, pl, sig = admin.split(".")
    ok = b64(hmac.new(TEST_SECRET.encode(), f"{h}.{pl}".encode(), hashlib.sha256).digest()) == sig
    print("admin JWT payload:", {k: p[k] for k in ("sub", "role")}, "有效秒數:", p["exp"] - p["iat"],
          "| header:", json.loads(base64.urlsafe_b64decode(h + "=" * (-len(h) % 4))),
          "| 用測試 secret 驗得過:", ok)

    print("== admin 準備資料 ==")
    show("建立廠商帳號 vendor1", http(base, "POST", "/api/v1/users",
                                 {"username": "vendor1", "password": "v1pass", "role": "operator"}, admin))
    show("建立設備 DEV1（nvr_channel）", http(base, "PUT", "/api/v1/devices/DEV1/nvr_channel",
                                         {"channel": 0, "name": "巡邏車1"}, admin))
    show("建立設備 DEV2（nvr_channel）", http(base, "PUT", "/api/v1/devices/DEV2/nvr_channel",
                                         {"channel": 1, "name": "巡邏車2"}, admin))
    show("nvr_channel 沒給 channel", http(base, "PUT", "/api/v1/devices/DEV1/nvr_channel", {}, admin))
    show("綁定 DEV1 → vendor1", http(base, "POST", "/api/v1/mapping/assign",
                                    {"userId": "vendor1", "deviceId": "DEV1"}, admin))

    print("== 廠商用 JWT ==")
    r = show("v1 login vendor1", http(base, "POST", "/api/v1/auth/login", {"username": "vendor1", "password": "v1pass"}))
    vendor = r["token"]
    print("vendor JWT payload:", {k: jwt_payload(vendor)[k] for k in ("sub", "role")})
    T = vendor
    show("devices/status", http(base, "GET", "/api/v1/devices/status", token=T))
    show("mapping/devices/vendor1（自己）", http(base, "GET", "/api/v1/mapping/devices/vendor1", token=T))
    show("mapping/devices/admin（別人）", http(base, "GET", "/api/v1/mapping/devices/admin", token=T))
    for dev in ("DEV1", "DEV2"):
        show(f"live/{dev}/subscribe", http(base, "GET", f"/api/v1/live/{dev}/subscribe", token=T))
        show(f"live/{dev}/stream", http(base, "GET", f"/api/v1/live/{dev}/stream", token=T))
        show(f"live/{dev}/webrtc/offer", http(base, "POST", f"/api/v1/live/{dev}/webrtc/offer",
                                              {"sdp": "v=0", "type": "offer"}, T))
        show(f"history/{dev}/gps", http(base, "GET",
                                        f"/api/v1/history/{dev}/gps?start_time=2026-01-01&end_time=2026-12-31", token=T))
        show(f"history/{dev}/audio", http(base, "GET", f"/api/v1/history/{dev}/audio", token=T))
        show(f"history/{dev}/videos", http(base, "GET",
                                           f"/api/v1/history/{dev}/videos?start_time=2026-01-01&end_time=2026-01-02", token=T))
        show(f"history/{dev}/videos/download", http(base, "GET", f"/api/v1/history/{dev}/videos/download?tag=x", token=T))
        show(f"devices/{dev}/nvr_channel GET", http(base, "GET", f"/api/v1/devices/{dev}/nvr_channel", token=T))
    show("devices/NOPE/nvr_channel GET", http(base, "GET", "/api/v1/devices/NOPE/nvr_channel", token=T))
    show("管理員 API：建立帳號", http(base, "POST", "/api/v1/users", {"username": "x", "password": "y"}, T))
    show("管理員 API：綁定", http(base, "POST", "/api/v1/mapping/assign", {"userId": "vendor1", "deviceId": "DEV2"}, T))
    show("管理員 API：解除綁定", http(base, "DELETE", "/api/v1/mapping/assign", {"userId": "vendor1", "deviceId": "DEV1"}, T))
    show("管理員 API：設定 nvr_channel", http(base, "PUT", "/api/v1/devices/DEV1/nvr_channel", {"channel": 3}, T))

    print("== 不正常的 token（打 devices/status） ==")
    now = int(time.time())
    bad = {
        "沒帶 Authorization": dict(raw_auth=None, token=None),
        "Basic 認證": dict(raw_auth="Basic YWRtaW46YWRtaW4="),
        "Bearer 空的": dict(raw_auth="Bearer "),
        "亂寫": dict(token="not-a-token"),
        "三段式但亂寫": dict(token="a.b.c"),
        "竄改 payload（role 改 admin）": dict(token=admin.split(".")[0] + "." +
                                          b64(json.dumps(dict(jwt_payload(vendor), role="admin")).encode()) + "." +
                                          vendor.split(".")[2]),
        "用錯的 secret 簽": dict(token=make_jwt({"sub": "admin", "role": "admin", "iat": now, "exp": now + 3600},
                                            secret="wrong")),
        "已過期（secret 正確）": dict(token=make_jwt({"sub": "admin", "role": "admin", "iat": now - 7200,
                                                "exp": now - 3600})),
        "alg=none": dict(token=make_jwt({"sub": "admin", "role": "admin", "iat": now, "exp": now + 3600}, alg="none")),
        "缺 sub（secret 正確）": dict(token=make_jwt({"role": "admin", "iat": now, "exp": now + 3600})),
    }
    for label, kw in bad.items():
        show(label, http(base, "GET", "/api/v1/devices/status", **kw))
    forged_admin = make_jwt({"sub": "vendor1", "role": "admin", "iat": now, "exp": now + 3600})
    show("自簽 role=admin（secret 正確）建帳號", http(base, "POST", "/api/v1/users",
                                                {"username": "forged", "password": "y"}, forged_admin))

    print("== Web UI session token ==")
    st = http(base, "POST", "/api/login", {"username": "vendor1", "password": "v1pass"})[1]["token"]
    show("session token 打 v1 devices/status", http(base, "GET", "/api/v1/devices/status", token=st))
    st_admin = http(base, "POST", "/api/login", {"username": "admin", "password": "admin"})[1]["token"]
    st_logout = http(base, "POST", "/api/login", {"username": "vendor1", "password": "v1pass"})[1]["token"]
    show("登出", http(base, "POST", "/api/logout", token=st_logout))
    show("登出後 session token 打 v1", http(base, "GET", "/api/v1/devices/status", token=st_logout))
    show("JWT 打 Web UI API /api/users", http(base, "GET", "/api/users", token=admin))

    print("== v1 語音 WebSocket ==")
    expired = make_jwt({"sub": "vendor1", "role": "operator", "iat": now - 7200, "exp": now - 3600})
    ws_try(base, "JWT DEV1", f"/api/v1/live/DEV1/audio/ws?token={vendor}")
    ws_try(base, "session token DEV1", f"/api/v1/live/DEV1/audio/ws?token={st}")
    ws_try(base, "JWT DEV2（沒權限）", f"/api/v1/live/DEV2/audio/ws?token={vendor}")
    ws_try(base, "沒帶 token", "/api/v1/live/DEV1/audio/ws")
    ws_try(base, "壞 token", "/api/v1/live/DEV1/audio/ws?token=a.b.c")
    ws_try(base, "過期 JWT", f"/api/v1/live/DEV1/audio/ws?token={expired}")

    print("== 解除綁定後 ==")
    show("admin 解除綁定 DEV1", http(base, "DELETE", "/api/v1/mapping/assign",
                                   {"userId": "vendor1", "deviceId": "DEV1"}, admin))
    show("vendor1 live/DEV1/subscribe", http(base, "GET", "/api/v1/live/DEV1/subscribe", token=vendor))
    show("vendor1 devices/status", http(base, "GET", "/api/v1/devices/status", token=vendor))

    json.dump({"admin_jwt": admin, "vendor_jwt": vendor, "session": st, "session_admin": st_admin},
              open(state_path, "w", encoding="utf-8"))


# ---------------- 第 2 階段：伺服器重新啟動後 ----------------
def phase2(base, state_path):
    s = json.load(open(state_path, encoding="utf-8"))
    print("== 伺服器重新啟動後 ==")
    show("重啟前的 admin JWT", http(base, "GET", "/api/v1/devices/status", token=s["admin_jwt"]))
    show("重啟前的 vendor JWT", http(base, "GET", "/api/v1/devices/status", token=s["vendor_jwt"]))
    show("重啟前的 session token 打 v1", http(base, "GET", "/api/v1/devices/status", token=s["session"]))
    show("重啟前的 admin session 打 /api/users", http(base, "GET", "/api/users", token=s["session_admin"]))
    show("重新登入 v1", http(base, "POST", "/api/v1/auth/login", {"username": "vendor1", "password": "v1pass"}))


# ---------------- 本機模式：自己用 uvicorn main:app 啟動 ----------------
def start_server(app_dir, server_py, log):
    env = dict(os.environ, PYTHONIOENCODING="utf-8", JWT_SECRET=TEST_SECRET, TAK_TCP_PORT="18089",
               NVR_HOST="127.0.0.1", MQTT_BROKER_HOST="127.0.0.1", MQTT_BROKER_PORT="1")
    return subprocess.Popen([server_py, "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", str(PORT)],
                            cwd=app_dir, env=env, stdout=log, stderr=subprocess.STDOUT)


def stop_server(p):
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(p.pid)], capture_output=True)
    else:
        p.kill()
    p.wait()


def wait_up(base):
    for _ in range(60):
        try:
            # 原本：urllib.request.urlopen(base + "/api/geofences", timeout=2)
            # 原本沒讀回應內容就關閉連線：Windows 上關閉時若還有沒讀的資料會送出 RST（強制中斷），
            # 伺服器端 asyncio（proactor_events.py _call_connection_lost 的 shutdown）就會隨機印出
            # ConnectionResetError [WinError 10054]，讓檢查 11 的「伺服器日誌錯誤行數」隨機不同。
            # 改成讀完回應再用 with 關閉，連線正常結束。
            with urllib.request.urlopen(base + "/api/geofences", timeout=2) as r:
                r.read()
            return True
        except Exception:
            time.sleep(1)
    return False


def local(app_dir, server_py):
    import tempfile
    base = f"http://127.0.0.1:{PORT}"
    for f in ("mezzo.db", ".env"):
        if os.path.exists(os.path.join(app_dir, f)):
            os.remove(os.path.join(app_dir, f))
    tmp = tempfile.mkdtemp(prefix="vendor_jwt_")          # 狀態檔與伺服器日誌放暫存資料夾，不留在 app 複本裡
    state, log_path = os.path.join(tmp, "state.json"), os.path.join(tmp, "server.log")
    log = open(log_path, "w", encoding="utf-8")
    srv = start_server(app_dir, server_py, log)
    try:
        if not wait_up(base):
            print("SERVER DID NOT START"); return
        phase1(base, state)
        stop_server(srv)
        srv = start_server(app_dir, server_py, log)
        if not wait_up(base):
            print("SERVER DID NOT RESTART"); return
        phase2(base, state)
    finally:
        stop_server(srv)
        log.close()
    text = open(log_path, encoding="utf-8").read()
    errs = [l for l in text.splitlines() if "Traceback" in l or ("Error" in l and "WebRTC" not in l
            and "aiohttp" not in l and "MQTT" not in l)]
    print("伺服器日誌錯誤行數:", len(errs))
    for l in errs[:10]:
        print("  ", re.sub(r"127\.0\.0\.1:\d+", "127.0.0.1:*", l)[:200])   # 用戶端 port 每次不同，遮掉
    print("done")


if __name__ == "__main__":
    mode = sys.argv[1]
    if mode == "local":
        local(sys.argv[2], sys.argv[3])
    elif mode == "client":
        host = urllib.parse.urlparse(sys.argv[2]).hostname
        if host not in ("127.0.0.1", "localhost"):
            sys.exit(f"只能對本機測試，目前是 {host}")
        (phase1 if sys.argv[3] == "1" else phase2)(sys.argv[2].rstrip("/"), sys.argv[4])
    else:
        sys.exit("mode 必須是 local 或 client")
