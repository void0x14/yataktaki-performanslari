import pytest
from proxy_pipeline.persistence.payloads import PayloadStore

def test_payload_checksum_detects_tampering(tmp_path):
    store=PayloadStore(tmp_path); ref=store.put({"safe": True})
    path=tmp_path/f"{ref}.zst"
    if not path.exists():
        path=tmp_path/f"{ref}.json.gz"
    path.write_bytes(b"bad")
    with pytest.raises(Exception): store.get(ref)
