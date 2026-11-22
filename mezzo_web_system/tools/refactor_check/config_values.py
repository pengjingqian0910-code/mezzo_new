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
for n in names:
    if not hasattr(main, n):
        print(f"{n:18} <main 裡沒有這個名稱>")
        continue
    v = getattr(main, n)
    print(f"{n:18} {type(v).__name__:5} {v!r}")
print(f"{'_pyjwt':18} {getattr(getattr(main, '_pyjwt', None), '__name__', None)!r}")
print(f"{'aiohttp':18} {getattr(getattr(main, 'aiohttp', None), '__name__', None)!r}")
print("audio dir exists  ", os.path.isdir(getattr(main, "AUDIO_BASE_PATH", "")))
print("import-time prints:", sorted(set(l for l in buf.getvalue().splitlines() if l.strip())))
