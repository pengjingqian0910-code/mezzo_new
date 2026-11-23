"""
拆模組驗證：一次跑完所有檢查，比對「基準 commit」與「目前工作區」的 mezzo_web_system。

用法（在 repo 任何位置都可以執行）：
  python mezzo_web_system/tools/refactor_check/run_checks.py \
      --python <venv 的 python.exe> --python <系統 python.exe> \
      [--base HEAD] [--live http://localhost:8000] [--db <資料庫檔>]

  --base    比對基準，預設 HEAD（= 上一個 commit）
  --python  每個 Python 各跑一輪（建議 venv〔WebRTC 停用〕與系統 Python〔WebRTC 啟用〕都跑）；
            沒給就只用執行這支腳本的 Python
  --live    額外對正在跑的伺服器發 GET（只讀，不寫資料）
  --db      檢查 5 真實資料用的資料庫，預設 mezzo_web_system/mezzo.db（只讀，會先複製一份）
  --keep    保留暫存目錄（除錯用）

做法：把基準 commit（git archive）與目前工作區各複製一份到暫存目錄，每個檢查都用全新的
資料庫在兩邊各跑一次再比對。不會動到工作區裡的 mezzo.db 與 .env。
檢查 4（實際啟動）會照常連線 MQTT broker，跟平常啟動一樣；其他測試的對外網路都被 _guard 擋下。
檢查 3 pyflakes、檢查 9 瀏覽器需要裝了 pyflakes / playwright 的 Python（從 --python 裡自動找）。
"""
import argparse, ast, io, json, os, re, shutil, subprocess, sys, tarfile, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(os.path.dirname(HERE))                       # mezzo_web_system
REPO = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=APP,
                      capture_output=True, text=True, check=True).stdout.strip()
APP_REL = os.path.relpath(APP, REPO).replace("\\", "/")
COPY_IGNORE = shutil.ignore_patterns("mezzo.db", ".env", "__pycache__", "*.pyc", "audio")
MODULE_TESTS = ["mqtt_flow", "ws_v1", "geofence_flow", "geofence_notify", "geofence_isolate", "geofence_reuse"]
CUSTOM_ENV_FILE = "JWT_EXPIRE_HOURS=7\nNVR_MEDIA_PATH=D:\\TestMedia\nAUDIO_BASE_PATH=static/audio_test\nTAK_TCP_PORT=9999\n"
CUSTOM_ENV_VARS = {"NVR_HOST": "9.9.9.9", "MQTT_BROKER_PORT": "1234"}

results = []   # (環境, 檢查, 狀態, 說明)


def record(env, name, status, detail=""):
    results.append((env, name, status, detail))
    print(f"  [{status}] {name}" + (f" — {detail}" if detail else ""))


def show_diff(a, b, limit=40):
    import difflib
    lines = list(difflib.unified_diff(a.splitlines(), b.splitlines(), "基準", "目前", lineterm="", n=0))
    for l in lines[:limit]:
        print("      " + l)
    if len(lines) > limit:
        print(f"      ...（還有 {len(lines) - limit} 行）")


def git(*args):
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


# ---------------------------------------------------------------- 準備兩份複本
def prepare(work, base):
    b, c = os.path.join(work, "base"), os.path.join(work, "cur")
    os.makedirs(b)
    tar = subprocess.run(["git", "archive", "--format=tar", f"{base}:{APP_REL}"], cwd=REPO,
                         capture_output=True, check=True).stdout
    tarfile.open(fileobj=io.BytesIO(tar)).extractall(b)
    shutil.copytree(APP, c, ignore=COPY_IGNORE)
    return b, c


def clean(d, env_file=False):
    for f in ("mezzo.db", ".env"):
        p = os.path.join(d, f)
        if os.path.exists(p):
            os.remove(p)
    if env_file:
        open(os.path.join(d, ".env"), "w", encoding="utf-8").write(CUSTOM_ENV_FILE)


