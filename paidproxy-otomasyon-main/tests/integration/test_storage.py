from proxy_pipeline.persistence.db import connect

def test_sqlite_wal_schema(tmp_path):
    db=connect(tmp_path/"pipeline.sqlite3")
    assert db.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    tables={r[0] for r in db.execute("select name from sqlite_master where type='table'")}
    assert {"agent_decisions","execution_manifests","state_events"} <= tables
