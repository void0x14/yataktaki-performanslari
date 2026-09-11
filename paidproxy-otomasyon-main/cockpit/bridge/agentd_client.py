"""paidproxy-agentd JSONL istemcisi.

İstemci yalnız SSH port-forward üzerinden VDS loopback supervisor'a bağlanır.
Yerel makinede ajan veya tarama prosesi başlatmaz.
"""
from __future__ import annotations

from collections.abc import Iterator
import json
import socket
import threading
from typing import Any

from cockpit.bridge.vds import SSHPortForward, VDSConfig
from services.agentd.protocol import decode_message, encode_message, make_command, new_id


class RemoteAgentClient:
    def __init__(self, config: VDSConfig | None = None) -> None:
        self.config = config or VDSConfig()
        self.forward = SSHPortForward(self.config)
        self._lock = threading.RLock()
        self._closed = False

    def connect(self) -> None:
        with self._lock:
            self._closed = False
            self.forward.start()

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self.forward.stop()

    @property
    def connected(self) -> bool:
        process = self.forward.process
        return bool(process is not None and process.poll() is None and self.forward.local_port)

    def _local_endpoint(self) -> tuple[str, int]:
        self.connect()
        port = self.forward.local_port
        if not port:
            raise ConnectionError("SSH port-forward has no local endpoint")
        return "127.0.0.1", port

    def request(self, command: str, **payload: Any) -> dict[str, Any]:
        for attempt in range(2):
            try:
                request_id = new_id("request")
                body = make_command(command, request_id, **payload)
                host, port = self._local_endpoint()
                with socket.create_connection((host, port), timeout=15) as sock:
                    sock.settimeout(30)
                    sock.sendall(encode_message(body).encode("utf-8"))
                    reader = sock.makefile("r", encoding="utf-8")
                    while True:
                        line = reader.readline()
                        if not line:
                            raise ConnectionError(f"agentd closed request connection: {command}")
                        message = decode_message(line)
                        if message.get("kind") != "event" or message.get("request_id") == request_id:
                            return message
            except (ConnectionError, OSError):
                if attempt == 0:
                    with self._lock:
                        self.forward.stop()
                    continue
                raise


    def subscribe(
        self,
        after_seq: int = 0,
        agent_id: str | None = None,
    ) -> Iterator[dict[str, Any]]:
        request_id = new_id("subscription")
        body = make_command(
            "subscribe",
            request_id,
            after_seq=int(after_seq),
            agent_id=agent_id or "",
        )
        host, port = self._local_endpoint()
        sock = socket.create_connection((host, port), timeout=15)
        sock.settimeout(None)
        try:
            sock.sendall(encode_message(body).encode("utf-8"))
            reader = sock.makefile("r", encoding="utf-8")
            while not self._closed:
                line = reader.readline()
                if not line:
                    raise ConnectionError("agentd event stream closed")
                yield decode_message(line)
        finally:
            try:
                reader.close()
            except (UnboundLocalError, OSError, ValueError):
                pass
            sock.close()

    def hard_kill(self, agent_id: str, reason: str = "operator") -> dict[str, Any]:
        return self.request("hard_kill", agent_id=agent_id, reason=reason)

    def replay(self, agent_id: str | None = None, after_seq: int = 0) -> list[dict[str, Any]]:
        response = self.request("replay", agent_id=agent_id or "", after_seq=int(after_seq))
        return list(response.get("events", []) or [])

    def status(self) -> dict[str, Any]:
        return self.request("status")
