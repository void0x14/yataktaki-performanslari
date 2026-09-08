from proxy_pipeline.persistence.db import connect
from proxy_pipeline.persistence.writer import DBWriter


def test_prefix_metadata_batch_insert(tmp_path):
    db = connect(tmp_path / "pipeline.sqlite3")
    writer = DBWriter(db)
    for i in range(256):
        writer.write_prefix(f"198.51.{i}.0/24", 64500 + i)
    count = db.execute("select count(*) as n from prefixes").fetchone()["n"]
    assert count == 256
