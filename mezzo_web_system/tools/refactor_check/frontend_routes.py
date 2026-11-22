"""檢查 6：掃描前端（static/js/*.js、index_3D.html、nvr_viewer.html）裡呼叫的 API 路徑，
列出後端快照裡找不到對應路由的路徑（一行一個）。
已知誤判：用字串拼接組出的 URL（例如 '/api/webrtc/' + id）只抓得到前半段 → /api/webrtc。
用法：cd <app 目錄複本> && python frontend_routes.py <snapshot.json>
"""
import json, re, glob, sys
from starlette.routing import compile_path

routes = json.load(open(sys.argv[1], encoding="utf-8"))["routes"]
patterns = [compile_path(r["path"])[0] for r in routes if r["path"].startswith("/")]
files = sorted(glob.glob("static/js/*.js")) + ["index_3D.html", "nvr_viewer.html"]
paths = set()
for f in files:
    try:
        src = open(f, encoding="utf-8").read()
    except FileNotFoundError:
        continue
    for m in re.finditer(r"""[`'"](?:\$\{[^}]+\})?(/(?:api|ws|view|nvr)[^`'"\s?#]*)""", src):
        paths.add(re.sub(r"\$\{[^}]+\}", "X", m.group(1)).rstrip("/") or "/")
print(f"# scanned paths: {len(paths)}")
for p in sorted(paths):
    if not any(rx.match(p) for rx in patterns):
        print(p)
