from __future__ import annotations

from typing import Any

from proxy_pipeline.auth import Authorizer


def create_app(service=None, authorizer: Authorizer | None = None):
    if service is None:
        from proxy_pipeline.bootstrap import build_control_plane

        service = build_control_plane()
    try:
        from fastapi import FastAPI, Header, HTTPException
        from fastapi.responses import HTMLResponse, PlainTextResponse
    except ImportError as exc:
        raise RuntimeError("FastAPI is required for the operator API") from exc

    from proxy_pipeline.ui.pages import render

    app = FastAPI(title="Proxy Pipeline", version="0.1.0")
    gate = authorizer or Authorizer()

    def actor(x_operator: str | None) -> str:
        return x_operator or "operator"

    def require(x_operator: str | None, permission: str) -> None:
        try:
            gate.require(actor(x_operator), permission)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/metrics")
    def metrics():
        if service and hasattr(service, "metrics"):
            return PlainTextResponse(service.metrics.prometheus(), media_type="text/plain")
        return PlainTextResponse("proxy_pipeline_up 1\n")

    @app.get("/api/modes")
    def modes(x_operator: str | None = Header(default=None)):
        require(x_operator, "read")
        if not service:
            return {"modes": []}
        return {
            "active": getattr(service.modes, "active", None),
            "modes": [m.__dict__ for m in service.modes.list()],
        }

    @app.post("/api/modes/{name}/activate")
    def activate_mode(name: str, x_operator: str | None = Header(default=None)):
        require(x_operator, "mode")
        if not service:
            raise HTTPException(404, "no control plane")
        service.modes.activate(name)
        return {"active": name, "version": service.modes.get(name).version}

    @app.get("/api/sources")
    def sources(x_operator: str | None = Header(default=None)):
        require(x_operator, "read")
        if not service:
            return {"sources": []}
        return {"sources": [m.__dict__ for m in service.catalog.describe()]}


    @app.get("/api/decisions")
    def decisions(x_operator: str | None = Header(default=None)):
        require(x_operator, "read")
        if not service:
            return {"decisions": []}
        rows = []
        for record in service.decisions.by_id.values():
            decision = record.decision
            rows.append(
                {
                    "decision_id": decision.decision_id if decision else None,
                    "state": record.state.value,
                    "action": decision.action.value if decision else None,
                    "reused": record.reused,
                    "targets": [t.cidr for t in decision.targets] if decision else [],
                }
            )
        return {"decisions": rows}

    @app.post("/api/kill")
    def kill(reason: str = "operator", x_operator: str | None = Header(default=None)):
        require(x_operator, "kill")
        if not service:
            raise HTTPException(404, "no control plane")
        service.kill_switch.trigger(reason)
        return {"active": True, "reason": reason}

    @app.post("/api/feedback")
    def feedback(payload: dict[str, Any], x_operator: str | None = Header(default=None)):
        require(x_operator, "feedback")
        if not service:
            raise HTTPException(404, "no control plane")
        item = service.feedback.record(
            payload["decision_id"],
            actor(x_operator),
            payload.get("approval", "noted"),
            payload.get("correction"),
            payload.get("reason", ""),
            payload.get("before_action"),
            payload.get("after_action"),
        )
        return item.__dict__

    screens = {
        "/": "mission",
        "/decisions": "decisions",
        "/modes": "modes",
        "/sources": "sources",
        "/candidates": "candidates",
        "/endpoints": "endpoints",
        "/lab": "lab",
        "/feedback": "feedback",
        "/audit": "audit",
        "/safety": "safety",
    }

    for path, name in screens.items():

        def page(name=name):
            require("operator", "read")
            return HTMLResponse(render(name, service))

        page.__name__ = f"page_{name}"
        app.add_api_route(path, page, methods=["GET"], response_class=HTMLResponse)

    return app
