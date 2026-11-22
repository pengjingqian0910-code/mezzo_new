"""檢查 9：瀏覽器自動化（Playwright，無頭 Chromium）。
啟動 `python main.py`（全新資料庫），打開首頁 → 用預設 admin/admin 登入 → 依序點 9 個分頁，
記錄每一步的：頁面 JS 例外、Console 錯誤、本站請求失敗、本站 HTTP 4xx/5xx。

為了不碰到實際設備，伺服器啟動時 NVR / MQTT 位址會指到 127.0.0.1（連線會直接失敗，拆分前後一致）。
外部 CDN（Vue、Cesium…）照常從網路載入，需要網路。
需要裝 playwright 的 Python 來執行這支（`pip install playwright` + `python -m playwright install chromium`）。

用法：python browser_check.py <app 目錄複本> <啟動伺服器用的 python> <server log 檔>
"""
import os, re, sys, time, subprocess, urllib.request

app_dir, server_py, log_path = sys.argv[1], sys.argv[2], sys.argv[3]
PORT = 8765
BASE = f"http://127.0.0.1:{PORT}"
TABS = ["電子地圖", "警戒區設定", "狀態總覽", "影像監控", "軌跡與影像回放", "語音對講", "後台與個人設定", "社群媒體", "NVR 監控"]

env = dict(os.environ, PORT=str(PORT), PYTHONIOENCODING="utf-8", TAK_TCP_PORT="18087",
           NVR_HOST="127.0.0.1", MQTT_BROKER_HOST="127.0.0.1", MQTT_BROKER_PORT="1")
for f in ("mezzo.db", ".env"):
    p = os.path.join(app_dir, f)
    if os.path.exists(p):
        os.remove(p)
log = open(log_path, "w", encoding="utf-8")
srv = subprocess.Popen([server_py, "main.py"], cwd=app_dir, env=env, stdout=log, stderr=subprocess.STDOUT)


def norm(s):
    s = s.replace(BASE, "<APP>").replace(f"127.0.0.1:{PORT}", "<APP>")
    s = re.sub(r"\?[^\s'\")]*", "?…", s)                      # 去掉 query string（含 token / 時間）
    s = re.sub(r"\b[0-9a-f]{32,}\b", "<HEX>", s)
    return s.strip()[:300]


try:
    up = False
    for _ in range(60):
        try:
            urllib.request.urlopen(BASE + "/api/geofences", timeout=2); up = True; break
        except Exception:
            time.sleep(1)
    if not up:
        print("SERVER DID NOT START"); sys.exit(0)

    from playwright.sync_api import sync_playwright
    events = []

    def add(kind, text):
        events.append((kind, norm(text)))

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1600, "height": 900})
        page.on("pageerror", lambda e: add("pageerror", str(e)))
        page.on("console", lambda m: m.type == "error" and add("console.error", m.text))
        page.on("requestfailed", lambda r: r.url.startswith(BASE) and add("requestfailed", f"{r.method} {r.url} {r.failure}"))
        page.on("response", lambda r: r.url.startswith(BASE) and r.status >= 400 and add(f"http{r.status}", f"{r.request.method} {r.url}"))
        page.on("dialog", lambda d: d.dismiss())

        def step(name, action):
            events.clear()
            ok = True
            try:
                action()
            except Exception as e:
                ok = False
                add("step-failed", f"{type(e).__name__}: {str(e).splitlines()[0]}")
            page.wait_for_timeout(2500)
            print(f"[{name}] {'ok' if ok else 'FAILED'}")
            for k, t in sorted(set(events)):
                print(f"    {k}: {t}")

        step("開啟首頁", lambda: page.goto(BASE + "/", wait_until="load", timeout=90000))
        step("登入 admin/admin", lambda: (page.get_by_role("button", name="登入系統").click(),
                                          page.get_by_text("在線: admin").wait_for(timeout=20000)))
        for t in TABS:
            step(f"分頁：{t}", lambda t=t: page.locator("nav button", has_text=t).first.click(timeout=10000))
        step("NVR 獨立頁 /nvr", lambda: page.goto(BASE + "/nvr", wait_until="load", timeout=60000))
        browser.close()
finally:
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(srv.pid)], capture_output=True)
    else:
        srv.kill()
    log.close()
print("done")
