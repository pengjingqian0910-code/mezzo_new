"""
WebSocket 連線管理
------------------
ConnectionManager：記錄目前連上的 WebSocket，提供 connect / disconnect / broadcast。
manager     → /ws/map-data（地圖：GPS、SOS、警戒區告警）
ptt_manager → /ws/ptt（PTT 音訊轉發）

從 main.py 原樣搬出，只有類別和兩個實例；/ws/map-data、/ws/ptt 兩個端點還留在 main.py
（它們要用 devices_state、mqtt_client），之後跟 MQTT 一起拆。

main.py 和 features/geofence.py（經 init_router 傳入）用的是這裡的同一個 manager / ptt_manager 物件。
這支檔案不 import main。
"""
from fastapi import WebSocket

class ConnectionManager:
    def __init__(self): self.active_connections = []
    async def connect(self, ws: WebSocket): await ws.accept(); self.active_connections.append(ws)
    def disconnect(self, ws: WebSocket):
        if ws in self.active_connections: self.active_connections.remove(ws)
    async def broadcast(self, msg: dict):
        for conn in list(self.active_connections):
            try: await conn.send_json(msg)
            except: self.active_connections.remove(conn)

manager     = ConnectionManager()
ptt_manager = ConnectionManager()
