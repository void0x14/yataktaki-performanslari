from proxy_pipeline.agents.select import select_routes, BEYIN

def test_havuz_once_yerlesik_sonda(monkeypatch):
    monkeypatch.delenv("PIPELINE_AJAN", raising=False)
    routes, beyin, yedek = select_routes()
    assert yedek is False
    assert BEYIN in beyin
    adlar = [getattr(r, "version", "") for r in routes]
    assert adlar[0] == "havuz-beyin-1"
    assert adlar[-1] == "yerlesik-beyin-1"

def test_havuz_yanit_vermezse_zincir_surer(tmp_path, monkeypatch):
    import proxy_pipeline.agents.ai_havuz as H
    def patlayan(self, context):
        raise RuntimeError("yapay zekâ havuzu yanıt vermiyor")
    monkeypatch.setattr(H.HavuzBeyni, "decide", patlayan)
    from proxy_pipeline.decision.service import DecisionService
    from proxy_pipeline.domain.models import DecisionContext
    routes, _, _ = select_routes(journal=tmp_path)
    svc = DecisionService(routes=routes)
    rec = svc.decide(DecisionContext("aday", "r1", {"cidr": "198.51.100.0/24", "scent": "squid cache hosting"}, "s", "m"), fresh=True)
    assert rec.decision.action.value == "sample"

