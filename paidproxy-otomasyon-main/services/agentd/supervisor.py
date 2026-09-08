"""paidproxy-agentd kalıcı VDS gözetmeni.

Bu servis yalnız loopback'te dinler. Masaüstü SSH port-forward ile bağlanır;
tüm lifecycle kararları ve gerçek PID kontrolü burada uygulanır.
"""
from __future__ import annotations

import argparse
import asyncio
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
from typing import Any

from services.agentd.protocol import (
    COMMANDS,
    TERMINAL_STATES,
    decode_message,
    encode_message,
    error_response,
    make_event,
    new_id,
    ok_response,
)
from services.agentd.state import StateStore
from services.agentd.evidence_display import (
    ack_evidence_completion,
    read_display_state,
    read_capability,
    read_evidence_completions,
    request_video_revoke,
    restore_video_demand,
    select_display_agent,
    wait_for_display_render,
)

from services.agentd.handover import (
    HandoverError,
    HandoverSession,
    process_identity,
    receive_handover,
    wait_for_pid_exit,
)


WORKER_IO_THREADS = 128
WORKER_IO_RESERVED_SLOTS = 8
WORKER_IO_SLOTS_PER_WORKER = 3


@dataclass
class WorkerHandle:
    agent_id: str
    process: subprocess.Popen[str] | None
    pid: int
    process_group: int
    started_at: str
    hard_kill_requested: bool = False
    adopted: bool = False
    starttime_ticks: int | None = None
    stdout: Any | None = None
    stderr: Any | None = None
    pidfd: int | None = None
    persisted_state: str = "running"


