"""網路防護：import 之後，所有對外（非 127.0.0.1 / localhost）的 socket 連線與 UDP 傳送都會被擋下並記錄。
用途：測試時就算觸發了 TAK 推送、WhatsApp、NVR 等對外功能，也不會真的送出任何封包。
本機 loopback 不擋（Windows 的 asyncio 事件迴圈內部會用到）。
用法：在測試腳本最前面 `import _guard`，最後呼叫 `_guard.report()` 印出被擋下的目的地。
"""
import socket, urllib.request

blocked = []
_LOCAL = ("127.", "::1", "localhost", "0.0.0.0")


def _is_local(addr):
    host = addr[0] if isinstance(addr, tuple) else str(addr)
    return any(str(host).startswith(p) for p in _LOCAL)


_orig_connect, _orig_connect_ex, _orig_sendto = socket.socket.connect, socket.socket.connect_ex, socket.socket.sendto


def _connect(self, addr):
    if _is_local(addr):
        return _orig_connect(self, addr)
    blocked.append(("tcp-connect", str(addr[0]), addr[1]))
    raise ConnectionRefusedError(f"[_guard] 已擋下對外連線 {addr}")


def _connect_ex(self, addr):
    if _is_local(addr):
        return _orig_connect_ex(self, addr)
    blocked.append(("tcp-connect", str(addr[0]), addr[1]))
    return 111   # ECONNREFUSED


def _sendto(self, data, *args):
    addr = args[-1]
    if _is_local(addr):
        return _orig_sendto(self, data, *args)
    blocked.append(("udp-sendto", str(addr[0]), addr[1]))
    return len(data)          # 假裝送出，實際上沒有


socket.socket.connect, socket.socket.connect_ex, socket.socket.sendto = _connect, _connect_ex, _sendto
_orig_create_connection = socket.create_connection


def _create_connection(address, *a, **kw):
    if _is_local(address):
        return _orig_create_connection(address, *a, **kw)
    blocked.append(("tcp-connect", str(address[0]), address[1]))
    raise ConnectionRefusedError(f"[_guard] 已擋下對外連線 {address}")


socket.create_connection = _create_connection


def _urlopen(req, *a, **kw):
    url = req.full_url if hasattr(req, "full_url") else str(req)
    if "://127.0.0.1" in url or "://localhost" in url:
        raise RuntimeError("[_guard] 測試不應呼叫本機 HTTP")
    blocked.append(("http", url.split("?")[0], ""))
    raise ConnectionRefusedError(f"[_guard] 已擋下對外 HTTP {url}")


urllib.request.urlopen = _urlopen


# ---- asyncio / aiohttp：Windows 的 Proactor 事件迴圈不經過 socket.connect，要另外擋 ----
import asyncio, asyncio.base_events, asyncio.proactor_events, asyncio.selector_events, ipaddress  # noqa: E402

_orig_create_conn = asyncio.base_events.BaseEventLoop.create_connection


async def _loop_create_connection(self, protocol_factory, host=None, port=None, *a, **kw):
    if host is not None and not _is_local(host):
        blocked.append(("tcp-connect", str(host), port))
        raise ConnectionRefusedError(f"[_guard] 已擋下對外連線 {host}:{port}")
    return await _orig_create_conn(self, protocol_factory, host, port, *a, **kw)


asyncio.base_events.BaseEventLoop.create_connection = _loop_create_connection

for _cls in (asyncio.proactor_events.BaseProactorEventLoop, asyncio.selector_events.BaseSelectorEventLoop):
    def _make(orig):
        async def _sock_connect(self, sock, address):
            if not _is_local(address):
                blocked.append(("tcp-connect", str(address[0]), address[1]))
                raise ConnectionRefusedError(f"[_guard] 已擋下對外連線 {address}")
            return await orig(self, sock, address)
        return _sock_connect
    _cls.sock_connect = _make(_cls.sock_connect)

# ---- DNS：主機名稱（非 IP、非 localhost）一律不查 ----
_orig_getaddrinfo = socket.getaddrinfo


def _getaddrinfo(host, *a, **kw):
    h = host.decode() if isinstance(host, bytes) else host
    if h and not _is_local(h):
        try:
            ipaddress.ip_address(h)          # 本身就是 IP → 不需要查 DNS，放行（連線時再擋）
        except ValueError:
            blocked.append(("dns", h, ""))
            raise socket.gaierror(f"[_guard] 已擋下 DNS 查詢 {h}")
    return _orig_getaddrinfo(host, *a, **kw)


socket.getaddrinfo = _getaddrinfo


def report():
    print("blocked outbound:", sorted(set(blocked)))
