"""Qt'süz canlı VDS RFB köprüsü: wayvnc loopback'i SSH üzerinden yerel porta taşır.

Tauri canlı görünümünün gerçek RFB istemci mantığını içerir.
Kalıcı süreç: stdin'den satır satır komut okur (watch/input/stop), stdout'a JSON
satırları yazar (Tauri `show_base` event'i olarak yayınlanır).
"""
from __future__ import annotations

from collections import deque
import base64
import json
from pathlib import Path
import socket
import struct
import sys
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from cockpit.bridge.vds import VDSConfig, WayVNCForward  # noqa: E402

STOP = threading.Event()
FORWARD: WayVNCForward | None = None
SOCK: socket.socket | None = None
SEND_LOCK = threading.Lock()
FRAME_LOCK = threading.Lock()
LAST_FRAME: bytes | None = None
LAST_FRAME_W = 0
LAST_FRAME_H = 0
FRAME_SEQ = 0
FRAME_SIZE = (0, 0)
LIVE_MAX_FPS = 12
FRAME_TIMES: deque[float] = deque(maxlen=24)


def emit(state: str, detail: str, image: bytes = b"", width: int = 0, height: int = 0, seq: int = 0, fps: float = 0.0) -> None:
    """Tek JSON satırı olarak stdout'a yazar; lib.rs bunu `show_base` event'ine çevirir."""
    payload: dict[str, object] = {"state": state, "detail": detail, "width": width, "height": height, "seq": seq, "fps": round(fps, 1), "ts": time.time()}
    if image:
        payload["image"] = base64.b64encode(image).decode("ascii")
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def recv_exact(sock: socket.socket, size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = int(size)
    while remaining:
        chunk = sock.recv(remaining)
        if not chunk:
            raise ConnectionError("RFB bağlantısı kapandı")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def frame_png() -> bytes:
    with FRAME_LOCK:
        frame, w, h = LAST_FRAME, LAST_FRAME_W, LAST_FRAME_H
    if frame is None or not w or not h:
        return b""
    try:
        import io

        from PIL import Image

        buffer = io.BytesIO()
        Image.frombytes("RGBX", (w, h), frame).convert("RGB").save(buffer, format="PNG", optimize=False)
        return buffer.getvalue()
    except ImportError:
        return frame


def send_rfb(payload: bytes) -> None:
    with SEND_LOCK:
        sock = SOCK
    if sock is None or STOP.is_set():
        raise ConnectionError("RFB soketi yok")
    sock.sendall(payload)


def send_pointer(mask: int, x: int, y: int) -> None:
    send_rfb(struct.pack(">BBHH", 5, mask & 0xFF, max(0, min(0xFFFF, x)), max(0, min(0xFFFF, y))))


def send_key(keysym: int, down: bool) -> None:
    send_rfb(struct.pack(">BBHI", 4, 1 if down else 0, 0, keysym & 0xFFFFFFFF))


KEYSYM = {
    "Backspace": 0xFF08, "Tab": 0xFF09, "Enter": 0xFF0D, "NumpadEnter": 0xFF0D,
    "Escape": 0xFF1B, "Delete": 0xFFFF, "Home": 0xFF50, "End": 0xFF57,
    "PageUp": 0xFF55, "PageDown": 0xFF56, "Insert": 0xFF63,
    "ArrowLeft": 0xFF51, "ArrowUp": 0xFF52, "ArrowRight": 0xFF53, "ArrowDown": 0xFF54,
    "ShiftLeft": 0xFFE1, "ShiftRight": 0xFFE2, "ControlLeft": 0xFFE3, "ControlRight": 0xFFE4,
    "AltLeft": 0xFFE9, "AltRight": 0xFFEA, "MetaLeft": 0xFFE7, "MetaRight": 0xFFE8,
    "Space": 0x20,
    "F1": 0xFFBE, "F2": 0xFFBF, "F3": 0xFFC0, "F4": 0xFFC1, "F5": 0xFFC2,
    "F6": 0xFFC3, "F7": 0xFFC4, "F8": 0xFFC5, "F9": 0xFFC6, "F10": 0xFFC7,
    "F11": 0xFFC8, "F12": 0xFFC9,
}


def human_input(entry: dict) -> None:
    """İnsan girdisini gerçek RFB soketine yazar; sonucu UI'a bildirir."""
    kind = str(entry.get("kind", ""))
    try:
        if kind == "pointer":
            send_pointer(int(entry.get("mask", 0)), int(entry.get("x", 0)), int(entry.get("y", 0)))
        elif kind == "key":
            send_key(int(entry.get("keysym", 0)), bool(entry.get("down", True)))
        else:
            raise ValueError(f"bilinmeyen girdi türü: {kind or 'boş'}")
        emit("INPUT", json.dumps({"ok": True, **entry}, ensure_ascii=False))
    except Exception as exc:
        emit("INPUT", json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}", **entry}, ensure_ascii=False))


def request_update(sock: socket.socket, width: int, height: int, incremental: bool) -> None:
    sock.sendall(struct.pack(">BBHHHH", 3, 1 if incremental else 0, 0, 0, width, height))


def read_update(sock: socket.socket, framebuffer: bytearray, width: int, height: int) -> None:
    recv_exact(sock, 1)
    rectangles = struct.unpack(">H", recv_exact(sock, 2))[0]
    for _ in range(rectangles):
        x, y, w, h = struct.unpack(">HHHH", recv_exact(sock, 8))
        encoding = struct.unpack(">i", recv_exact(sock, 4))[0]
        if encoding != 0:
            raise ConnectionError(f"wayvnc raw yerine encoding={encoding} gönderdi")
        if x + w > width or y + h > height:
            raise ConnectionError("RFB rectangle framebuffer dışına taşıyor")
        raw = recv_exact(sock, w * h * 4)
        for row in range(h):
            source = row * w * 4
            target = ((y + row) * width + x) * 4
            framebuffer[target:target + w * 4] = raw[source:source + w * 4]


def current_fps() -> float:
    now = time.monotonic()
    FRAME_TIMES.append(now)
    if len(FRAME_TIMES) < 2:
        return 0.0
    span = FRAME_TIMES[-1] - FRAME_TIMES[0]
    return (len(FRAME_TIMES) - 1) / span if span > 0 else 0.0


def emit_last_frame(reason: str) -> None:
    """Yeni RFB oturumu kurulana kadar son bilinen kareyi UI'a göster."""
    with FRAME_LOCK:
        frame = LAST_FRAME
        w, h = LAST_FRAME_W, LAST_FRAME_H
        seq = FRAME_SEQ
    if frame and w and h:
        emit("STALE", reason, frame_png(), w, h, seq)


def publish_frame(framebuffer: bytearray, width: int, height: int) -> None:
    global LAST_FRAME, LAST_FRAME_W, LAST_FRAME_H, FRAME_SEQ
    with FRAME_LOCK:
        LAST_FRAME = bytes(framebuffer)
        LAST_FRAME_W = width
        LAST_FRAME_H = height
        FRAME_SEQ += 1
        seq = FRAME_SEQ
    emit("LIVE", "RFB kare alındı", frame_png(), width, height, seq, current_fps())


def close_rfb() -> None:
    global SOCK
    with SEND_LOCK:
        sock, SOCK = SOCK, None
    if sock is not None:
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            sock.close()
        except OSError:
            pass


def run_rfb(local_port: int) -> None:
    """Tek RFB oturumu; WayVNC’nin RFB 3.8 protokol dizilimi."""
    global SOCK, FRAME_SIZE
    try:
        with socket.create_connection(("127.0.0.1", local_port), timeout=8) as sock:
            with SEND_LOCK:
                SOCK = sock
            sock.settimeout(8)
            server_version = recv_exact(sock, 12)
            if not server_version.startswith(b"RFB "):
                raise ConnectionError(f"RFB protokolü okunamadı: {server_version!r}")
            sock.sendall(b"RFB 003.008\n")
            security_count = recv_exact(sock, 1)[0]
            if security_count == 0:
                reason_len = struct.unpack(">I", recv_exact(sock, 4))[0]
                reason = recv_exact(sock, reason_len).decode("utf-8", "replace")
                raise ConnectionError(f"wayvnc security reddetti: {reason[:220]}")
            security_types = list(recv_exact(sock, security_count))
            if 1 not in security_types:
                raise ConnectionError(f"desteklenmeyen RFB security types: {security_types}")
            sock.sendall(b"\x01")
            if struct.unpack(">I", recv_exact(sock, 4))[0] != 0:
                raise ConnectionError("RFB security sonucu başarısız")
            sock.sendall(b"\x01")
            init = recv_exact(sock, 24)
            width, height = struct.unpack(">HH", init[:4])
            if not width or not height or width > 4096 or height > 4096:
                raise ConnectionError(f"geçersiz RFB framebuffer: {width}x{height}")
            name_length = struct.unpack(">I", init[20:24])[0]
            if name_length > 1024 * 1024:
                raise ConnectionError("RFB desktop adı aşırı büyük")
            desktop_name = recv_exact(sock, name_length).decode("utf-8", "replace")
            FRAME_SIZE = (width, height)
            emit("CONNECTED", f"ServerInit: {width}×{height} · {desktop_name or 'adsız masaüstü'}")
            sock.sendall(b"\x00\x00\x00\x00" + struct.pack(">BBBB", 32, 24, 0, 1) + struct.pack(">HHHBBBxxx", 255, 255, 255, 16, 8, 0))
            sock.sendall(struct.pack(">BBHi", 2, 0, 1, 0))
            framebuffer = bytearray(width * height * 4)
            first_frame = True
            request_update(sock, width, height, False)
            sock.settimeout(1.0)
            idle_polls = 0
            while not STOP.is_set():
                try:
                    message_type = recv_exact(sock, 1)[0]
                except socket.timeout:
                    if STOP.is_set():
                        break
                    idle_polls += 1
                    request_update(sock, width, height, incremental=(idle_polls % 5 != 0))
                    continue
                sock.settimeout(8.0)
                if message_type == 0:
                    read_update(sock, framebuffer, width, height)
                    publish_frame(framebuffer, width, height)
                    if first_frame:
                        emit("LIVE", f"RFB framebuffer canlı: {width}×{height}")
                        first_frame = False
                    if STOP.wait(1.0 / LIVE_MAX_FPS):
                        break
                    request_update(sock, width, height, True)
                elif message_type == 2:
                    continue
                elif message_type == 1:
                    recv_exact(sock, 3)
                    colors = struct.unpack(">H", recv_exact(sock, 2))[0]
                    recv_exact(sock, colors * 6)
                elif message_type == 3:
                    length = struct.unpack(">I", recv_exact(sock, 4))[0]
                    recv_exact(sock, length)
                else:
                    raise ConnectionError(f"desteklenmeyen RFB server mesajı: {message_type}")
                sock.settimeout(1.0)
    except Exception as exc:
        if not STOP.is_set():
            emit("UNAVAILABLE", f"RFB görüntüsü alınamadı: {type(exc).__name__}: {exc}")
    finally:
        close_rfb()


def supervisor(remote_port: int) -> None:
    """SSH tüneli + RFB oturumunu kalıcı olarak yönetir; kopmada sessizce yeniden bağlanır."""
    global FORWARD
    cfg = VDSConfig()
    attempt = 0
    while not STOP.is_set():
        try:
            if FORWARD is None:
                FORWARD = WayVNCForward(cfg, remote_port)
            local_port = FORWARD.start()
            emit("TUNNEL", f"SSH wayvnc tüneli açık: 127.0.0.1:{local_port} → VDS:{remote_port}")
            attempt = 0
        except Exception as exc:  # noqa: BLE001 - tünel hatası UI'a bildirilir, süreç ölmez
            attempt += 1
            emit("UNAVAILABLE", f"wayvnc tüneli kurulamadı ({attempt}): {type(exc).__name__}: {exc}")
            if STOP.wait(min(30.0, 1.5 * attempt)):
                break
            continue
        run_rfb(local_port)
        if STOP.is_set():
            break
        # RFB oturumu koptu: tüneli tazele, son kareyi göster, kısa süre sonra tekrar bağlan.
        try:
            FORWARD.stop()
        except Exception:  # noqa: BLE001
            pass
        FORWARD = WayVNCForward(cfg, remote_port)
        emit("RECONNECTING", "RFB oturumu koptu · son kare gösteriliyor · yeniden bağlanılıyor")
        emit_last_frame("son kare (yeniden bağlanma)")
        if STOP.wait(1.5):
            break
    close_rfb()
    if FORWARD is not None:
        try:
            FORWARD.stop()
        except Exception:  # noqa: BLE001
            pass


def watch(remote_port: int) -> int:
    global FORWARD
    STOP.clear()
    # İlk tüneli ana thread'de bir kez dene ki UI hızlı yanıt alsın; hata olsa da süreç yaşar.
    cfg = VDSConfig()
    FORWARD = WayVNCForward(cfg, remote_port)
    try:
        local_port = FORWARD.start(timeout=6.0)
        emit("TUNNEL", f"SSH wayvnc tüneli açık: 127.0.0.1:{local_port} → VDS:{remote_port}")
        print(json.dumps({"ok": True, "local_port": local_port, "remote_port": remote_port}), flush=True)
    except Exception as exc:  # noqa: BLE001
        emit("UNAVAILABLE", f"ilk wayvnc tüneli kurulamadı: {type(exc).__name__}: {exc}")
        print(json.dumps({"ok": False, "remote_port": remote_port, "error": str(exc)}), flush=True)
    threading.Thread(target=supervisor, args=(remote_port,), daemon=True).start()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            sub = json.loads(line)
        except json.JSONDecodeError:
            continue
        action = str(sub.get("action", ""))
        if action == "input":
            human_input(sub)
        elif action == "stop":
            break
    STOP.set()
    close_rfb()
    if FORWARD is not None:
        FORWARD.stop()
    return 0


def main() -> int:
    line = sys.stdin.readline()
    if not line.strip():
        return 2
    message = json.loads(line)
    action = str(message.get("action", "watch"))
    if action == "watch":
        return watch(int(message.get("remote_port") or VDSConfig().wayvnc_loopback_port))
    raise ValueError(f"bilinmeyen eylem: {action}")


if __name__ == "__main__":
    raise SystemExit(main())