class Supervisor:
    def __init__(
        self,
        root: Path | str,
        host: str = "127.0.0.1",
        port: int = 8787,
        handover_socket: Path | str | None = None,
        handover_old_agentd_pid: int | None = None,
        prepare_only: bool = False,
    ) -> None:
        self.root = Path(root).expanduser().resolve()
        self.host = host
        self.port = int(port)
        self.store = StateStore(self.root)
        self._server: asyncio.AbstractServer | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._started_at = datetime.now(timezone.utc)
        self._handles: dict[str, WorkerHandle] = {}
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._closed = False
        self._evidence_task: asyncio.Task[None] | None = None
        self._adopted_tasks: list[asyncio.Task[Any]] = []
        self._adopted_task_roles: dict[asyncio.Task[Any], str] = {}
        self._adopted_prepared_counts = {"stream": 0, "watcher": 0}
        self._adopted_prepared_event = asyncio.Event()
        self._adopted_activation_event = asyncio.Event()
        self._adopted_read_attempts = 0
        self._handover_session: HandoverSession | None = None
        self._handover_prepare_only = bool(prepare_only)
        self._command_ready = False
        self._handover_reconciliation_plan: list[dict[str, Any]] = []
        self._worker_io_executor = ThreadPoolExecutor(
            max_workers=WORKER_IO_THREADS,
            thread_name_prefix="paidproxy-worker-io",
        )
        self._handover_socket = (
            Path(handover_socket).expanduser().resolve() if handover_socket else None
        )
        self._handover_old_agentd_pid = (
            int(handover_old_agentd_pid) if handover_old_agentd_pid is not None else None
        )
        if self._handover_socket is None:
            self._recover_persisted_processes()
        else:
            if self._handover_old_agentd_pid is None:
                self._worker_io_executor.shutdown(wait=False, cancel_futures=True)
                raise HandoverError("handover socket requires --old-agentd-pid")
            self._handover_session = receive_handover(
                self.root,
                self._handover_socket,
                self.store.list_agents(include_hidden=True),
                self._handover_old_agentd_pid,
            )
            self._install_adopted_workers(self._handover_session.adopted)

    def _recover_persisted_processes(self) -> None:
        for agent in self.store.list_agents(include_hidden=True):
            if agent.get("state") not in {"running", "paused"}:
                continue
            pid = agent.get("pid")
            process_group = agent.get("process_group")
            if not pid:
                continue
            self.store.update_agent(
                agent["agent_id"],
                state="unknown",
                working_note="Supervisor yeniden başladı; eski PID otomatik sahiplenilmedi.",
                next_action="operator inspect",
            )
            self.store.record_event(
                "recovery_required",
                agent_id=agent["agent_id"],
                job_id=agent.get("job_id", ""),
                pid=pid,
                process_group=process_group,
                state="unknown",
                tool="supervisor_recovery",
                target="vds://process",
                working_note="Kalıcı kayıt var fakat yeni supervisor eski prosesi otomatik yeniden başlatmıyor.",
                next_action="operator inspect",
            )

    def _repo_root(self) -> Path:
        return Path(__file__).resolve().parents[2]

    def _handle_is_alive(self, handle: WorkerHandle) -> bool:
        if handle.adopted:
            if handle.starttime_ticks is None:
                return False
            try:
                process_identity(
                    handle.pid,
                    expected_starttime_ticks=handle.starttime_ticks,
                    expected_pgid=handle.process_group,
                )
            except HandoverError:
                return False
            return True
        return handle.process is not None and handle.process.poll() is None


    def _worker_io_capacity_facts(self) -> dict[str, int]:
        live_handles = sum(
            1 for handle in self._handles.values() if self._handle_is_alive(handle)
        )
        safe_capacity = max(
            0,
            (WORKER_IO_THREADS - WORKER_IO_RESERVED_SLOTS) // WORKER_IO_SLOTS_PER_WORKER,
        )
        return {
            "worker_io_threads": WORKER_IO_THREADS,
            "worker_io_reserved_slots": WORKER_IO_RESERVED_SLOTS,
            "worker_io_slots_per_worker": WORKER_IO_SLOTS_PER_WORKER,
            "worker_io_safe_live_capacity": safe_capacity,
            "worker_io_live_handles": live_handles,
            "worker_io_expected_persistent_slots": live_handles * WORKER_IO_SLOTS_PER_WORKER,
        }

    def _close_adopted_streams(self, handle: WorkerHandle) -> None:
        if not handle.adopted:
            return
        for stream in (handle.stdout, handle.stderr):
            if stream is None:
                continue
            try:
                stream.close()
            except (OSError, ValueError):
                pass
        handle.stdout = None
        handle.stderr = None
        if handle.pidfd is not None:
            try:
                os.close(handle.pidfd)
            except OSError:
                pass
            handle.pidfd = None

    def _install_adopted_workers(self, adopted: list[dict[str, Any]]) -> None:
        seen: set[str] = set()
        for item in adopted:
            agent_id = str(item.get("agent_id", "")).strip()
            if not agent_id or agent_id in seen:
                raise HandoverError(f"invalid or duplicate adopted agent: {agent_id!r}")
            starttime_ticks = item.get("starttime_ticks")
            stdout = item.get("stdout")
            stderr = item.get("stderr")
            if starttime_ticks is None or stdout is None or stderr is None:
                raise HandoverError(f"adopted worker is incomplete: {agent_id}")
            state = str(item.get("state") or "running")
            if state not in {"running", "paused", "stopping"}:
                raise HandoverError(f"adopted worker has invalid state: {agent_id}")
            seen.add(agent_id)
            self._handles[agent_id] = WorkerHandle(
                agent_id=agent_id,
                process=None,
                pid=int(item["pid"]),
                process_group=int(item["process_group"]),
                started_at=datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                adopted=True,
                starttime_ticks=int(starttime_ticks),
                stdout=stdout,
                stderr=stderr,
                pidfd=item.get("pidfd"),
                persisted_state=state,
            )

    async def _wait_for_handle_exit(self, handle: WorkerHandle, timeout: float | None) -> bool:
        loop = asyncio.get_running_loop()
        if handle.adopted:
            if handle.starttime_ticks is None:
                return False
            return bool(
                await loop.run_in_executor(
                    self._worker_io_executor,
                    partial(
                        wait_for_pid_exit,
                        handle.pid,
                        int(handle.starttime_ticks),
                        pidfd=handle.pidfd,
                        timeout=timeout,
                    ),
                )
            )
        process = handle.process
        if process is None:
            return True

        def wait_native() -> bool:
            try:
                process.wait(timeout)
            except subprocess.TimeoutExpired:
                return False
            return True

        return bool(await loop.run_in_executor(self._worker_io_executor, wait_native))

    async def _mark_adopted_task_prepared(self, role: str) -> None:
        if role not in self._adopted_prepared_counts:
            raise HandoverError(f"unknown adopted task role: {role}")
        self._adopted_prepared_counts[role] += 1
        self._adopted_prepared_event.set()
        await self._adopted_activation_event.wait()

    def _track_adopted_task(self, coroutine: Any, role: str) -> None:
        task = asyncio.create_task(coroutine)
        self._adopted_tasks.append(task)
        self._adopted_task_roles[task] = role

    async def _wait_for_adopted_tasks_prepared(self) -> None:
        expected = {
            "stream": sum(1 for handle in self._handles.values() if handle.adopted) * 2,
            "watcher": sum(1 for handle in self._handles.values() if handle.adopted),
        }
        while any(self._adopted_prepared_counts[role] < count for role, count in expected.items()):
            for task in self._adopted_tasks:
                if task.done():
                    if task.cancelled():
                        raise HandoverError("adopted task cancelled before preparation")
                    error = task.exception()
                    if error is not None:
                        raise HandoverError(
                            f"adopted task failed before preparation: {type(error).__name__}: {error}"
                        )
                    raise HandoverError("adopted task ended before preparation")
            self._adopted_prepared_event.clear()
            if all(self._adopted_prepared_counts[role] >= count for role, count in expected.items()):
                break
            await self._adopted_prepared_event.wait()

    async def _attach_adopted_workers(self) -> None:
        adopted = [handle for handle in self._handles.values() if handle.adopted]
        capacity = self._worker_io_capacity_facts()
        if len(adopted) > capacity["worker_io_safe_live_capacity"]:
            raise HandoverError(
                "adopted worker IO capacity exceeded: "
                f"{len(adopted)} > {capacity['worker_io_safe_live_capacity']}"
            )
        for handle in adopted:
            if not self._handle_is_alive(handle):
                raise HandoverError(f"adopted worker identity is no longer alive: {handle.agent_id}")
            if handle.stdout is None or handle.stderr is None:
                raise HandoverError(f"adopted worker streams are missing: {handle.agent_id}")
            self._track_adopted_task(
                self._read_worker_stream(handle.agent_id, handle.stdout, "stdout", adopted=True),
                "stream",
            )
            self._track_adopted_task(
                self._read_worker_stream(handle.agent_id, handle.stderr, "stderr", adopted=True),
                "stream",
            )
            self._track_adopted_task(self._watch_process(handle, adopted=True), "watcher")

    async def _record_adopted_workers(self) -> None:
        for handle in self._handles.values():
            if not handle.adopted:
                continue
            agent = self.store.get_agent(handle.agent_id) or {}
            try:
                await self._record(
                    "process_adopted",
                    agent_id=handle.agent_id,
                    job_id=agent.get("job_id", ""),
                    pid=handle.pid,
                    process_group=handle.process_group,
                    state=handle.persisted_state,
                    tool="process_handover",
                    target="vds://worker",
                    working_note="Çalışan VDS worker aynı PID/PGID ve stdout/stderr FD kimliğiyle devralındı.",
                    next_action="worker runtime",
                )
            except Exception:
                continue

    def _plan_unadopted_transitional_reconciliation(self) -> list[dict[str, Any]]:
        adopted_ids = set(self._handles)
        transitional_states = {"running", "paused", "stopping"}
        intents: list[dict[str, Any]] = []
        for agent in self.store.list_agents(include_hidden=True):
            agent_id = str(agent.get("agent_id", "")).strip()
            previous_state = str(agent.get("state", ""))
            if previous_state not in transitional_states or agent_id in adopted_ids:
                continue
            pid = agent.get("pid")
            process_group = agent.get("process_group")
            if pid:
                stat_path = Path(f"/proc/{int(pid)}/stat")
                try:
                    process_identity(
                        int(pid),
                        expected_pgid=int(process_group) if process_group else None,
                    )
                except HandoverError:
                    if stat_path.exists():
                        raise HandoverError(
                            f"unadopted transitional PID is still present: {agent_id}/{pid}"
                        )
                else:
                    raise HandoverError(
                        f"unadopted transitional PID is still present: {agent_id}/{pid}"
                    )
            intents.append(
                {
                    "agent_id": agent_id,
                    "previous_state": previous_state,
                    "previous_pid": pid,
                    "previous_process_group": process_group,
                    "process_present": False,
                }
            )
        return intents

    async def _apply_unadopted_transitional_reconciliation(
        self,
        intents: list[dict[str, Any]],
    ) -> None:
        for intent in intents:
            agent_id = str(intent["agent_id"])
            try:
                self.store.update_agent(
                    agent_id,
                    state="unknown",
                    working_note="Handover sonrası devralınmayan transitional kayıt için süreç kimliği bulunamadı.",
                    next_action="operator inspect",
                )
                await self._record(
                    "recovery_required",
                    agent_id=agent_id,
                    state="unknown",
                    tool="supervisor_handover_recovery",
                    target="vds://process",
                    working_note="Persisted transitional PID yok; exit code bilinmiyor, sonuç başarı olarak varsayılmadı.",
                    next_action="operator inspect",
                    error="unadopted transitional worker is absent; exit code unavailable",
                    handover_reconciliation=dict(intent),
                )
            except Exception:
                continue

    async def _verify_handover_precommit_ready(self) -> None:
        session = self._handover_session
        if session is None:
            return
        adopted_count = sum(1 for handle in self._handles.values() if handle.adopted)
        expected_task_count = adopted_count * 3
        if len(self._adopted_tasks) != expected_task_count:
            raise HandoverError(
                f"adopted task set incomplete: {len(self._adopted_tasks)} != {expected_task_count}"
            )
        await self._wait_for_adopted_tasks_prepared()
        if self._adopted_read_attempts != 0:
            raise HandoverError(
                f"adopted stream read attempts before commit: {self._adopted_read_attempts}"
            )
        for handle in self._handles.values():
            if handle.adopted and not self._handle_is_alive(handle):
                raise HandoverError(f"adopted worker identity changed before commit: {handle.agent_id}")
        self._handover_reconciliation_plan = self._plan_unadopted_transitional_reconciliation()
        if self._server is None:
            raise HandoverError("handover server is not ready")
        for task in self._adopted_tasks:
            if task.done():
                raise HandoverError("adopted task ended before commit")
        if self._adopted_read_attempts != 0:
            raise HandoverError(
                f"adopted stream read attempts before commit: {self._adopted_read_attempts}"
            )

    async def _commit_handover_if_ready(self) -> None:
        session = self._handover_session
        if session is None:
            self._command_ready = True
            return
        await self._verify_handover_precommit_ready()
        session.commit()
        self._handover_session = None
        self._adopted_activation_event.set()
        await self._record_adopted_workers()
        await self._apply_unadopted_transitional_reconciliation(self._handover_reconciliation_plan)
        self._command_ready = True

    def handover_prepare_summary(self) -> dict[str, Any]:
        session = self._handover_session
        return {
            "mode": "handover-prepare-only",
            "protocol_version": session.manifest.get("manifest_version") if session else None,
            "manifest_id": session.manifest.get("manifest_id") if session else None,
            "adopted_handles": sum(1 for handle in self._handles.values() if handle.adopted),
            "prepared_stream_tasks": self._adopted_prepared_counts["stream"],
            "prepared_watcher_tasks": self._adopted_prepared_counts["watcher"],
            "prepared_tasks_total": sum(self._adopted_prepared_counts.values()),
            "expected_prepared_tasks": sum(1 for handle in self._handles.values() if handle.adopted) * 3,
            "activation_event": self._adopted_activation_event.is_set(),
            "command_ready": self._command_ready,
            "stream_read_attempts": self._adopted_read_attempts,
            "reconciliation_plan": list(self._handover_reconciliation_plan),
            "server_bound": self._server is not None,
            "host": self.host,
            "port": self.port,
            **self._worker_io_capacity_facts(),
            "committed": bool(session and session.committed),
        }

    async def start(self) -> None:
        if self._server is not None:
            return
        self._loop = asyncio.get_running_loop()
        self._closed = False
        await self._attach_adopted_workers()
        if self._handover_session is not None:
            await self._wait_for_adopted_tasks_prepared()
            if self._adopted_read_attempts != 0:
                raise HandoverError(
                    f"adopted stream read attempts before commit: {self._adopted_read_attempts}"
                )
            self._handover_reconciliation_plan = self._plan_unadopted_transitional_reconciliation()
        self._server = await asyncio.start_server(self._client, self.host, self.port)
        address = self._server.sockets[0].getsockname() if self._server.sockets else (self.host, self.port)
        self.port = int(address[1])
        if self._handover_session is not None:
            await self._verify_handover_precommit_ready()
            if self._handover_prepare_only:
                return
            await self._commit_handover_if_ready()
        else:
            self._command_ready = True
        try:
            self.store.record_event(
                "supervisor_started",
                state="running",
                tool="supervisor",
                target="vds://agentd",
                working_note=f"VDS supervisor loopback üzerinde dinliyor: {self.host}:{self.port}.",
                next_action="operator command",
                supervisor_pid=os.getpid(),
            )
        except Exception:
            pass
        self._evidence_task = asyncio.create_task(self._evidence_pump())
    async def serve_forever(self) -> None:
        await self.start()
        if self._server is None:
            raise RuntimeError("supervisor server was not created")
        async with self._server:
            await self._server.serve_forever()

    async def stop(self) -> None:
        if self._closed:
            return
        self._closed = True
        precommit_handover = bool(
            self._handover_session is not None and not self._handover_session.committed
        )
        if not precommit_handover:
            for handle in list(self._handles.values()):
                if self._handle_is_alive(handle):
                    self.store.record_event(
                        "supervisor_shutdown",
                        agent_id=handle.agent_id,
                        state="unknown",
                        pid=handle.pid,
                        process_group=handle.process_group,
                        tool="supervisor",
                        target="vds://process",
                        working_note="Supervisor kapanıyor; çalışan worker otomatik öldürülmedi.",
                        next_action="operator inspect",
                    )
        task, self._evidence_task = self._evidence_task, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        adopted_tasks, self._adopted_tasks = self._adopted_tasks, []
        for adopted_task in adopted_tasks:
            if not adopted_task.done():
                adopted_task.cancel()
        if adopted_tasks:
            await asyncio.gather(*adopted_tasks, return_exceptions=True)
        session, self._handover_session = self._handover_session, None
        if session is not None and not session.committed:
            session.close_without_commit()
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        for handle in self._handles.values():
            self._close_adopted_streams(handle)
        self._worker_io_executor.shutdown(wait=False, cancel_futures=True)

    async def _send(self, writer: asyncio.StreamWriter, payload: dict[str, Any]) -> None:
        writer.write(encode_message(payload).encode("utf-8"))
        await writer.drain()

    async def _client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        if not self._command_ready:
            writer.close()
            try:
                await writer.wait_closed()
            except (ConnectionError, RuntimeError):
                pass
            return
        queue: asyncio.Queue[dict[str, Any]] | None = None
        try:
            while not reader.at_eof():
                raw = await reader.readline()
                if not raw:
                    break
                try:
                    command = decode_message(raw)
                except Exception as exc:
                    await self._send(writer, error_response(None, "invalid_command", str(exc)))
                    continue
                if command.get("kind") not in (None, "command"):
                    await self._send(
                        writer,
                        error_response(command.get("request_id"), "invalid_command", "kind must be command"),
                    )
                    continue
                name = str(command.get("command", ""))
                if name == "subscribe":
                    queue = asyncio.Queue()
                    self._subscribers.add(queue)
                    after_seq = int(command.get("after_seq", 0) or 0)
                    agent_id = str(command.get("agent_id", "") or "") or None
                    await self._send(
                        writer,
                        ok_response(
                            command.get("request_id"),
                            subscribed=True,
                            after_seq=after_seq,
                            last_seq=self.store.last_seq,
                        ),
                    )
                    for event in self.store.events_after(after_seq, agent_id):
                        await self._send(writer, event)
                    while True:
                        event = await queue.get()
                        if agent_id and event.get("agent_id") != agent_id:
                            continue
                        await self._send(writer, event)
                    break
                response = await self.handle(command)
                await self._send(writer, response)
        except (asyncio.IncompleteReadError, ConnectionResetError, BrokenPipeError):
            pass
        finally:
            if queue is not None:
                self._subscribers.discard(queue)
            writer.close()
            try:
                await writer.wait_closed()
            except (ConnectionError, RuntimeError):
                pass

    async def _publish(self, event: dict[str, Any]) -> None:
        for queue in tuple(self._subscribers):
            try:
                queue.put_nowait(dict(event))
            except asyncio.QueueFull:
                self._subscribers.discard(queue)

    async def _record(self, event_type: str, **fields: Any) -> dict[str, Any]:
        event = self.store.record_event(event_type, **fields)
        await self._publish(event)
        return event
    async def _record_evidence_completion(self, record: dict[str, Any]) -> dict[str, Any]:
        completion_id = str(record.get("completion_id", "")).strip()
        event_type = str(record.get("event_type", "")).strip()
        if not completion_id or not event_type:
            return {}
        fields = dict(record)
        fields.pop("event_type", None)
        fields.pop("created_at", None)
        fields["event_id"] = completion_id
        event = await self._record(event_type, **fields)
        await asyncio.to_thread(ack_evidence_completion, self.root, completion_id)
        return event

    async def _evidence_pump(self) -> None:
        last_error = ""
        while not self._closed:
            try:
                records = await asyncio.to_thread(read_evidence_completions, self.root)
                for record in records[:32]:
                    await self._record_evidence_completion(record)
                last_error = ""
            except (OSError, RuntimeError, ValueError) as exc:
                detail = f"{type(exc).__name__}: {exc}"[:500]
                if detail != last_error:
                    last_error = detail
                    await self._record(
                        "evidence_completion_pump_error",
                        state="degraded",
                        tool="evidence_control",
                        target="vds://evidence/completions",
                        working_note="Evidence completion journal okunamadı; yeniden denenecek.",
                        error=detail,
                        next_action="evidence completion retry",
                    )
            await asyncio.sleep(0.5)

    async def _publish_new_events(self, previous_seq: int) -> None:
        for event in self.store.events_after(previous_seq):
            await self._publish(event)

    def _agent_or_error(self, agent_id: str) -> dict[str, Any]:
        agent = self.store.get_agent(agent_id)
        if not agent:
            raise KeyError(f"unknown agent: {agent_id}")
        return agent

    async def handle(self, command: dict[str, Any]) -> dict[str, Any]:
        request_id = command.get("request_id")
        name = str(command.get("command", ""))
        if name not in COMMANDS:
            return error_response(request_id, "unknown_command", name)
        previous_seq = self.store.last_seq
        try:
            await self._record(
                "command_received",
                state="running",
                tool="operator_command",
                target=f"vds://agentd/{name}",
                working_note=f"VDS komutu alındı: {name}.",
                operator_action=name,
                request_id=request_id,
            )
            if name == "status":
                result = self._status()
            elif name == "create":
                result = await self._create(command)
            elif name == "start":
                result = await self._start(command)
            elif name == "pause":
                result = await self._pause(command)
            elif name == "resume":
                result = await self._resume(command)
            elif name == "hard_kill":
                result = await self._hard_kill(command)
            elif name == "intervene":
                result = await self._intervene(command)
            elif name == "destroy":
                result = await self._destroy(command)
            elif name == "replay":
                result = self._replay(command)
            elif name == "viewport":
                result = self._viewport(command)
            elif name == "display_select":
                result = await self._display_select(command)
            elif name == "display_release":
                result = await self._display_release(command)
            elif name == "subscribe":
                result = {"subscribed": False}
            else:
                result = {}
            response = ok_response(request_id, **result)
            await self._record(
                "command_completed",
                state="running",
                tool="operator_command",
                target=f"vds://agentd/{name}",
                working_note=f"VDS komutu tamamlandı: {name}.",
                operator_action=name,
                request_id=request_id,
            )
            return response
        except KeyError as exc:
            await self._record(
                "error",
                state="failed",
                tool="operator_command",
                target=f"vds://agentd/{name}",
                error=str(exc),
                operator_action=name,
            )
            return error_response(request_id, "not_found", str(exc))
        except Exception as exc:
            await self._record(
                "error",
                state="failed",
                tool="operator_command",
                target=f"vds://agentd/{name}",
                error=f"{type(exc).__name__}: {exc}",
                operator_action=name,
            )
            return error_response(request_id, "command_failed", f"{type(exc).__name__}: {exc}")

    def _status(self) -> dict[str, Any]:
        return {
            "agents": self.store.list_agents(),
            "last_seq": self.store.last_seq,
            "capture_kind": "sway-headless",
            "display_capability": read_capability(self.root),
            "display_control": read_display_state(self.root),
            "supervisor_pid": os.getpid(),
            "uptime_seconds": max(0.0, (datetime.now(timezone.utc) - self._started_at).total_seconds()),
            "host": self.host,
            "port": self.port,
            **self._worker_io_capacity_facts(),
        }

    async def _create(self, command: dict[str, Any]) -> dict[str, Any]:
        kind = str(command.get("agent_kind", "gezinme")).strip() or "gezinme"
        label = str(command.get("label", kind)).strip() or kind
        pet_name = command.get("pet_name")
        agent = self.store.create_agent(kind, label, str(pet_name) if pet_name else None, str(command.get("initial_input", "")))
        return {
            "agent": agent,
            "agent_id": agent["agent_id"],
            "job_id": agent["job_id"],
            "pet": agent["pet"],
            "state": agent["state"],
        }

    async def _start(self, command: dict[str, Any]) -> dict[str, Any]:
        agent_id = str(command.get("agent_id", ""))
        agent = self._agent_or_error(agent_id)
        existing = self._handles.get(agent_id)
        if existing is not None:
            if self._handle_is_alive(existing):
                return {"agent": agent, "pid": agent.get("pid"), "process_group": agent.get("process_group")}
            self._handles.pop(agent_id, None)
            self._close_adopted_streams(existing)
        if agent.get("state") in TERMINAL_STATES or not agent.get("visible", True):
            raise RuntimeError(f"terminal agent cannot start: {agent_id}")
        if agent.get("state") == "unknown":
            raise RuntimeError(f"agent requires recovery inspection: {agent_id}")
        cmd = [
            sys.executable,
            "-m",
            "services.agentd.worker",
            "--agent-id",
            agent_id,
            "--job-id",
            str(agent["job_id"]),
            "--kind",
            str(agent["kind"]),
            "--root",
            str(self.root),
            "--initial-input",
            str(agent.get("initial_input", "")),
        ]
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        existing_pythonpath = env.get("PYTHONPATH", "")
        repo_root = self._repo_root()
        pythonpath = [str(repo_root), str(repo_root / "src")]
        if existing_pythonpath:
            pythonpath.append(existing_pythonpath)
        env["PYTHONPATH"] = os.pathsep.join(pythonpath)
        capacity = self._worker_io_capacity_facts()
        if capacity["worker_io_live_handles"] + 1 > capacity["worker_io_safe_live_capacity"]:
            raise RuntimeError(
                "worker IO capacity exceeded before spawn: "
                f"{capacity['worker_io_live_handles'] + 1} > "
                f"{capacity['worker_io_safe_live_capacity']} live workers"
            )
        process = subprocess.Popen(
            cmd,
            cwd=str(self._repo_root()),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            start_new_session=True,
        )
        pid = int(process.pid)
        process_group = int(os.getpgid(pid))
        handle = WorkerHandle(
            agent_id=agent_id,
            process=process,
            pid=pid,
            process_group=process_group,
            started_at=datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        )
        self._handles[agent_id] = handle
        self.store.update_agent(
            agent_id,
            state="running",
            pid=pid,
            process_group=process_group,
            working_note="VDS worker başlatıldı; gerçek stdout/stderr eventleri bekleniyor.",
            next_action="worker runtime preflight",
        )
        await self._record(
            "process_started",
            agent_id=agent_id,
            job_id=agent["job_id"],
            pid=pid,
            process_group=process_group,
            state="running",
            tool="process_runtime",
            target="vds://worker",
            working_note="VDS gerçek child process ve process-group ile başladı.",
            next_action="worker runtime preflight",
        )
        if process.stdout is not None:
            asyncio.create_task(self._read_worker_stream(agent_id, process.stdout, "stdout"))
        if process.stderr is not None:
            asyncio.create_task(self._read_worker_stream(agent_id, process.stderr, "stderr"))
        asyncio.create_task(self._watch_process(handle))
        return {
            "agent": self.store.get_agent(agent_id),
            "agent_id": agent_id,
            "job_id": agent["job_id"],
            "pid": pid,
            "process_group": process_group,
            "state": "running",
        }

    async def _read_worker_stream(
        self,
        agent_id: str,
        stream: Any,
        channel: str,
        *,
        adopted: bool = False,
    ) -> None:
        loop = asyncio.get_running_loop()
        if adopted:
            await self._mark_adopted_task_prepared("stream")
        while True:
            try:
                if adopted:
                    self._adopted_read_attempts += 1
                line = await loop.run_in_executor(self._worker_io_executor, stream.readline)
            except Exception as exc:
                await self._record(
                    "error",
                    agent_id=agent_id,
                    state="failed",
                    tool=f"worker_{channel}",
                    target="vds://worker",
                    error=f"{type(exc).__name__}: {exc}",
                )
                return
            if not line:
                return
            try:
                payload = decode_message(line)
                if payload.get("kind") != "event":
                    raise ValueError("worker output is not an event")
            except Exception:
                await self._record(
                    "worker_output",
                    agent_id=agent_id,
                    state="running",
                    tool=f"worker_{channel}",
                    target="vds://worker",
                    working_note=f"Worker {channel} çıktısı alındı.",
                    error=line.strip()[:4000],
                )
                continue
            if not payload.get("agent_id"):
                payload["agent_id"] = agent_id
            await self._ingest_worker_event(payload)
    async def _ingest_worker_event(self, payload: dict[str, Any]) -> None:
        agent_id = str(payload.get("agent_id", ""))
        handle = self._handles.get(agent_id)
        event_type = str(payload.get("event_type", "worker_event"))
        if handle and handle.hard_kill_requested and event_type in {"agent_stopping", "agent_stopped"}:
            payload["operator_action"] = payload.get("operator_action") or "hard_kill"
        event = self.store.append_event(payload)
        await self._publish(event)

    async def _watch_process(
        self,
        handle: WorkerHandle,
        *,
        adopted: bool = False,
    ) -> None:
        loop = asyncio.get_running_loop()
        if adopted:
            await self._mark_adopted_task_prepared("watcher")
        if handle.adopted:
            if handle.starttime_ticks is None:
                return
            exited = await loop.run_in_executor(
                self._worker_io_executor,
                partial(
                    wait_for_pid_exit,
                    handle.pid,
                    int(handle.starttime_ticks),
                    pidfd=handle.pidfd,
                ),
            )
            if not exited or self._handles.get(handle.agent_id) is not handle:
                return
            agent = self.store.get_agent(handle.agent_id) or {}
            self._handles.pop(handle.agent_id, None)
            self._close_adopted_streams(handle)
            if handle.hard_kill_requested or agent.get("state") == "killed":
                return
            await self._record(
                "agent_exit_uncertain",
                agent_id=handle.agent_id,
                job_id=agent.get("job_id", ""),
                pid=handle.pid,
                process_group=handle.process_group,
                state="unknown",
                tool="process_runtime",
                target="vds://worker",
                working_note="Devralınan VDS worker prosesi çıktı; adopted süreçte exit code mevcut değil.",
                next_action="operator inspect",
                error="adopted worker exit code unavailable",
            )
            return
        if handle.process is None:
            return
        return_code = await loop.run_in_executor(self._worker_io_executor, handle.process.wait)
        if self._handles.get(handle.agent_id) is not handle:
            return
        agent = self.store.get_agent(handle.agent_id) or {}
        self._handles.pop(handle.agent_id, None)
        if handle.hard_kill_requested or agent.get("state") == "killed":
            return
        state = "completed" if return_code == 0 else "failed"
        await self._record(
            "agent_exited",
            agent_id=handle.agent_id,
            job_id=agent.get("job_id", ""),
            pid=handle.pid,
            process_group=handle.process_group,
            state=state,
            tool="process_runtime",
            target="vds://worker",
            working_note=f"Worker prosesi çıktı: code={return_code}.",
            next_action="operator inspect" if state == "failed" else "none",
            error=None if return_code == 0 else f"exit code {return_code}",
        )

    async def _signal_group(self, handle: WorkerHandle, sig: signal.Signals) -> None:
        if not self._handle_is_alive(handle):
            return
        try:
            if handle.process_group == os.getpgrp():
                raise RuntimeError("refusing to signal supervisor process group")
            os.killpg(handle.process_group, sig)
        except ProcessLookupError:
            return

    async def _revoke_evidence_lease(
        self,
        agent_id: str,
        reason: str,
        *,
        required: bool,
    ) -> dict[str, Any]:
        try:
            result = dict(await asyncio.to_thread(request_video_revoke, self.root, agent_id, reason))
            completion = result.get("completion")
            if isinstance(completion, dict):
                await self._record_evidence_completion(completion)
            return result
        except TimeoutError as exc:
            await self._record(
                "evidence_lease_revoke_timeout",
                agent_id=agent_id,
                state="degraded",
                tool="evidence_control",
                target="vds://evidence/lease",
                error=str(exc),
                operator_action=reason,
                next_action="evidence service recovery",
            )
            if required:
                raise RuntimeError(f"evidence lease revoke failed before {reason}") from exc
            return {}

    async def _pause(self, command: dict[str, Any]) -> dict[str, Any]:
        agent_id = str(command.get("agent_id", ""))
        agent = self._agent_or_error(agent_id)
        handle = self._handles.get(agent_id)
        if not handle or not self._handle_is_alive(handle):
            raise RuntimeError(f"no live VDS worker for {agent_id}")
        revoke = await self._revoke_evidence_lease(agent_id, "operator_pause", required=True)
        await self._signal_group(handle, signal.SIGSTOP)
        updated = self.store.update_agent(agent_id, state="paused", next_action="operator resume")
        await self._record(
            "agent_paused",
            agent_id=agent_id,
            job_id=agent.get("job_id", ""),
            pid=handle.pid,
            process_group=handle.process_group,
            state="paused",
            tool="process_control",
            target="vds://worker",
            working_note="VDS process-group SIGSTOP ile duraklatıldı.",
            operator_action="pause",
            next_action="operator resume",
        )
        return {
            "agent": updated,
            "state": "paused",
            "pid": handle.pid,
            "process_group": handle.process_group,
            "evidence_video_ref": revoke.get("video_ref"),
            "evidence_video_provenance_ref": revoke.get("video_provenance_ref"),
        }

    async def _resume(self, command: dict[str, Any]) -> dict[str, Any]:
        agent_id = str(command.get("agent_id", ""))
        agent = self._agent_or_error(agent_id)
        handle = self._handles.get(agent_id)
        if not handle or not self._handle_is_alive(handle):
            raise RuntimeError(f"no live VDS worker for {agent_id}")
        video_request_id = await asyncio.to_thread(restore_video_demand, self.root, agent_id, handle.pid)
        await self._signal_group(handle, signal.SIGCONT)
        updated = self.store.update_agent(agent_id, state="running", next_action="worker runtime")
        await self._record(
            "agent_resumed",
            agent_id=agent_id,
            job_id=agent.get("job_id", ""),
            pid=handle.pid,
            process_group=handle.process_group,
            state="running",
            tool="process_control",
            target="vds://worker",
            working_note="VDS process-group SIGCONT ile devam ettirildi.",
            operator_action="resume",
            next_action="worker runtime",
        )
        return {
            "agent": updated,
            "state": "running",
            "pid": handle.pid,
            "process_group": handle.process_group,
            "video_demand_request_id": video_request_id,
        }

    async def _intervene(self, command: dict[str, Any]) -> dict[str, Any]:
        agent_id = str(command.get("agent_id", "")).strip()
        agent = self._agent_or_error(agent_id)
        if agent.get("state") in TERMINAL_STATES or not agent.get("visible", True):
            raise RuntimeError(f"terminal agent cannot receive intervention: {agent_id}")
        instruction = str(command.get("instruction", "")).strip()
        if not instruction:
            raise ValueError("operator intervention instruction is empty")
        context = command.get("context")
        directive = self.store.append_operator_directive(
            agent_id,
            instruction,
            context=context if isinstance(context, dict) else None,
        )
        await self._record(
            "operator_intervention",
            agent_id=agent_id,
            job_id=agent.get("job_id", ""),
            state=str(agent.get("state", "created")),
            tool="operator_control",
            target="vds://agent/directives",
            working_note="Operatör yönlendirmesi VDS mailbox'a kalıcı olarak yazıldı.",
            operator_action="intervene",
            directive=directive,
            intervention_id=directive.get("intervention_id", new_id("intervention")),
            next_action="Worker bir sonraki AI kararında yönlendirmeyi okuyacak",
        )
        return {
            "agent": self.store.get_agent(agent_id),
            "agent_id": agent_id,
            "intervention_id": directive["intervention_id"],
            "state": agent.get("state"),
            "instruction_recorded": True,
        }

    async def _hard_kill(self, command: dict[str, Any]) -> dict[str, Any]:
        agent_id = str(command.get("agent_id", ""))
        agent = self._agent_or_error(agent_id)
        handle = self._handles.get(agent_id)
        if not handle:
            await self._revoke_evidence_lease(agent_id, "operator_hard_kill", required=False)
            pid = agent.get("pid")
            process_group = agent.get("process_group")
            if process_group:
                try:
                    os.killpg(int(process_group), signal.SIGKILL)
                except ProcessLookupError:
                    pass
            updated = self.store.update_agent(agent_id, state="killed", next_action="none")
            await self._record(
                "agent_killed",
                agent_id=agent_id,
                job_id=agent.get("job_id", ""),
                pid=pid,
                process_group=process_group,
                state="killed",
                tool="process_control",
                target="vds://worker",
                working_note="Kayıtlı uzak process group artık supervisor belleğinde yok; kill kanıtı kaydedildi.",
                operator_action=command.get("reason", "operator"),
                next_action="none",
            )
            return {"agent": updated, "state": "killed", "pid": pid, "process_group": process_group}

        handle.hard_kill_requested = True
        await self._record(
            "hard_kill_requested",
            agent_id=agent_id,
            job_id=agent.get("job_id", ""),
            pid=handle.pid,
            process_group=handle.process_group,
            state="stopping",
            tool="process_control",
            target="vds://worker",
            working_note="Operatör VDS process-group için sert sonlandırma istedi.",
            operator_action=command.get("reason", "operator"),
            next_action="SIGTERM then SIGKILL if needed",
        )
        revoke = await self._revoke_evidence_lease(agent_id, "operator_hard_kill", required=False)
        await self._signal_group(handle, signal.SIGTERM)
        if not await self._wait_for_handle_exit(handle, 2.0):
            await self._signal_group(handle, signal.SIGKILL)
            if not await self._wait_for_handle_exit(handle, 2.0):
                raise RuntimeError(f"VDS worker did not exit: {agent_id}")
        await asyncio.sleep(0)
        self._handles.pop(agent_id, None)
        self._close_adopted_streams(handle)
        updated = self.store.update_agent(agent_id, state="killed", next_action="none")
        await self._record(
            "agent_killed",
            agent_id=agent_id,
            job_id=agent.get("job_id", ""),
            pid=handle.pid,
            process_group=handle.process_group,
            state="killed",
            tool="process_control",
            target="vds://worker",
            working_note=(
                "VDS adopted worker process-group sonlandırıldı; süreç kimliği kapandı."
                if handle.adopted
                else "VDS worker process-group sonlandırıldı; PID process wait ile kapandı."
            ),
            operator_action=command.get("reason", "operator"),
            next_action="none",
        )
        return {
            "agent": updated,
            "state": "killed",
            "pid": handle.pid,
            "process_group": handle.process_group,
            "evidence_video_ref": revoke.get("video_ref"),
            "evidence_video_provenance_ref": revoke.get("video_provenance_ref"),
        }

    async def _destroy(self, command: dict[str, Any]) -> dict[str, Any]:
        agent_id = str(command.get("agent_id", ""))
        agent = self._agent_or_error(agent_id)
        if agent_id in self._handles and self._handle_is_alive(self._handles[agent_id]):
            raise RuntimeError("live VDS worker must be hard_killed before destroy")
        if agent.get("state") in {"running", "paused"}:
            raise RuntimeError("running or paused agent must be hard_killed before destroy")
        updated = self.store.remove_agent(agent_id)
        await self._record(
            "agent_destroyed",
            agent_id=agent_id,
            job_id=agent.get("job_id", ""),
            pid=agent.get("pid"),
            process_group=agent.get("process_group"),
            state="destroyed",
            tool="process_control",
            target="vds://agent",
            working_note="Ajan aktif görünümden kaldırıldı; event ve manifest korunuyor.",
            operator_action="destroy",
            next_action="replay",
        )
        return {"agent": updated, "state": "destroyed"}

    def _replay(self, command: dict[str, Any]) -> dict[str, Any]:
        agent_id = str(command.get("agent_id", "") or "") or None
        after_seq = int(command.get("after_seq", 0) or 0)
        return {
            "events": self.store.events_after(after_seq, agent_id),
            "last_seq": self.store.last_seq,
        }

    def _viewport(self, command: dict[str, Any]) -> dict[str, Any]:
        agent_id = str(command.get("agent_id", ""))
        agent = self._agent_or_error(agent_id)
        agent_dir = self.root / "agents" / agent_id
        historical_capability = dict(agent.get("display_capability") or {})
        current_capability = read_capability(self.root)
        def artifact_exists(ref: str | None) -> bool:
            if not ref:
                return False
            prefix = f"agent://{agent_id}/"
            if not str(ref).startswith(prefix):
                return False
            relative = str(ref)[len(prefix):]
            path = agent_dir / relative
            try:
                path.resolve().relative_to(agent_dir.resolve())
            except ValueError:
                return False
            return path.is_file()

        return {
            "agent_id": agent_id,
            "manifest_ref": f"agent://{agent_id}/manifest.json",
            "frames_ref": f"agent://{agent_id}/frames/",
            "video_ref": f"agent://{agent_id}/video/",
            "capture_kind": str(agent.get("capture_kind", "sway-headless")),
            "display_capability": historical_capability,
            "current_display_capability": current_capability,
            "display_control": read_display_state(self.root),
            "wayvnc_stream_ref": agent.get("wayvnc_stream_ref") or current_capability.get("wayvnc_stream_ref"),
            "frames_available": artifact_exists(agent.get("last_frame_ref")),
            "video_available": artifact_exists(agent.get("last_video_ref")),
            "real_frame_available": bool(current_capability.get("real_frame_available")),
            "video_capture_available": bool(current_capability.get("video_capture_available")),
            "wayvnc_available": bool(
                current_capability.get("wayvnc_loopback_ready")
                and current_capability.get("wayvnc_running")
            ),
            "live_view_available": bool(current_capability.get("ready")),
            "last_frame_ref": agent.get("last_frame_ref"),
            "last_frame_provenance_ref": agent.get("last_frame_provenance_ref"),
            "last_frame_event_id": agent.get("last_frame_event_id"),
            "last_frame_render_revision": agent.get("last_frame_render_revision"),
            "last_video_ref": agent.get("last_video_ref"),
            "last_video_provenance_ref": agent.get("last_video_provenance_ref"),
            "last_output_ref": agent.get("last_output_ref"),
            "last_evidence_refs": list(agent.get("last_evidence_refs", []) or []),
            "last_result_summary": agent.get("last_result_summary"),
            "operator_directives": list(agent.get("operator_directives", []) or [])[-20:],
        }

    async def _display_select(self, command: dict[str, Any]) -> dict[str, Any]:
        agent_id = str(command.get("agent_id", "")).strip()
        self._agent_or_error(agent_id)
        selection = await asyncio.to_thread(select_display_agent, self.root, agent_id)
        capability = read_capability(self.root)
        render_error = None
        if capability.get("ready"):
            render_error = await asyncio.to_thread(wait_for_display_render, self.root, agent_id)
        return {
            "agent_id": agent_id,
            "selected_agent_id": agent_id,
            "selection_id": selection["selection_id"],
            "preempted_video_ref": selection.get("preempted_video_ref"),
            "preempted_video_provenance_ref": (
                selection.get("completion") or {}
            ).get("video_provenance_ref"),
            "preempted_completion": selection.get("completion"),
            "capture_kind": "sway-headless",
            "display_capability": capability,
            "display_control": read_display_state(self.root),
            "live_view_available": bool(capability.get("ready") and not render_error),
            "display_render_error": render_error,
        }

    async def _display_release(self, _command: dict[str, Any]) -> dict[str, Any]:
        selection = await asyncio.to_thread(select_display_agent, self.root, None)
        return {
            "selected_agent_id": None,
            "selection_id": selection["selection_id"],
            "capture_kind": "sway-headless",
            "display_capability": read_capability(self.root),
            "display_control": read_display_state(self.root),
            "live_view_available": False,
        }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="PaidProxy VDS agent supervisor")
    parser.add_argument("--root", default="var/agentd")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--handover-socket")
    parser.add_argument("--old-agentd-pid", type=int)
    parser.add_argument(
        "--handover-prepare-only",
        action="store_true",
        help="prepare a real handover without commit, activation, or command serving",
    )
    return parser