def snapshot_db(src, dst):
    """用 sqlite backup API 一致地複製資料庫（來源以唯讀模式開啟，不會被修改）"""
    import sqlite3
    s = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    t = sqlite3.connect(dst)
    s.backup(t)
    t.close(); s.close()


def has_module(py, mod):
    return subprocess.run([py, "-c", f"import {mod}"], capture_output=True).returncode == 0


def run(py, script, d, *args, env_extra=None, env_file=False, db_copy=None):
    clean(d, env_file)
    if db_copy:
        shutil.copyfile(db_copy, os.path.join(d, "mezzo.db"))
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    for k in ["PORT", *CUSTOM_ENV_VARS]:          # 不讓外部環境變數影響比對
        env.pop(k, None)
    env.update(env_extra or {})
    r = subprocess.run([py, os.path.join(HERE, script), *args], cwd=d, env=env, capture_output=True,
                       text=True, encoding="utf-8", errors="replace", timeout=300)
    clean(d)
    return r.stdout + r.stderr


def compare(env, name, b_out, c_out, changed_status="FAIL"):
    if b_out == c_out:
        record(env, name, "PASS", "與基準相同")
    else:
        record(env, name, changed_status, "與基準不同，見下方差異")
        show_diff(b_out, c_out)


# ---------------------------------------------------------------- 檢查 0：函式/類別搬移比對
SKIP_DIRS = {"tools", "static", "js", "__pycache__", ".github"}


def py_files(d):
    """app 裡的 .py（含 core/、features/ 等子資料夾），不含工具、靜態檔與「拷貝」備份檔；路徑用 / 分隔"""
    out = []
    for root, dirs, files in os.walk(d):
        dirs[:] = [x for x in dirs if x not in SKIP_DIRS]
        for f in files:
            if f.endswith(".py") and "拷貝" not in f:
                out.append(os.path.relpath(os.path.join(root, f), d).replace("\\", "/"))
    return sorted(out)


