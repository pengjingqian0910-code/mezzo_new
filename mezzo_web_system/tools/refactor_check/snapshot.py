"""檢查 1：路由與資料表快照。
在 app 目錄（的複本）裡 import main，把所有路由（路徑、方法、參數、依賴、endpoint）、
資料表欄位、啟動事件存成 JSON。
用法：cd <app 目錄複本> && python snapshot.py <輸出.json>
"""
import sys, os, json, io, contextlib
sys.path.insert(0, os.getcwd())

with contextlib.redirect_stdout(io.StringIO()):
    import main


def dep_tree(d):
    return {
        "path": sorted(p.name for p in d.path_params),
        "query": sorted(p.name for p in d.query_params),
        "header": sorted(p.name for p in d.header_params),
        "body": sorted(p.name for p in d.body_params),
        "deps": [(getattr(s.call, "__name__", repr(s.call)), dep_tree(s)) for s in d.dependencies],
    }


routes = []
for r in main.app.routes:
    item = {"path": r.path, "kind": type(r).__name__, "name": getattr(r, "name", None),
            "methods": sorted(getattr(r, "methods", None) or [])}
    if hasattr(r, "dependant"):
        item["dependant"] = dep_tree(r.dependant)
    if hasattr(r, "response_class"):
        rc = getattr(r.response_class, "value", r.response_class)   # unwrap DefaultPlaceholder
        item["response_class"] = getattr(rc, "__name__", type(rc).__name__)
    if hasattr(r, "endpoint"):
        item["endpoint"] = f"{r.endpoint.__module__}.{r.endpoint.__qualname__}"
    routes.append(item)

tables = {}
for name, t in main.Base.metadata.tables.items():
    tables[name] = [(c.name, str(c.type), c.primary_key, bool(c.index), bool(c.unique), c.nullable,
                     repr(c.default.arg) if c.default is not None and not callable(c.default.arg) else None,
                     sorted(fk.target_fullname for fk in c.foreign_keys)) for c in t.columns]

events = {k: [f.__name__ for f in v] for k, v in
          (("startup", main.app.router.on_startup), ("shutdown", main.app.router.on_shutdown))}

json.dump({"routes": routes, "tables": tables, "events": events}, open(sys.argv[1], "w", encoding="utf-8"),
          ensure_ascii=False, indent=1, sort_keys=True)
print(f"routes={len(routes)} tables={len(tables)}")