async def async_main(args: argparse.Namespace) -> None:
    if bool(args.handover_socket) != (args.old_agentd_pid is not None):
        raise HandoverError("--handover-socket and --old-agentd-pid must be supplied together")
    if args.handover_prepare_only and not args.handover_socket:
        raise HandoverError("--handover-prepare-only requires --handover-socket")
    if args.handover_prepare_only and args.port == 8787:
        raise HandoverError("--handover-prepare-only requires an alternate port, use --port 0")
    supervisor = Supervisor(
        args.root,
        args.host,
        args.port,
        handover_socket=args.handover_socket,
        handover_old_agentd_pid=args.old_agentd_pid,
        prepare_only=args.handover_prepare_only,
    )
    try:
        if args.handover_prepare_only:
            await supervisor.start()
            print(json.dumps(supervisor.handover_prepare_summary(), ensure_ascii=False, sort_keys=True))
            return
        await supervisor.serve_forever()
    except (asyncio.CancelledError, KeyboardInterrupt):
        pass
    finally:
        await supervisor.stop()


def main() -> int:
    args = build_parser().parse_args()
    try:
        asyncio.run(async_main(args))
    except KeyboardInterrupt:
        return 130
    except HandoverError as exc:
        print(f"handover failed: {exc}", file=sys.stderr)
        return 2
    return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