def defs(path):
    try:
        tree = ast.parse(open(path, encoding="utf-8").read())
    except Exception:
        return {}
    out = {}
    def walk(node, prefix):
        for ch in ast.iter_child_nodes(node):
            if isinstance(ch, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                q = prefix + ch.name
                out[q] = ast.dump(ch)
                walk(ch, q + ".")
            else:
                walk(ch, prefix)
    walk(tree, "")
    return out


def check_moves(b, c):
    print("\n== 檢查 0：函式/類別搬移與修改（AST 比對，不含註解）==")
    B = {(f, q): v for f in py_files(b) for q, v in defs(os.path.join(b, f)).items()}
    C = {(f, q): v for f in py_files(c) for q, v in defs(os.path.join(c, f)).items()}
    c_by_name = {}
    for (f, q), v in C.items():
        c_by_name.setdefault(q.split(".")[-1], []).append((f, q, v))
    moved_same, review = [], []
    for (f, q), v in B.items():
        if (f, q) in C:
            if C[(f, q)] != v:
                review.append(f"修改   {f}: {q}")
            continue
        cands = c_by_name.get(q.split(".")[-1], [])
        same = [x for x in cands if x[2] == v]
        if same:
            moved_same.append(f"{f}:{q} → {same[0][0]}:{same[0][1]}")
        elif cands:
            review.append(f"搬移但內容不同  {f}:{q} → {cands[0][0]}:{cands[0][1]}")
        else:
            review.append(f"刪除   {f}: {q}")
    for (f, q) in C:
        if (f, q) not in B and not any(x for x in moved_same if x.endswith(f"→ {f}:{q}")):
            if not any(f"→ {f}:{q}" in r for r in review):
                review.append(f"新增   {f}: {q}")
    print(f"  逐字搬移（AST 相同）：{len(moved_same)} 個")
    for m in moved_same:
        print("     ", m)
    if review:
        record("共用", "檢查 0 函式/類別比對", "REVIEW", f"{len(review)} 項需要人工確認（修改/新增/刪除）")
        for r in review:
            print("     ", r)
    else:
        record("共用", "檢查 0 函式/類別比對", "PASS", "沒有修改、新增或刪除")


# ---------------------------------------------------------------- 檢查 3：pyflakes
def pyflakes_undefined(py, d):
    r = subprocess.run([py, "-m", "pyflakes", *py_files(d)], cwd=d, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if "No module named pyflakes" in r.stderr:
        return None
    return sorted(re.sub(r":\d+:\d+:?", ":", l) for l in r.stdout.splitlines() if "undefined name" in l)


# ---------------------------------------------------------------- 檢查 4：啟動日誌正規化
def norm_log(path, d):
    out = []
    for l in open(path, encoding="utf-8", errors="replace").read().splitlines():
        if "127.0.0.1:" in l or "Will watch for changes" in l or not l.strip():
            continue
        l = l.replace(d + os.sep, "<APP>" + os.sep)
        l = re.sub(r"\.py:\d+:", ".py:N:", l)
        l = re.sub(r"\[\d+\]", "[PID]", l)
        out.append(l)
    return "\n".join(out)


def main():
    try:
        sys.stdout.reconfigure(line_buffering=True)   # 輸出導到檔案時也即時寫出，跑的過程中看得到進度
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="HEAD")
    ap.add_argument("--python", action="append", dest="pythons")
    ap.add_argument("--live")
    ap.add_argument("--db", default=os.path.join(APP, "mezzo.db"))
    ap.add_argument("--keep", action="store_true")
    a = ap.parse_args()
    pythons = a.pythons or [sys.executable]
    flakes_py = next((p for p in pythons if has_module(p, "pyflakes")), None)
    browser_py = next((p for p in pythons if has_module(p, "playwright")), None)

    base_sha = git("rev-parse", "--short", a.base).stdout.strip()
    print(f"基準：{a.base} ({base_sha})　目前：工作區 {APP}")
    if len(pythons) < 2:
        print("提醒：只給了一個 Python。建議 venv 與系統 Python 都跑（WebRTC 停用 / 啟用兩條路）。")

    work = tempfile.mkdtemp(prefix="refactor_check_")
    try:
        b, c = prepare(work, a.base)

        print("\n== 檢查 7：git diff 範圍與空白 ==")
        print(git("diff", "--stat", a.base, "--", APP_REL).stdout.rstrip() or "  （已追蹤檔案沒有差異）")
        untracked = git("ls-files", "--others", "--exclude-standard", "--", APP_REL).stdout.split()
        if untracked:
            print("  未追蹤的新檔案：", *untracked, sep="\n    ")
        chk = git("diff", "--check", a.base, "--", APP_REL)
        record("共用", "檢查 7 git diff --check", "PASS" if chk.returncode == 0 else "FAIL",
               "沒有空白/換行問題" if chk.returncode == 0 else chk.stdout.strip()[:300])

        check_moves(b, c)

        print("\n== 檢查 3：pyflakes（靜態檢查，跟 Python 環境無關，只跑一次）==")
        if not flakes_py:
            record("共用", "檢查 3 pyflakes", "SKIP", "--python 裡沒有裝 pyflakes 的 Python（pip install pyflakes）")
        else:
            ub, uc = pyflakes_undefined(flakes_py, b), pyflakes_undefined(flakes_py, c)
            new = [x for x in uc if x not in ub]
            record("共用", "檢查 3 pyflakes", "PASS" if not new else "FAIL",
                   f"undefined name：基準 {len(ub)}、目前 {len(uc)}，新增 {len(new)}")
            for x in new:
                print("      ", x)

        db_snap = None
        if os.path.exists(a.db):
            db_snap = os.path.join(work, "realdb_snapshot.db")
            snapshot_db(a.db, db_snap)

        for py in pythons:
            ver = subprocess.run([py, "-c", "import sys,importlib.util as u;print(sys.version.split()[0],"
                                  "'aiortc' if u.find_spec('aiortc') else 'no-aiortc')"],
                                 capture_output=True, text=True).stdout.strip()
            tag = f"{os.path.basename(os.path.dirname(os.path.dirname(py))) or py} ({ver})"
            print(f"\n################ {py}  [{ver}] ################")

            print("== 檢查 1：路由與資料表快照 ==")
            outs = {}
            for d in (b, c):
                run(py, "snapshot.py", d, os.path.join(work, f"snap_{os.path.basename(d)}.json"))
                p = os.path.join(work, f"snap_{os.path.basename(d)}.json")
                outs[d] = open(p, encoding="utf-8").read() if os.path.exists(p) else "<snapshot 失敗>"
            compare(tag, "檢查 1 快照", outs[b], outs[c])

            print("== 檢查 10：模組重複載入 ==")
            mi = run(py, "module_identity.py", c)
            print("      " + "\n      ".join(mi.splitlines()))
            record(tag, "檢查 10 模組重複載入", "PASS" if "duplicates: none" in mi else "FAIL",
                   "同一個檔案沒有被載入成兩個模組" if "duplicates: none" in mi else "有檔案被載入兩次，見上方")

            print("== 檢查 2：打 API ==")
            compare(tag, "檢查 2 API 回應", run(py, "smoke.py", b), run(py, "smoke.py", c))

            print("== 檢查 4：python main.py 實際啟動 ==")
            logs, gets = {}, {}
            for d in (b, c):
                clean(d)
                lp = os.path.join(work, f"launch_{os.path.basename(d)}.log")
                out = subprocess.run([py, os.path.join(HERE, "launch_check.py"), d, lp], capture_output=True,
                                     text=True, encoding="utf-8", errors="replace", timeout=300).stdout
                clean(d)
                gets[d] = out
                logs[d] = norm_log(lp, d)
            started = "SERVER STARTED" in gets[c] and "error lines in log: 0" in gets[c]
            if not started:
                record(tag, "檢查 4 實際啟動", "FAIL", "目前版本沒有正常啟動")
                print(gets[c])
            else:
                compare(tag, "檢查 4 實際啟動（API 回應）", gets[b], gets[c])
                compare(tag, "檢查 4 實際啟動（啟動日誌）", logs[b], logs[c])

            print("== 檢查 5：設定值 ==")
            compare(tag, "檢查 5 設定值（預設）", run(py, "config_values.py", b), run(py, "config_values.py", c))
            compare(tag, "檢查 5 設定值（自訂 .env＋環境變數）",
                    run(py, "config_values.py", b, env_extra=CUSTOM_ENV_VARS, env_file=True),
                    run(py, "config_values.py", c, env_extra=CUSTOM_ENV_VARS, env_file=True))

            print("== 檢查 5：模組專屬測試 ==")
            for t in MODULE_TESTS:
                compare(tag, f"檢查 5 {t}", run(py, f"{t}.py", b), run(py, f"{t}.py", c), changed_status="CHANGED")

            print("== 檢查 5：真實資料庫複本（只印狀態碼/筆數/雜湊，不印資料內容）==")
            if not db_snap:
                record(tag, "檢查 5 realdb", "SKIP", f"找不到資料庫 {a.db}")
            else:
                rb = run(py, "realdb.py", b, db_copy=db_snap)
                rc_ = run(py, "realdb.py", c, db_copy=db_snap)
                print("      " + "\n      ".join(rc_.splitlines()[:3]) + "\n      …")
                compare(tag, "檢查 5 realdb", rb, rc_, changed_status="CHANGED")

            print("== 檢查 9：瀏覽器自動化 ==")
            if not browser_py:
                record(tag, "檢查 9 瀏覽器", "SKIP", "--python 裡沒有裝 playwright 的 Python")
            else:
                outs = {}
                for d in (b, c):
                    clean(d)
                    outs[d] = subprocess.run([browser_py, os.path.join(HERE, "browser_check.py"), d, py,
                                              os.path.join(work, f"browser_{os.path.basename(d)}.log")],
                                             capture_output=True, text=True, encoding="utf-8", errors="replace",
                                             timeout=600, env=dict(os.environ, PYTHONIOENCODING="utf-8")).stdout
                    clean(d)
                if "SERVER DID NOT START" in outs[c] or "done" not in outs[c]:
                    record(tag, "檢查 9 瀏覽器", "FAIL", "目前版本沒有跑完")
                    print(outs[c][-2000:])
                else:
                    compare(tag, "檢查 9 瀏覽器（各步驟的錯誤）", outs[b], outs[c])

                print("== 檢查 9b：警戒區繪製流程（截圖像素判斷頂點）==")
                outs = {}
                for d in (b, c):
                    clean(d)
                    shots = os.path.join(work, f"geofence_draw_{os.path.basename(d)}_{os.path.basename(os.path.dirname(os.path.dirname(py)))}")
                    outs[d] = subprocess.run([browser_py, os.path.join(HERE, "browser_geofence_draw.py"), d, py, shots],
                                             capture_output=True, text=True, encoding="utf-8", errors="replace",
                                             timeout=600, env=dict(os.environ, PYTHONIOENCODING="utf-8")).stdout
                    clean(d)
                print("      " + "\n      ".join(outs[c].splitlines()))
                if "done" not in outs[c]:
                    record(tag, "檢查 9b 警戒區繪製", "FAIL", "目前版本沒有跑完")
                else:
                    compare(tag, "檢查 9b 警戒區繪製", outs[b], outs[c], changed_status="CHANGED")

            print("== 檢查 6：前端 API 路徑 ==")
            miss = {}
            for d in (b, c):
                snap = os.path.join(work, f"snap_{os.path.basename(d)}.json")
                run(py, "snapshot.py", d, snap)
                miss[d] = set(l for l in run(py, "frontend_routes.py", d, snap).splitlines() if l and not l.startswith("#"))
            new_miss = miss[c] - miss[b]
            record(tag, "檢查 6 前端路徑", "PASS" if not new_miss else "FAIL",
                   f"找不到路由：基準 {sorted(miss[b])}、目前 {sorted(miss[c])}"
                   + (f"，新增 {sorted(new_miss)}" if new_miss else ""))

        if a.live:
            import urllib.request
            print(f"\n== 檢查 8：正在跑的伺服器 {a.live}（只 GET）==")
            bad = []
            for p in ["/", "/api/geofences", "/api/devices", "/api/webrtc/status", "/api/social/stt_status"]:
                try:
                    with urllib.request.urlopen(a.live.rstrip("/") + p, timeout=8) as r:
                        print(f"  {p:26} {r.status}")
                        if r.status != 200:
                            bad.append(p)
                except Exception as e:
                    print(f"  {p:26} ERROR {e}"); bad.append(p)
            record("live", "檢查 8 正在跑的伺服器", "PASS" if not bad else "FAIL", f"失敗：{bad}" if bad else "全部 200")
    finally:
        if a.keep:
            print(f"\n暫存目錄保留在：{work}")
        else:
            shutil.rmtree(work, ignore_errors=True)

    print("\n================ 總結 ================")
    w = max(len(r[1]) for r in results)
    for env, name, status, detail in results:
        print(f"[{status:7}] {name.ljust(w)}  {env}")
    print("\nPASS=與基準相同　CHANGED=行為有變（預期中的修正才可以接受，請看差異）"
          "　REVIEW=需要人工確認　SKIP=沒跑到　FAIL=有問題")
    print("注意：檢查 0 只比對函式/類別；模組層級的程式（import、變數）請另外用 git diff 確認。"
          "\n　　　沒有涵蓋瀏覽器裡的實際操作。")
    return 1 if any(r[2] == "FAIL" for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
