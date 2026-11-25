"""檢查 5（設定）：import main，印出 main.py 看到的每個設定值與選裝套件狀態。
run_checks.py 會用「預設值」與「自訂 .env + 環境變數」兩種情況各跑一次比對。
用法：cd <app 目錄複本> && python config_values.py
"""
import sys, os, io, contextlib
import _guard                                      # noqa: E402  擋下所有對外網路（同目錄的 _guard.py）
sys.path.insert(0, os.getcwd())
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    import main

names = ["MQTT_BROKER_HOST", "MQTT_BROKER_PORT", "MQTT_TOPIC", "NVR_HOST", "NVR_AUTH", "AUDIO_BASE_PATH",
         "NVR_MEDIA_PATH", "TAK_SERVER_HOST", "TAK_SERVER_PORT", "JWT_AVAILABLE", "JWT_SECRET",
         "JWT_EXPIRE_HOURS", "AIOHTTP_AVAILABLE", "WEBRTC_AVAILABLE", "STT_AVAILABLE", "TAK_TCP_PORT"]
# [更新] 拆 auth.py 後，JWT_SECRET、_pyjwt 只有 core/auth.py 在用，main.py 不再 import。
#        名稱在 main 找不到時改從 core/auth.py 讀（輸出格式不變）；兩邊都沒有才印「沒有這個名稱」。
# [更新] 拆 tak.py 後，TAK_TCP_PORT 只有 features/tak.py 在用，main.py 不再有這個名稱；
#        改成依序找 main → core.auth → features.tak（還沒拆出來的版本 import 不到就跳過）。
# [更新] 拆 nvr.py 後，NVR_MEDIA_PATH 只有 features/nvr.py 在用，加上 features.nvr。
# 原本：_FALLBACK_MODULES = ["core.auth", "features.tak"]
# [更新] 拆 stt.py 後，STT_AVAILABLE 在 features/stt.py（main.py 改用 stt.is_available()，不再有這個名稱），加上 features.stt。
# 原本：_FALLBACK_MODULES = ["core.auth", "features.tak", "features.nvr"]
_FALLBACK_MODULES = ["core.auth", "features.tak", "features.nvr", "features.stt"]


def _find(n):
    if hasattr(main, n):
        return True, getattr(main, n)
    # 原本：try:
    # 原本：    import core.auth as _auth
    # 原本：except ImportError:
    # 原本：    return False, None
    # 原本：if hasattr(_auth, n):
    # 原本：    return True, getattr(_auth, n)
    import importlib
    for mod_name in _FALLBACK_MODULES:
        try:
            mod = importlib.import_module(mod_name)
        except ImportError:
            continue
        if hasattr(mod, n):
            return True, getattr(mod, n)
    return False, None


for n in names:
    # 原本：if not hasattr(main, n):
    # 原本：    print(f"{n:18} <main 裡沒有這個名稱>")
    # 原本：    continue
    # 原本：v = getattr(main, n)
    found, v = _find(n)
    if not found:
        print(f"{n:18} <main 裡沒有這個名稱>")
        continue
    print(f"{n:18} {type(v).__name__:5} {v!r}")
# 原本：print(f"{'_pyjwt':18} {getattr(getattr(main, '_pyjwt', None), '__name__', None)!r}")
print(f"{'_pyjwt':18} {getattr(_find('_pyjwt')[1], '__name__', None)!r}")
print(f"{'aiohttp':18} {getattr(getattr(main, 'aiohttp', None), '__name__', None)!r}")
print("audio dir exists  ", os.path.isdir(getattr(main, "AUDIO_BASE_PATH", "")))
print("import-time prints:", sorted(set(l for l in buf.getvalue().splitlines() if l.strip())))
