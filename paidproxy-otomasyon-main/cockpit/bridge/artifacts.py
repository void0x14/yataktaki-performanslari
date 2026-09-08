"""Güvenli VDS artifact alıcısı.

Event içindeki agent:// referansları yalnız seçili ajan namespace'inde
çözümlenir; referans hiçbir zaman shell komutu olarak yürütülmez.
"""
from __future__ import annotations

from hashlib import sha256
import os
from pathlib import Path
from typing import Any

from cockpit.bridge.vds import VDSConfig, artifact_parts, copy_artifact


class ArtifactCache:
    def __init__(self, config: VDSConfig, root: Path | None = None) -> None:
        data_root = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
        self.root = (root or data_root / "paidproxy" / "artifacts").expanduser().resolve()
        self.config = config

    def local_path(self, ref: str, agent_id: str) -> Path:
        _agent_id, relative = artifact_parts(ref, agent_id)
        path = self.root / agent_id / relative
        try:
            path.resolve().relative_to((self.root / agent_id).resolve())
        except ValueError as exc:
            raise ValueError("artifact cache path escaped agent cache") from exc
        return path

    def has(self, ref: str, agent_id: str) -> bool:
        try:
            return self.local_path(ref, agent_id).is_file()
        except ValueError:
            return False

    def fetch(self, ref: str, agent_id: str, *, immutable: bool = True) -> Path:
        if "/video/" in str(ref) and not immutable:
            raise ValueError("mutable video ref is not downloadable")
        destination = self.local_path(ref, agent_id)
        if destination.is_file():
            return destination
        temporary = destination.with_name(f".{destination.name}.{sha256(ref.encode()).hexdigest()[:10]}.part")
        copy_artifact(self.config, ref, temporary, agent_id=agent_id)
        os.replace(temporary, destination)
        return destination

    def frame_paths(self, agent_id: str) -> list[Path]:
        directory = self.root / agent_id / "frames"
        return sorted(directory.glob("frame-*.png"))[-12:] if directory.is_dir() else []

    def cached_refs(self, agent_id: str) -> list[str]:
        directory = self.root / agent_id
        if not directory.is_dir():
            return []
        return [
            f"agent://{agent_id}/{path.relative_to(directory).as_posix()}"
            for path in sorted(directory.rglob("*"))
            if path.is_file() and not path.name.endswith(".part")
        ]
