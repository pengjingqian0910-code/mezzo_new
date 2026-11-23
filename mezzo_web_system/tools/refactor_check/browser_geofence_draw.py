"""檢查 9b：在瀏覽器裡實際操作「警戒區設定」頁的繪製流程，並自動判斷地圖上的頂點有沒有畫出來。
流程：登入 → 警戒區設定 → 開始繪製 → 在地圖點 4 個點 → 右鍵 → 輸入名稱 → 重新整理頁面 → 停用 → 刪除。
每一步截圖，並讀取 4 個頂點位置的像素顏色，判斷是 red（紅點）/ gray（灰點）/ none（沒有點）。
Cesium 地圖物件包在元件內部，程式讀不到，所以用截圖像素判斷；像素是用 Playwright 的瀏覽器讀的，不需要另外裝 Pillow。

預期（f9ae0d3 修正後）：儲存後 red、重新整理後 red、停用後 gray、刪除後 none。
（修正前 1dd683a 實測：儲存後 red〔殘留的暫時頂點〕、重新整理後 none、停用後 none、刪除後 none）

伺服器啟動時 NVR / MQTT 指到 127.0.0.1，不碰實際設備；地圖圖磚（Google）照常從網路載入，需要網路。
用法：python browser_geofence_draw.py <app 目錄複本> <啟動伺服器用的 python> <截圖輸出資料夾>
"""
import os, sys, time, json, base64, subprocess, urllib.request

app_dir, server_py, shot_dir = sys.argv[1], sys.argv[2], sys.argv[3]
os.makedirs(shot_dir, exist_ok=True)
PORT = 8766
BASE = f"http://127.0.0.1:{PORT}"
env = dict(os.environ, PORT=str(PORT), PYTHONIOENCODING="utf-8", TAK_TCP_PORT="18088",
           NVR_HOST="127.0.0.1", MQTT_BROKER_HOST="127.0.0.1", MQTT_BROKER_PORT="1")
for f in ("mezzo.db", ".env"):
    p = os.path.join(app_dir, f)
    if os.path.exists(p):
        os.remove(p)
log = open(os.path.join(shot_dir, "server.log"), "w", encoding="utf-8")
srv = subprocess.Popen([server_py, "main.py"], cwd=app_dir, env=env, stdout=log, stderr=subprocess.STDOUT)

# 讀像素：把截圖畫到一個空白網頁的 canvas 上，再用 getImageData 取每個頂點周圍 5x5 的顏色
READ_PIXELS_JS = """async ([b64, pts]) => {
  const img = new Image(); img.src = 'data:image/png;base64,' + b64; await img.decode();
  const c = document.createElement('canvas'); c.width = img.width; c.height = img.height;
  const g = c.getContext('2d'); g.drawImage(img, 0, 0);
  return pts.map(([x, y]) => Array.from(g.getImageData(Math.round(x) - 2, Math.round(y) - 2, 5, 5).data));
}"""


def classify(rgba):
    px = [rgba[i:i + 3] for i in range(0, len(rgba), 4)]
    if any(r > 200 and g < 60 and b < 60 for r, g, b in px):
        return "red"
    if any(110 <= r <= 145 and abs(r - g) < 8 and abs(g - b) < 8 for r, g, b in px):
        return "gray"
    return "none"


def api_fences():
    return [(f["name"], f["is_enabled"], len(json.loads(f["points"])))
            for f in json.loads(urllib.request.urlopen(BASE + "/api/geofences").read())]


try:
    for _ in range(60):
        try:
            urllib.request.urlopen(BASE + "/api/geofences", timeout=2); break
        except Exception:
            time.sleep(1)
    else:
        print("SERVER DID NOT START"); sys.exit(0)

    from playwright.sync_api import sync_playwright
    errors = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1400, "height": 800})
        reader = browser.new_page()
        page.on("pageerror", lambda e: errors.append(f"pageerror: {str(e)[:160]}"))
        page.on("dialog", lambda d: d.accept("測試區A") if d.type == "prompt" else d.accept())

        def login_and_open_tab():
            page.get_by_role("button", name="登入系統").click()
            page.get_by_text("在線: admin").wait_for(timeout=20000)
            page.locator("nav button", has_text="警戒區設定").first.click()
            page.wait_for_timeout(6000)                      # 等地圖飛到預設位置、圖磚載入

        def check(step, vertices):
            png = page.screenshot(path=os.path.join(shot_dir, f"{step}.png"))
            data = reader.evaluate(READ_PIXELS_JS, [base64.b64encode(png).decode(), vertices])
            print(f"{step:16} 頂點: {[classify(d) for d in data]}")

        page.goto(BASE + "/", wait_until="load", timeout=90000)
        login_and_open_tab()
        box = page.locator("#drawContainer canvas").first.bounding_box()
        cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
        vertices = [(cx - 150, cy - 100), (cx + 150, cy - 100), (cx + 150, cy + 100), (cx - 150, cy + 100)]

        check("0_開始前", vertices)
        page.get_by_role("button", name="開始繪製新警戒區").click()
        for x, y in vertices:
            page.mouse.click(x, y); page.wait_for_timeout(400)
        check("1_繪製中", vertices)
        page.mouse.click(cx, cy, button="right"); page.wait_for_timeout(3000)
        print("儲存後 API:", api_fences())
        check("2_儲存後", vertices)

        page.reload(wait_until="load", timeout=90000)
        login_and_open_tab()
        check("3_重新整理後", vertices)

        page.get_by_role("button", name="啟用中").first.click(); page.wait_for_timeout(2500)
        print("停用後 API:", api_fences())
        check("4_停用後", vertices)

        page.get_by_role("button", name="刪除").first.click(); page.wait_for_timeout(2500)
        print("刪除後 API:", api_fences())
        check("5_刪除後", vertices)
        browser.close()
    print("page errors:", sorted(set(errors)))
finally:
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(srv.pid)], capture_output=True)
    else:
        srv.kill()
    log.close()
print("done")
