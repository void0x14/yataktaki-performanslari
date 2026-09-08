from __future__ import annotations

from html import escape

SCREENS = [
    ("/", "Mission Control"),
    ("/decisions", "Decision Cockpit"),
    ("/modes", "Mode Studio"),
    ("/sources", "Source Intelligence"),
    ("/candidates", "Candidate Portfolio"),
    ("/endpoints", "Endpoint Inventory"),
    ("/lab", "Comparison Lab"),
    ("/bulgular", "Bulgular"),
    ("/audit", "Audit Explorer"),
    ("/safety", "Kill Switch"),
]


def _nav(active: str) -> str:
    links = []
    for href, label in SCREENS:
        cls = "active" if label.split()[0].lower() in active else ""
        links.append(f'<a class="{cls}" href="{href}">{escape(label)}</a>')
    return "".join(links)


def render(name: str, service=None) -> str:
    body = BODY.get(name, lambda _s: "<p>unknown screen</p>")(service)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <title>Proxy Pipeline — {escape(name)}</title>
  <style>
    :root {{ font-family: ui-sans-serif, system-ui, sans-serif; background:#0b1020; color:#e8eefc; }}
    body {{ margin:0; }}
    header {{ display:flex; justify-content:space-between; padding:1rem 1.5rem; background:#121a33; border-bottom:1px solid #243056; }}
    nav a {{ color:#9db0e0; margin-right:1rem; text-decoration:none; }}
    nav a.active {{ color:#fff; font-weight:600; }}
    main {{ padding:1.5rem; }}
    .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); gap:1rem; }}
    .card {{ background:#162044; padding:1rem; border-radius:12px; border:1px solid #2a3b6a; }}
    table {{ width:100%; border-collapse:collapse; }}
    th,td {{ text-align:left; padding:.5rem; border-bottom:1px solid #2a3b6a; }}
    .warn {{ color:#ffb4b4; }}
  </style>
  <script src="https://unpkg.com/htmx.org@2.0.4"></script>
</head>
<body>
  <header><strong>Proxy Pipeline</strong><nav>{_nav(name)}</nav></header>
  <main>{body}</main>
</body>
</html>"""


def _cards(items: list[tuple[str, str]]) -> str:
    return '<div class="grid">' + "".join(f'<div class="card"><h3>{escape(k)}</h3><p>{escape(v)}</p></div>' for k, v in items) + "</div>"


def mission(service) -> str:
    metrics = service.metrics.snapshot() if service else {}
    return "<h1>Mission Control</h1>" + _cards(
        [
            ("Throughput", str(metrics.get("manifests_committed", 0))),
            ("Blocked decisions", str(metrics.get("decision_blocked", 0))),
            ("Decisions", str(len(service.decisions.by_id) if service else 0)),
            ("Kill switch", "ACTIVE" if service and service.kill_switch.active else "clear"),
        ]
    )


def decisions(service) -> str:
    rows = []
    if service:
        for record in service.decisions.by_id.values():
            d = record.decision
            rows.append(
                f"<tr><td>{escape(d.decision_id if d else '')}</td><td>{escape(record.state.value)}</td>"
                f"<td>{escape(d.action.value if d else '')}</td><td>{escape(str(d.confidence if d else ''))}</td></tr>"
            )
    return "<h1>Decision Cockpit</h1><table><tr><th>ID</th><th>State</th><th>Action</th><th>Confidence</th></tr>" + "".join(rows) + "</table>"


def modes(service) -> str:
    items = service.modes.list() if service else []
    rows = "".join(f"<tr><td>{escape(m.name)}</td><td>{escape(m.mode_type)}</td><td>{escape(m.version)}</td></tr>" for m in items)
    return "<h1>Mode Studio</h1><table><tr><th>Name</th><th>Type</th><th>Version</th></tr>" + rows + "</table>"


def sources(service) -> str:
    items = service.catalog.describe() if service else []
    rows = "".join(
        f"<tr><td>{escape(m.name)}</td><td>{escape(m.license_note)}</td><td>{escape(m.health)}</td><td>{'yes' if m.enabled else 'no'}</td></tr>"
        for m in items
    )
    return "<h1>Source Intelligence</h1><table><tr><th>Name</th><th>License</th><th>Health</th><th>Enabled</th></tr>" + rows + "</table>"


def candidates(_service) -> str:
    return "<h1>Candidate Portfolio</h1><p>ASN/prefix candidates, last context, decision and realized value.</p>"


def endpoints(_service) -> str:
    return "<h1>Endpoint Inventory</h1><p>Protocol, exit, IPv4/IPv6, rotation class and freshness.</p>"


def lab(_service) -> str:
    return "<h1>Comparison Lab</h1><p>Mode/model/prompt shadow and replay comparison.</p>"


def feedback(_service) -> str:
    return "<h1>Bulgular</h1><p>Doğrulanan bulgular burada listelenir.</p>"


def audit(_service) -> str:
    return (
        "<h1>Audit Explorer</h1>"
        "<p>Karar, manifest, tarama ve doğrulama zincirinin olay kayıtları burada incelenir.</p>"
    )


def safety(service) -> str:
    return (
        "<h1>Kill Switch</h1>"
        + _cards(
            [
                ("Kill switch", "ACTIVE" if service and service.kill_switch.active else "clear"),
            ]
        )
    )


BODY = {
    "mission": mission,
    "decisions": decisions,
    "modes": modes,
    "sources": sources,
    "candidates": candidates,
    "endpoints": endpoints,
    "lab": lab,
    "feedback": feedback,
    "audit": audit,
    "safety": safety,
}