def test_saglayici_listesi_yalnizca_mimo_ve_gemini(monkeypatch, tmp_path):
    import proxy_pipeline.agents.ai_havuz as H

    keys = tmp_path / "keys.txt"
    keys.write_text(
        "\n".join([
            "MIMO_API_KEY=mimo-test",
            "MIMO_BASE_URL=http://mimo.test/v1",
            "GEMINI_WEB2API_API_KEY=gemini-test",
            "MIMO_MODEL=wrong-model-is-ignored",
            "GEMINI_WEB2API_MODEL=wrong-model-is-ignored",
            "OPENROUTER_API_KEY=must-not-be-used",
            "NVIDIA_API_KEY=must-not-be-used",
            "DEEPSEEK_API_KEY=must-not-be-used",
            "ZEN_API_KEY=must-not-be-used",
        ]) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(H, "ANAHTAR_DOSYASI", keys)
    monkeypatch.setattr(H, "_YUKLENDI", False)

    providers = H.saglayicilar()

    assert [provider["ad"] for provider in providers] == ["mimo", "gemini-web2api"]
    assert [provider["model"] for provider in providers] == [
        "mimo-v2.5-pro",
        "gemini-3.5-flash-thinking-lite",
    ]
    assert all(provider["ad"] not in {"openrouter", "nvidia", "deepseek", "zen"}
               for provider in providers)


def test_mimo_token_plan_cin_endpointini_kullanir(monkeypatch, tmp_path):
    import proxy_pipeline.agents.ai_havuz as H

    keys = tmp_path / "keys.txt"
    keys.write_text("MIMO_API_KEY=tp-test-token\n", encoding="utf-8")
    monkeypatch.setattr(H, "ANAHTAR_DOSYASI", keys)
    monkeypatch.setattr(H, "_YUKLENDI", False)

    mimo = next(provider for provider in H.saglayicilar() if provider["ad"] == "mimo")

    assert mimo["taban"] == "https://token-plan-cn.xiaomimimo.com/v1"


@__import__('pytest').mark.havuz_canli
def test_havuz_deep_route_keeps_primary_and_records_second_agent(monkeypatch):
    import proxy_pipeline.agents.ai_havuz as H
    from proxy_pipeline.domain.models import DecisionContext

    providers = [
        {"ad": "mimo", "model": "mimo-v2.5-pro", "taban": "http://mimo", "anahtar": "x"},
        {"ad": "gemini-web2api", "model": "gemini-3.5-flash-thinking-lite", "taban": "http://gemini", "anahtar": ""},
    ]

    monkeypatch.setattr(H, "saglayicilar", lambda: providers)

    def attempt(sag, anlik, context, kaydet):
        return {"action": "research", "targets": [], "provider": sag["ad"], "model": sag["model"],
                "evidence": [], "counter_evidence": [], "alternatives": [], "items": []}

    monkeypatch.setattr(H.HavuzBeyni, "_attempt", staticmethod(attempt))
    out = H.HavuzBeyni().decide(
        DecisionContext("aday", "r10", {"model_tercihi": "derin"}, "s", "m")
    )

    assert out["provider"] == "mimo"
    assert out["review_provider"] == "gemini-web2api"
    assert any("İkinci ajan uyumu" in item for item in out["evidence"])


def test_adaptive_ruflo_route_uses_gemini_for_source_and_mimo_for_execution():
    from proxy_pipeline.agents.ruflo_lite import route_plan
    from proxy_pipeline.domain.models import DecisionContext

    source = DecisionContext("research", "source-1", {"phase": "source"}, "s", "m")
    execution = DecisionContext("aday", "candidate-1", {"phase": "execution"}, "s", "m")

    assert [task.provider for task in route_plan(source).tasks] == ["gemini-web2api"]
    assert [task.provider for task in route_plan(execution).tasks] == ["mimo"]


def test_adaptive_ruflo_route_uses_both_for_deep_review():
    from proxy_pipeline.agents.ruflo_lite import route_plan
    from proxy_pipeline.domain.models import DecisionContext

    context = DecisionContext("aday", "candidate-2", {"model_tercihi": "derin"}, "s", "m")

    assert [task.provider for task in route_plan(context).tasks] == ["mimo", "gemini-web2api"]


@__import__('pytest').mark.havuz_canli
def test_havuz_xiaomi_mimo_uyumlu_sunucudan_karar_alir(monkeypatch, tmp_path):
    import json, threading
    from http.server import BaseHTTPRequestHandler, HTTPServer
    karar = {"action": "sample",
             "targets": [{"cidr": "198.51.100.0/24", "ports": [8080], "protocols": ["http_connect"]}],
             "resource_plan": {}, "stop_condition": {},
             "items": [{"candidate_id": "r9", "action": "sample",
                        "targets": [{"cidr": "198.51.100.0/24", "ports": [8080]}],
                        "order_index": 0, "resource_allocation": {}, "stop_expression": {}}]}
    class El(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200); self.send_header("content-type", "application/json"); self.end_headers()
            self.wfile.write(json.dumps({"data": [{"id": "sinama"}]}).encode())
        def do_POST(self):
            n = int(self.headers.get("content-length", 0)); self.rfile.read(n)
            govde = json.dumps({"choices": [{"message": {"content": json.dumps(karar)}}]}).encode()
            self.send_response(200); self.send_header("content-type", "application/json"); self.end_headers()
            self.wfile.write(govde)
        def log_message(self, *a): pass
    sunucu = HTTPServer(("127.0.0.1", 0), El)
    threading.Thread(target=sunucu.serve_forever, daemon=True).start()
    import proxy_pipeline.agents.ai_havuz as H
    keys = tmp_path / "keys.txt"
    keys.write_text(
        f"MIMO_BASE_URL=http://127.0.0.1:{sunucu.server_port}/v1\nMIMO_API_KEY=mimo-test\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(H, "ANAHTAR_DOSYASI", keys)
    monkeypatch.setattr(H, "_YUKLENDI", False)
    from proxy_pipeline.agents.ai_havuz import HavuzBeyni
    from proxy_pipeline.domain.models import DecisionContext
    out = HavuzBeyni().decide(DecisionContext("aday", "r9", {"cidr": "198.51.100.0/24"}, "s", "m"))
    assert out["action"] == "sample"
    assert out["provider"] == "mimo"
    assert out["model"] == "mimo-v2.5-pro"
    sunucu.shutdown()

def test_uyarlayici_hedef_uydurmaz():
    from proxy_pipeline.agents.ai_havuz import _sozlesmeye_uyarla
    from proxy_pipeline.decision.contracts import DecisionOutput
    from proxy_pipeline.domain.models import DecisionContext
    ctx = DecisionContext("aday", "r2", {}, "s", "m")
    out = _sozlesmeye_uyarla({"action": "belirsiz", "targets": [{"cidr": "x", "ports": [99999]}]}, ctx)
    parsed = DecisionOutput.model_validate(out)
    assert parsed.action.value == "research"
    assert parsed.targets == []
    assert parsed.items[0].candidate_id == "r2"

def test_uyarlayici_gevsek_tipleri_duzeltir():
    from proxy_pipeline.agents.ai_havuz import _sozlesmeye_uyarla
    from proxy_pipeline.domain.models import DecisionContext
    from proxy_pipeline.decision.contracts import DecisionOutput
    ctx = DecisionContext("aday", "r3", {}, "s", "m")
    out = _sozlesmeye_uyarla(
        {"action": "sample",
         "targets": {"cidr": "198.51.100.0/24", "ports": [3128], "protocols": ["tcp"]},
         "resource_plan": "hızlı bak",
         "items": [{"candidate_id": "r3", "action": "sample",
                    "targets": [{"cidr": "198.51.100.0/24"}],
                    "resource_allocation": "1 dizi, 5 dakika",
                    "stop_expression": "10 düğümde dur"}],
         "confidence": 0.75}, ctx)
    parsed = DecisionOutput.model_validate(out)
    assert parsed.action.value == "sample"
    assert parsed.targets[0].cidr == "198.51.100.0/24"
    assert isinstance(parsed.confidence, str)


def test_uyarlayici_string_port_ve_protocolu_karakterlere_bolmez():
    from proxy_pipeline.agents.ai_havuz import _sozlesmeye_uyarla
    from proxy_pipeline.domain.models import DecisionContext

    out = _sozlesmeye_uyarla(
        {"action": "research", "targets": [{
            "cidr": "192.168.1.0/24",
            "ports": "8443",
            "protocols": "http_connect",
        }]},
        DecisionContext("aday", "r4", {}, "s", "m"),
    )
    assert out["targets"][0]["ports"] == [8443]
    assert out["targets"][0]["protocols"] == ["http_connect"]


def test_hunter_prompt_uses_only_catalog_tools_and_tool_arguments():
    from proxy_pipeline.agents.ai_havuz import YONERGE

    assert "curl" in YONERGE
    assert "tool_arguments" in YONERGE
    assert "httpbin" in YONERGE
    assert "observe_vds_surface" in YONERGE
