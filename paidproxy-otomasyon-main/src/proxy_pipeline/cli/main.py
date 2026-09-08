from __future__ import annotations

from pathlib import Path
import json

import typer

from proxy_pipeline.persistence.db import connect, integrity_check, quick_check, wal_checkpoint
from proxy_pipeline.ops import BackupManager

app = typer.Typer(
    help="Proxy kesif hatti.  kur | kesfet | tara | panel",
    no_args_is_help=True,
    add_completion=False,
)

DEFAULT_DB = Path("var/db/pipeline.sqlite3")


@app.command("kur")
@app.command("init-db")
def init_db(path: Path = typer.Argument(DEFAULT_DB, help="SQLite yolu")) -> None:
    """Veritabanini kur. Bir kere yeter."""
    db = connect(path)
    db.close()
    typer.echo(str(path))


@app.command("check-db")
def check_db(path: Path = typer.Argument(DEFAULT_DB)) -> None:
    db = connect(path)
    typer.echo(json.dumps({"quick_check": quick_check(db), "integrity_check": integrity_check(db)}))
    db.close()


@app.command("checkpoint")
def checkpoint(path: Path = typer.Argument(DEFAULT_DB)) -> None:
    db = connect(path)
    wal_checkpoint(db)
    db.close()
    typer.echo("ok")


@app.command("backup")
def backup(database: Path = DEFAULT_DB, root: Path = Path("var/backup"), name: str = "snapshot.sqlite3") -> None:
    manager = BackupManager(database, root)
    target = manager.snapshot(name)
    typer.echo(str(target))


@app.command("panel")
@app.command("serve")
def serve(host: str = "0.0.0.0", port: int = 8080) -> None:
    """Operator paneli. Tarama yapmaz."""
    import uvicorn

    from proxy_pipeline.api.app import create_app
    from proxy_pipeline.bootstrap import build_control_plane

    uvicorn.run(create_app(build_control_plane()), host=host, port=port)


@app.command("tara")
def tara(
    cidr: str = typer.Argument(..., help="Taranacak CIDR, ornek: 1.1.1.0/24"),
    ports: str = typer.Option("3128,8080,1080,80,8888", "--ports", "-p", help="Virgulle port listesi"),
    rate: int = typer.Option(1000, "--rate", help="masscan --rate"),
    masscan_bin: str = typer.Option("masscan", "--masscan-bin", help="masscan programinin yolu"),
    cikti: Path = typer.Option(Path("var/spool/l4-open.txt"), "--cikti", help="Acik portlarin yazilacagi dosya"),
    dry_run: bool = typer.Option(False, "--dry-run", help="masscan calistirma, komutu yaz"),
) -> None:
    """Masscan ile L4 tarama. masscan bu repoda yok; makinede kurulu olmali."""
    from proxy_pipeline.safety import KillSwitch, RunGate
    from proxy_pipeline.scanners.adapter import MasscanAdapter
    from proxy_pipeline.scanners.runner import MasscanRunner, operator_manifest, write_events

    port_tuple = tuple(int(p.strip()) for p in ports.split(",") if p.strip())
    if not port_tuple:
        raise typer.BadParameter("en az bir port ver")
    manifest = operator_manifest(cidr, port_tuple)
    adapter = MasscanAdapter(RunGate(KillSwitch()))
    runner = MasscanRunner(adapter, binary=masscan_bin)
    cmd = runner.command(manifest, rate=rate)
    if dry_run:
        typer.echo(" ".join(cmd))
        return
    events = runner.run(manifest, rate=rate)
    write_events(cikti, events)
    typer.echo(json.dumps({"acik": len(events), "cikti": str(cikti), "komut": cmd}, ensure_ascii=True))


@app.command("kesfet")
def kesfet(
    aday: str = typer.Argument(..., help="Aday kimligi, ornek: as64500 veya 1.2.3.0/24"),
    kanit: str = typer.Option("{}", "--kanit", help="JSON kanit/snapshot"),
    tara_hemen: bool = typer.Option(False, "--tara", help="Karardaki CIDR'leri masscan ile tara"),
) -> None:
    """Asama 1: ajan hedef secer. Ajan yoksa durur, uydurma skor yok."""
    from proxy_pipeline.bootstrap import build_control_plane
    from proxy_pipeline.decision.service import DecisionBlocked
    from proxy_pipeline.domain.models import DecisionContext

    try:
        snapshot = json.loads(kanit)
    except json.JSONDecodeError as exc:
        raise typer.BadParameter("kanit JSON olmali") from exc
    snapshot.setdefault("aday", aday)
    plane = build_control_plane()
    context = DecisionContext(
        "aday",
        aday,
        snapshot,
        plane.strategy_version,
        plane.modes.get().version,
    )
    try:
        record, manifest = plane.request_decision(context)
    except DecisionBlocked as exc:
        typer.echo("AJAN YOK. Tak: src/proxy_pipeline/agents/tak.py  veya  PIPELINE_AJAN")
        raise typer.Exit(code=2) from exc
    decision = record.decision
    payload = {
        "durum": record.state.value,
        "karar": decision.action.value if decision else None,
        "hedefler": [{"cidr": t.cidr, "ports": list(t.ports)} for t in (decision.targets if decision else ())],
        "manifest": manifest.manifest_id if manifest else None,
    }
    typer.echo(json.dumps(payload, ensure_ascii=True))
    if tara_hemen and manifest:
        from proxy_pipeline.safety import KillSwitch, RunGate
        from proxy_pipeline.scanners.adapter import MasscanAdapter
        from proxy_pipeline.scanners.runner import MasscanRunner, write_events

        runner = MasscanRunner(MasscanAdapter(RunGate(KillSwitch())))
        events = runner.run(manifest)
        write_events(Path("var/spool/l4-open.txt"), events)
        typer.echo(json.dumps({"acik": len(events)}, ensure_ascii=True))


def main() -> None:
    app()


if __name__ == "__main__":
    main()
