"""檢查 10：同一個檔案有沒有被當成兩個不同的模組載入。
例如 database.py 搬進 core/ 之後，如果有地方還寫 `import database`、有地方寫 `from core import database`，
同一個檔案會被載入兩次，變成兩份 Base / SessionLocal，資料表註冊與連線狀態就會對不起來。
（這裡只檢查 import main 時的情況；`python main.py` 的 __main__ / main 雙重執行是另一回事，由檢查 4 涵蓋）
用法：cd <app 目錄複本> && python module_identity.py      → 印出重複載入的檔案；沒有就印 none
"""
import sys, os, io, contextlib
import _guard                                      # noqa: E402  擋下所有對外網路
sys.path.insert(0, os.getcwd())
with contextlib.redirect_stdout(io.StringIO()):
    import main  # noqa: F401

root = os.path.abspath(os.getcwd())
by_file = {}
for name, mod in list(sys.modules.items()):
    f = getattr(mod, "__file__", None)
    if f and os.path.abspath(f).startswith(root):
        by_file.setdefault(os.path.relpath(os.path.abspath(f), root).replace("\\", "/"), []).append(name)
print("app modules:", sorted(n for names in by_file.values() for n in names))
dups = {f: sorted(n) for f, n in by_file.items() if len(n) > 1}
print("duplicates:", dups if dups else "none")
