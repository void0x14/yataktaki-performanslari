from __future__ import annotations

from pathlib import Path

from proxy_pipeline.domain.models import ExecutionManifest
from proxy_pipeline.queue.segments import Segment, write_segment_items


def materialize_manifest(manifest: ExecutionManifest, root: Path) -> Segment:
    """Split a committed manifest into a durable disk segment. Segmentation size is storage, not ranking."""
    root.mkdir(parents=True, exist_ok=True)
    items = []
    for target in manifest.targets:
        ports = target.ports or (0,)
        for port in ports:
            items.append(
                {
                    "cidr": target.cidr,
                    "port": port,
                    "protocols": list(target.protocols),
                    "asn": target.asn,
                    "prefix": target.prefix,
                    "sample_approach": target.sample_approach,
                    "decision_id": manifest.decision_id,
                    "manifest_id": manifest.manifest_id,
                }
            )
    path = root / f"{manifest.manifest_id}.seg.zst"
    checksum = write_segment_items(path, items)
    return Segment(
        segment_id=manifest.manifest_id,
        manifest_id=manifest.manifest_id,
        path=path,
        item_count=len(items),
        checksum_value=checksum,
    )
