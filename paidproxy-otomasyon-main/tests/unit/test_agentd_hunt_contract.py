import pytest

from services.agentd import ai_runtime
from services.agentd.ai_runtime import AgentRuntime, _hunter_instruction, validate_tool_arguments


def test_masscan_liveness_accepts_planner_port_intent_without_a_single_port_gate():
    """The planner chooses one port or a port set/range; the code must not
    force a single first-bite port."""
    single = validate_tool_arguments(
        "masscan_liveness",
        {"cidr": "9.9.9.0/24", "ports": [3128]},
    )
    assert single["ports"] == [3128]

    multi = validate_tool_arguments(
        "masscan_liveness",
        {"cidr": "9.9.9.0/24", "ports": [3128, 1080]},
    )
    assert multi["ports"] == [3128, 1080]

    band = validate_tool_arguments(
        "masscan_liveness",
        {"cidr": "9.9.9.0/24", "port_spec": "10000-10999"},
    )
    assert band["port_spec"] == "10000-10999"


def test_masscan_liveness_accepts_wider_than_slash24():
    """A prefix size must not block a provider target."""
    accepted = validate_tool_arguments(
        "masscan_liveness",
        {"cidr": "79.119.0.0/16", "ports": [7777]},
    )
    assert accepted["cidr"] == "79.119.0.0/16"


def test_fast_triage_tool_argument_validation():
    """fast_triage accepts host/ip with list of ports."""
    res = validate_tool_arguments("fast_triage", {"host": "1.2.3.4", "ports": [8080, 1080], "concurrency": 250})
    assert res["host"] == "1.2.3.4"
    assert res["ports"] == [1080, 8080]
    assert res["concurrency"] == 250


def test_recon_bgp_tool_argument_validation():
    """recon_bgp accepts ASN or IP."""
    res_asn = validate_tool_arguments("recon_bgp", {"asn": "AS209207", "org": "Digital Hosting"})
    assert res_asn["asn"] == "AS209207"
    assert res_asn["org"] == "Digital Hosting"

    res_ip = validate_tool_arguments("recon_bgp", {"ip": "138.124.79.1"})
    assert res_ip["ip"] == "138.124.79.1"

    with pytest.raises(ValueError, match="publicly routable IPv4"):
        validate_tool_arguments(
            "masscan_liveness",
            {"cidr": "10.0.0.0/8", "ports": [7777]},
        )


def test_masscan_liveness_defaults_to_every_port():
    """No port argument means every port: the first scan must not miss a port
    because the planner omitted the intent."""
    accepted = validate_tool_arguments("masscan_liveness", {"cidr": "79.119.0.0/16"})
    assert accepted["port_spec"] == "1-65535"


def test_masscan_wait_and_rate_are_environment_execution_knobs(monkeypatch):
    from services.agentd.ai_runtime import _masscan_command

    monkeypatch.setenv("PAIDPROXY_MASSCAN_WAIT", "3")
    command = _masscan_command("79.119.0.0/16", "1-65535", 5000)
    assert "--wait" in command
    assert command[command.index("--wait") + 1] == "3"
    assert command[command.index("--rate") + 1] == "5000"

    monkeypatch.delenv("PAIDPROXY_MASSCAN_WAIT")
    command = _masscan_command("79.119.0.0/16", "1-65535", 5000)
    assert command[command.index("--wait") + 1] == "0"


def test_decide_uses_only_claude_planner_and_never_falls_back(tmp_path, monkeypatch):
    """There is no Python pool: a planner failure yields no decision at all."""
    events: list[tuple] = []
    runtime = AgentRuntime(
        root=tmp_path,
        agent_id="agent-test",
        job_id="job-test",
        kind="gezinme",
        initial_input="",
        emit=lambda *args, **kwargs: events.append((args, kwargs)),
        stopped=lambda: False,
    )

    def boom(snapshot):
        raise RuntimeError("harness down")

    monkeypatch.setattr(ai_runtime, "claude_planner_decide", boom)
    assert runtime._decide() is None
    assert any(args and args[0] == "ai_unavailable" for args, _ in events)


def test_validate_open_ports_honours_l7_concurrency_env(tmp_path, monkeypatch):
    import threading
    import time

    runtime = AgentRuntime(
        root=tmp_path,
        agent_id="agent-test",
        job_id="job-test",
        kind="gezinme",
        initial_input="",
        emit=lambda *args, **kwargs: None,
        stopped=lambda: False,
    )
    monkeypatch.setenv("PAIDPROXY_L7_CONCURRENCY", "4")
    lock = threading.Lock()
    active = 0
    peak = 0

    def fake_validate(host, port, target_url, protocols):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.02)
        with lock:
            active -= 1
        return {"results": [], "validated": []}

    runtime._validate_port_direct = fake_validate
    result = runtime._validate_open_ports("1.2.3.4", list(range(1, 41)))
    assert result["checked"] == 40
    assert peak <= 4


def test_validate_open_ports_emits_progress_every_100_ports(tmp_path):
    events: list[tuple] = []
    runtime = AgentRuntime(
        root=tmp_path,
        agent_id="agent-test",
        job_id="job-test",
        kind="gezinme",
        initial_input="",
        emit=lambda *args, **kwargs: events.append((args, kwargs)),
        stopped=lambda: False,
    )
    runtime._validate_port_direct = (
        lambda host, port, target_url, protocols: {"results": [], "validated": []}
    )
    result = runtime._validate_open_ports("1.2.3.4", list(range(1, 251)))
    assert result["checked"] == 250
    progress = [kwargs for args, kwargs in events if args and args[0] == "l7_progress"]
    assert [item["checked"] for item in progress] == [100, 200]


def test_expand_live_ip_keeps_multi_port_vertical_expansion():
    accepted = validate_tool_arguments(
        "expand_live_ip",
        {"ip": "9.9.9.9", "ports": [3128, 1080]},
    )
    assert accepted["ports"] == [3128, 1080]


def test_validation_rejects_decorative_example_target():
    for target_url in ("https://example.com/", "https://whatismyip.com/"):
        with pytest.raises(ValueError, match="genel örnek"):
            AgentRuntime._target_from_args({"target_url": target_url})


def test_target_ip_is_allowed_when_provenance_guard_handles_bootstrap_policy():
    target = AgentRuntime._target_from_args({"target_url": "https://1.1.1.1/"})
    assert target["host"] == "1.1.1.1"


def test_hunt_target_tools_require_public_source_provenance(tmp_path):
    runtime = AgentRuntime(
        root=tmp_path,
        agent_id="agent-test",
        job_id="job-test",
        kind="gezinme",
        initial_input="",
        emit=lambda *args, **kwargs: None,
        stopped=lambda: False,
    )
    decision = {
        "requested_tools": ["inspect_owner_context"],
        "resource_plan": {"tool_arguments": {"inspect_owner_context": {"ip": "1.1.1.1"}}},
    }
    assert runtime._requested_tools(decision) == []

    mixed = {
        "requested_tools": ["browse_public_source", "masscan_liveness"],
        "resource_plan": {"tool_arguments": {
            "browse_public_source": {"url": "https://bgp.he.net/"},
            "masscan_liveness": {"cidr": "not-a-cidr", "ports": [3128]},
        }},
    }
    assert runtime._requested_tools(mixed) == [
        ("browse_public_source", {"url": "https://bgp.he.net/"}),
    ]

    runtime.observations.append({
        "tool": "browse_public_source",
        "result": {
            "url": "https://bgp.he.net/",
            "status": 200,
            "evidence_refs": ["agent://agent-test/outputs/source-1.bin"],
            "observed_ips": ["1.1.1.1"],
            "observed_asns": [13335],
        },
    })
    assert runtime._requested_tools(decision) == [
        ("inspect_owner_context", {"ip": "1.1.1.1"}),
    ]


def test_hunter_instruction_moves_past_repeated_runtime_observation():
    instruction = _hunter_instruction([
        {"tool": "observe_vds_surface", "result": {"hostname": "thinkpad"}},
    ])
    assert "browse_public_source" in instruction
    assert "observe_vds_surface" in instruction
    assert "tekrar seçme" in instruction


def test_runtime_hides_preflight_tool_after_initial_observation(tmp_path):
    runtime = AgentRuntime(
        root=tmp_path,
        agent_id="agent-test",
        job_id="job-test",
        kind="gezinme",
        initial_input="",
        emit=lambda *args, **kwargs: None,
        stopped=lambda: False,
    )
    runtime._runtime_preflight_done = True
    names = {item["name"] for item in runtime._available_tools_for_phase()}
    assert "observe_vds_surface" not in names
    assert "browse_public_source" in names


def test_catalog_gives_ai_real_public_source_entry_points(tmp_path):
    runtime = AgentRuntime(
        root=tmp_path,
        agent_id="agent-test",
        job_id="job-test",
        kind="gezinme",
        initial_input="",
        emit=lambda *args, **kwargs: None,
        stopped=lambda: False,
    )
    browse = next(item for item in runtime.catalog.describe() if item["name"] == "browse_public_source")
    assert "bgp.he.net" in browse["allowed_hosts"]
    assert browse["source_examples"]
    assert all("example.com" not in url for url in browse["source_examples"])


def test_requested_tool_dict_and_contract_label_are_normalized(tmp_path):
    runtime = AgentRuntime(
        root=tmp_path,
        agent_id="agent-test",
        job_id="job-test",
        kind="gezinme",
        initial_input="",
        emit=lambda *args, **kwargs: None,
        stopped=lambda: False,
    )
    runtime.observations.append({
        "tool": "browse_public_source",
        "result": {
            "url": "https://bgp.he.net/",
            "status": 200,
            "evidence_refs": ["agent://agent-test/outputs/source-1.bin"],
            "observed_ips": ["1.2.3.4"],
            "observed_cidrs": ["1.2.3.0/24"],
        },
    })
    tools = runtime._requested_tools({
        "requested_tools": [{
            "name": "masscan_liveness",
            "resource_plan": {"tool_arguments": {
                "cidr": "1.2.3.0/24",
                "one first port in ports OR port_spec/port_range": "80",
            }},
        }],
    })
    assert tools == [("masscan_liveness", {"cidr": "1.2.3.0/24", "ports": [80]})]


def test_masscan_command_uses_noninteractive_sudo_for_unprivileged_worker(monkeypatch):
    monkeypatch.setattr(ai_runtime.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(ai_runtime.shutil, "which", lambda name: "/usr/bin/sudo" if name == "sudo" else None)
    command = ai_runtime._masscan_command("1.2.3.0/24", "3128", 1000)
    assert command[:3] == ["/usr/bin/sudo", "-n", "masscan"]



def test_myip_source_is_collected_by_kahin_and_anchored_to_agent_evidence(tmp_path, monkeypatch):

    def fake_collect(url):
        return {
            "working_note": "Kahin visual proof",
            "url": url,
            "status": 200,
            "content_type": "text/visual+ocr",
            "body_preview": "AS64501 9.9.9.9 broadband reseller",
            "_screenshot_bytes": b"visual-proof",
            "source_provenance": "kahin-mirage-google-vision",
            "observed_ips": ["9.9.9.9"],
            "observed_cidrs": [],
            "observed_asns": [64501],
        }

    monkeypatch.setattr("services.agentd.kahin_source.collect_myip_source", fake_collect)
    runtime = AgentRuntime(
        root=tmp_path / "runtime",
        agent_id="agent-test",
        job_id="job-test",
        kind="gezinme",
        initial_input="",
        emit=lambda *args, **kwargs: None,
        stopped=lambda: False,
    )
    result = runtime._browse_public_source({"url": "https://myip.ms/"})
    assert result["source_provenance"] == "kahin-mirage-google-vision"
    assert result["observed_ips"] == ["9.9.9.9"]
    assert any(ref.endswith("kahin-myip-00000.png") for ref in result["evidence_refs"])


def test_masscan_command_skips_sudo_when_file_capability_present(monkeypatch):
    monkeypatch.setattr(ai_runtime.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(
        ai_runtime.shutil, "which", lambda name: "/usr/bin/masscan" if name == "masscan" else None
    )
    monkeypatch.setattr(ai_runtime, "_masscan_has_file_capability", lambda binary: True)
    command = ai_runtime._masscan_command("1.2.3.0/24", "3128", 1000)
    assert command[0] == "/usr/bin/masscan"
    assert "sudo" not in command


def test_masscan_command_uses_sudo_without_capability(monkeypatch):
    monkeypatch.setattr(ai_runtime.os, "geteuid", lambda: 1000)
    def which(name):
        return {"masscan": "/usr/bin/masscan", "sudo": "/usr/bin/sudo"}.get(name)
    monkeypatch.setattr(ai_runtime.shutil, "which", which)
    monkeypatch.setattr(ai_runtime, "_masscan_has_file_capability", lambda binary: False)
    command = ai_runtime._masscan_command("1.2.3.0/24", "3128", 1000)
    assert command[:3] == ["/usr/bin/sudo", "-n", "/usr/bin/masscan"]


def test_validate_proxy_accepts_public_host_without_name_error():
    """Regression: _validated_host_or_ip referenced an undefined helper and
    crashed the whole worker when the AI finally reached L7 validation."""
    accepted = validate_tool_arguments(
        "validate_proxy",
        {
            "host": "138.124.79.148",
            "port": 8080,
            "target_url": "https://httpbin.org/ip",
            "protocols": ["http_connect"],
        },
    )
    assert accepted["host"] == "138.124.79.148"
    assert accepted["port"] == 8080


def test_validate_proxy_still_rejects_decorative_validation_target():
    with pytest.raises(ValueError, match="genel örnek"):
        AgentRuntime._target_from_args({"target_url": "https://example.com/"})


def test_flat_tool_arguments_are_accepted_as_requested_tools(tmp_path):
    """Regression: the planner sometimes emits {"tool_arguments": {...}}
    without requested_tools/resource_plan; the runtime must still execute it."""
    runtime = AgentRuntime(
        root=tmp_path,
        agent_id="agent-test",
        job_id="job-test",
        kind="gezinme",
        initial_input="",
        emit=lambda *args, **kwargs: None,
        stopped=lambda: False,
    )
    runtime.observations.append({
        "tool": "browse_public_source",
        "result": {
            "url": "https://bgp.he.net/AS209207",
            "status": 200,
            "evidence_refs": ["agent://agent-test/outputs/source.bin"],
            "observed_ips": ["138.124.79.148"],
            "observed_cidrs": ["138.124.79.0/24"],
            "observed_asns": [209207],
        },
    })
    tools = runtime._requested_tools({
        "action": "research",
        "tool_arguments": {
            "masscan_liveness": {"cidr": "138.124.79.0/24", "ports": [3128], "rate": 500},
        },
    })
    assert tools == [("masscan_liveness", {"cidr": "138.124.79.0/24", "ports": [3128], "rate": 500})]


def test_flat_tool_arguments_expand_list_of_targets(tmp_path):
    runtime = AgentRuntime(
        root=tmp_path,
        agent_id="agent-test",
        job_id="job-test",
        kind="gezinme",
        initial_input="",
        emit=lambda *args, **kwargs: None,
        stopped=lambda: False,
    )
    runtime.observations.append({
        "tool": "masscan_liveness",
        "result": {
            "discovered": [
                {"ip": "138.124.79.148", "port": 8080},
                {"ip": "138.124.79.89", "port": 8080},
            ]
        },
    })
    tools = runtime._requested_tools({
        "tool_arguments": {
            "validate_proxy": [
                {"host": "138.124.79.148", "port": 8080, "target_url": "https://httpbin.org/ip", "protocols": ["http_connect"]},
                {"host": "138.124.79.89", "port": 8080, "target_url": "https://httpbin.org/ip", "protocols": ["http_connect"]},
            ],
        },
    })
    assert [name for name, _ in tools] == ["validate_proxy", "validate_proxy"]
    assert tools[1][1]["host"] == "138.124.79.89"


def test_operator_directive_supplies_hunt_provenance(tmp_path):
    """The operator is an authoritative scent source: when they state a CIDR
    and ASN, the hunter must be able to act on it without re-browsing."""
    runtime = AgentRuntime(
        root=tmp_path,
        agent_id="agent-test",
        job_id="job-test",
        kind="gezinme",
        initial_input="",
        emit=lambda *args, **kwargs: None,
        stopped=lambda: False,
    )
    runtime.operator_directives.append({
        "instruction": "Damar: 138.124.79.0/24 ASN 209207. masscan 8080 yap.",
    })
    facts = runtime._hunt_facts()
    assert "138.124.79.0/24" in {str(c) for c in facts["cidrs"]}
    assert 209207 in facts["asns"]
    assert runtime._target_provenance_error(
        "masscan_liveness", {"cidr": "138.124.79.0/24", "ports": [8080]}
    ) is None


def test_operator_product_specific_proxy_ports_are_allowed():
    """Operator scent: real paid-proxy vendors rotate/sticky on these ports.
    3128 alone is the script-kiddie graveyard; these are the product ports."""
    for port in (1081, 3129, 8000, 8001, 7777, 12323, 12324, 7000, 823, 6060, 10000, 10001, 63000):
        accepted = validate_tool_arguments(
            "expand_live_ip", {"ip": "9.9.9.9", "ports": [port]}
        )
        assert accepted["ports"] == [port], f"port {port} must be allowed"


def test_operator_sticky_port_band_is_allowed():
    """Sticky-IP paid proxies start at 10K and end at 63K."""
    accepted = validate_tool_arguments(
        "expand_live_ip", {"ip": "9.9.9.9", "ports": ["10000-63000"]}
    )
    assert accepted["ports"] == ["10000-63000"]


def test_script_kiddie_port_is_still_a_valid_first_bite_but_not_the_only_one():
    accepted = validate_tool_arguments(
        "masscan_liveness", {"cidr": "9.9.9.0/24", "ports": [3128]}
    )
    assert accepted["ports"] == [3128]


def test_hunt_notes_file_supplies_operator_port_scent(tmp_path):
    """The operator's hunt notebook must be read on every decision, so vendor
    port knowledge survives restarts instead of living only in chat."""
    notes = tmp_path / "var" / "port-araliklari" / "av-defteri.txt"
    notes.parent.mkdir(parents=True, exist_ok=True)
    notes.write_text(
        "# yorum\nPORT 12323\nPORT 12324\nBAND 8001-63000\n",
        encoding="utf-8",
    )
    runtime = AgentRuntime(
        root=tmp_path,
        agent_id="agent-test",
        job_id="job-test",
        kind="gezinme",
        initial_input="",
        emit=lambda *args, **kwargs: None,
        stopped=lambda: False,
    )
    scent = runtime._hunt_notebook()
    assert 12323 in scent["ports"]
    assert 12324 in scent["ports"]
    assert "8001-63000" in scent["bands"]


def test_hunt_notes_ports_are_usable_as_provenance(tmp_path):
    notes = tmp_path / "var" / "port-araliklari" / "av-defteri.txt"
    notes.parent.mkdir(parents=True, exist_ok=True)
    notes.write_text("PORT 12323\n", encoding="utf-8")
    runtime = AgentRuntime(
        root=tmp_path,
        agent_id="agent-test",
        job_id="job-test",
        kind="gezinme",
        initial_input="",
        emit=lambda *args, **kwargs: None,
        stopped=lambda: False,
    )
    accepted = validate_tool_arguments(
        "masscan_liveness", {"cidr": "9.9.9.0/24", "ports": [12323]}
    )
    assert accepted["ports"] == [12323]


def test_proxy_get_does_not_accept_origin_server_page_as_egress(monkeypatch):
    """Regression: a non-proxy web port answering 200/404 with its own page
    must never be counted as confirmed egress. Only the real target's body does."""
    runtime = AgentRuntime(
        root="/tmp/egress-test",
        agent_id="agent-test",
        job_id="job-test",
        kind="gezinme",
        initial_input="",
        emit=lambda *args, **kwargs: None,
        stopped=lambda: False,
    )

    class FakeSock:
        def __init__(self, payload):
            self.payload = payload
            self.sent = b""
        def sendall(self, data):
            self.sent += data
        def recv(self, _n):
            chunk, self.payload = self.payload, b""
            return chunk

    # A random web server answering with its own HTML, not httpbin's JSON.
    fake = FakeSock(
        b"HTTP/1.1 200 OK\r\nServer: nginx/1.31.5\r\nContent-Type: text/html\r\n"
        b"Content-Length: 40\r\n\r\n<!doctype html><html>nginx page</html>"
    )
    target = {"host": "httpbin.org", "port": 80, "path": "/ip", "scheme": "http"}
    result = runtime._proxy_get(fake, target)
    assert result["egress_confirmed"] is False, "origin server page must not count as egress"

    # A real proxy answer carries the target's own payload.
    real = FakeSock(
        b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
        b"Content-Length: 30\r\n\r\n{\"origin\": \"203.0.113.7\"}"
    )
    ok = runtime._proxy_get(real, target)
    assert ok["egress_confirmed"] is True


def test_port_scan_live_ip_enumerates_every_open_port(tmp_path):
    """Operator's core flow: masscan gives a live IP, then a real port scanner
    enumerates ALL its open ports. Every open port goes to L7; one dead port
    must never discard the whole IP."""
    runtime = AgentRuntime(
        root=tmp_path,
        agent_id="agent-test",
        job_id="job-test",
        kind="gezinme",
        initial_input="",
        emit=lambda *args, **kwargs: None,
        stopped=lambda: False,
    )
    # Simulate a host where 3128 is closed but a random high port is open.
    import services.agentd.ai_runtime as rt
    original = rt.socket.create_connection

    class FakeConn:
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def fake_create_connection(addr, timeout=None):
        host, port = addr
        if port in (16866, 41451):
            return FakeConn()
        raise OSError("closed")

    rt.socket.create_connection = fake_create_connection
    runtime._masscan_enumerate_ports = lambda ip, rng, rate: [16866, 41451]
    try:
        result = runtime._port_scan_live_ip({
            "ip": "193.233.126.126",
            "port_range": "1-65535",
            "concurrency": 1024,
            "timeout": 0.05,
        })
    finally:
        rt.socket.create_connection = original
    assert result["ip"] == "193.233.126.126"
    assert result["open_ports"] == [16866, 41451]
    assert result["scan_range"] == "1-65535"
    assert result["open_port_count"] == 2


def test_open_ports_are_registered_for_validation(tmp_path):
    """Each open port is work to validate; the IP survives per-port failures."""
    runtime = AgentRuntime(
        root=tmp_path,
        agent_id="agent-test",
        job_id="job-test",
        kind="gezinme",
        initial_input="",
        emit=lambda *args, **kwargs: None,
        stopped=lambda: False,
    )
    added = runtime._register_open_ports("193.233.126.126", [16866, 41451])
    assert added == 2
    assert runtime._pending_open_ports() == [
        {"host": "193.233.126.126", "port": 16866},
        {"host": "193.233.126.126", "port": 41451},
    ]


def test_resource_plan_nested_tool_arguments_are_executed(tmp_path):
    """Regression: the planner emits resource_plan.tool + nested tool_arguments
    without requested_tools; the new port_scan tool must still run."""
    runtime = AgentRuntime(
        root=tmp_path,
        agent_id="agent-test",
        job_id="job-test",
        kind="gezinme",
        initial_input="",
        emit=lambda *args, **kwargs: None,
        stopped=lambda: False,
    )
    runtime.observations.append({
        "tool": "masscan_liveness",
        "result": {"discovered": [{"ip": "193.233.126.126", "port": 8000}]},
    })
    tools = runtime._requested_tools({
        "action": "full_scan",
        "resource_plan": {
            "tool": "port_scan_live_ip",
            "tool_arguments": {
                "port_scan_live_ip": {
                    "ip": "193.233.126.126",
                    "port_range": "1-65535",
                    "concurrency": 1024,
                    "timeout": 0.5,
                }
            },
        },
    })
    assert tools == [
        ("port_scan_live_ip", {
            "ip": "193.233.126.126",
            "port_range": "1-65535",
            "concurrency": 1024,
            "timeout": 0.5,
        })
    ]


def test_operator_declared_live_ips_are_usable_for_port_scan(tmp_path):
    """Operator states the masscan live-IP list; the hunter must be able to run
    the full port scan on them without re-running masscan from scratch."""
    runtime = AgentRuntime(
        root=tmp_path,
        agent_id="agent-test",
        job_id="job-test",
        kind="gezinme",
        initial_input="",
        emit=lambda *args, **kwargs: None,
        stopped=lambda: False,
    )
    runtime.operator_directives.append({
        "instruction": "masscan canli IP ler: 193.233.126.126, 193.233.126.179. port_scan_live_ip yap.",
    })
    assert runtime._target_provenance_error(
        "port_scan_live_ip", {"ip": "193.233.126.126"}
    ) is None


def test_initial_input_live_ips_are_valid_port_scan_provenance(tmp_path):
    """The operator's brief arrives as initial_input on a fresh agent; its live
    IP list and hunt flow must be usable without a prior intervene call."""
    runtime = AgentRuntime(
        root=tmp_path,
        agent_id="agent-test",
        job_id="job-test",
        kind="gezinme",
        initial_input=(
            "masscan canli IP ler: 193.233.126.126, 193.233.126.179. "
            "port_scan_live_ip ile tum acik portlari cikar."
        ),
        emit=lambda *args, **kwargs: None,
        stopped=lambda: False,
    )
    assert runtime._target_provenance_error(
        "port_scan_live_ip", {"ip": "193.233.126.126"}
    ) is None


def test_open_ports_are_validated_without_llm_discretion(tmp_path):
    """Every open port produced by a port scan must be validated. The runtime
    tracks the work itself instead of hoping the planner lists all of them."""
    runtime = AgentRuntime(
        root=tmp_path,
        agent_id="agent-test",
        job_id="job-test",
        kind="gezinme",
        initial_input="",
        emit=lambda *args, **kwargs: None,
        stopped=lambda: False,
    )
    runtime._register_open_ports("193.233.126.126", [22, 8000])
    runtime._register_open_ports("193.233.126.179", [16866])
    assert runtime._pending_open_ports() == [
        {"host": "193.233.126.126", "port": 22},
        {"host": "193.233.126.126", "port": 8000},
        {"host": "193.233.126.179", "port": 16866},
    ]
    runtime._mark_port_validated({"host": "193.233.126.126", "port": 22})
    assert runtime._pending_open_ports() == [
        {"host": "193.233.126.126", "port": 8000},
        {"host": "193.233.126.179", "port": 16866},
    ]


def test_port_scan_result_is_exposed_as_open_ports_to_validate(tmp_path):
    import services.agentd.ai_runtime as rt

    runtime = AgentRuntime(
        root=tmp_path,
        agent_id="agent-test",
        job_id="job-test",
        kind="gezinme",
        initial_input="",
        emit=lambda *args, **kwargs: None,
        stopped=lambda: False,
    )
    original = rt.socket.create_connection

    class FakeConn:
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def fake(addr, timeout=None):
        if addr[1] in (22, 8000):
            return FakeConn()
        raise OSError("closed")

    rt.socket.create_connection = fake
    runtime._masscan_enumerate_ports = lambda ip, rng, rate: [22, 8000]
    try:
        result = runtime._port_scan_live_ip({
            "ip": "193.233.126.126",
            "port_range": "1-65535",
            "concurrency": 1024,
            "timeout": 0.05,
        })
    finally:
        rt.socket.create_connection = original
    assert result["open_port_count"] == 2
    assert runtime._pending_open_ports() == [
        {"host": "193.233.126.126", "port": 22},
        {"host": "193.233.126.126", "port": 8000},
    ]


def test_port_scan_default_timeout_is_not_so_aggressive_it_misses_ports(tmp_path):
    """Measured on the real VDS: timeout=0.5 missed 5432/8000/16866 that
    timeout=1.5 found. The default must not silently drop real open ports."""
    import services.agentd.ai_runtime as rt

    runtime = AgentRuntime(
        root=tmp_path,
        agent_id="agent-test",
        job_id="job-test",
        kind="gezinme",
        initial_input="",
        emit=lambda *args, **kwargs: None,
        stopped=lambda: False,
    )
    seen_timeouts = []
    original = rt.socket.create_connection

    class FakeConn:
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def fake(addr, timeout=None):
        seen_timeouts.append(timeout)
        if addr[1] == 16866:
            return FakeConn()
        raise OSError("closed")

    rt.socket.create_connection = fake
    runtime._masscan_enumerate_ports = lambda ip, rng, rate: [16866]
    try:
        runtime._port_scan_live_ip({
            "ip": "193.233.126.89",
            "port_range": "16866-16866",
            "concurrency": 16,
        })
    finally:
        rt.socket.create_connection = original
    assert seen_timeouts, "scan must probe"
    assert min(seen_timeouts) >= 1.0, f"default timeout too aggressive: {min(seen_timeouts)}"


def test_port_scan_uses_masscan_then_socket_confirms(tmp_path):
    """Measured: masscan full-scan of one IP takes ~8s and found all 6 ports,
    while a pure socket scan took 250s+ and missed ports. The scanner must use
    masscan to enumerate, then re-confirm each hit with a real socket connect."""
    import services.agentd.ai_runtime as rt

    runtime = AgentRuntime(
        root=tmp_path,
        agent_id="agent-test",
        job_id="job-test",
        kind="gezinme",
        initial_input="",
        emit=lambda *args, **kwargs: None,
        stopped=lambda: False,
    )
    calls = {}

    class FakeProcess:
        def __init__(self, lines):
            self.stdout = iter(lines)
            self.stderr = None
            self.returncode = 0
        def wait(self):
            return 0

    def fake_popen(command, **kwargs):
        calls["command"] = command
        # masscan -oL - output: open tcp <port> <ip> <ts>
        return FakeProcess([
            "open tcp 22 193.233.126.89 1\n",
            "open tcp 16866 193.233.126.89 1\n",
            "open tcp 9999 193.233.126.89 1\n",  # stale/false positive
        ])

    original_popen = rt.subprocess.Popen
    original_conn = rt.socket.create_connection

    class FakeConn:
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def fake_conn(addr, timeout=None):
        if addr[1] in (22, 16866):
            return FakeConn()
        raise OSError("not really open")

    runtime._masscan_enumerate_ports = lambda ip, rng, rate: [22, 16866, 9999]
    rt.socket.create_connection = fake_conn
    try:
        result = runtime._port_scan_live_ip({
            "ip": "193.233.126.89",
            "port_range": "1-65535",
        })
    finally:
        rt.socket.create_connection = original_conn
    # 9999 was reported by masscan but socket-confirm rejects it.
    assert result["open_ports"] == [22, 16866]
    assert result["method"] == "masscan+socket_confirm"


def test_port_scan_rejects_silent_range_narrowing_when_full_scan_requested(tmp_path):
    """Regression: the planner passed the vendor port list as port_range and
    silently reduced a full scan to 9 ports, losing 22/80/443/5432/16866.
    A full-scan request must not be narrowed by the notebook ports."""
    import services.agentd.ai_runtime as rt

    runtime = AgentRuntime(
        root=tmp_path,
        agent_id="agent-test",
        job_id="job-test",
        kind="gezinme",
        initial_input="",
        emit=lambda *args, **kwargs: None,
        stopped=lambda: False,
    )
    seen = {}
    runtime._masscan_enumerate_ports = lambda ip, rng, rate: seen.setdefault("rng", rng) or []
    result = runtime._port_scan_live_ip({
        "ip": "193.233.126.126",
        "port_range": "8000-8001,10000-10001,12323-12324,3129,1081,7777,7000,823,6060",
    })
    # This tool's contract is a FULL port scan; a narrowed range from the
    # planner must not silently drop ports, so the effective range is 1-65535.
    assert seen["rng"] == "1-65535"
    assert result["scan_range"] == "1-65535"
    assert result["requested_range"] != "1-65535"


def test_port_scan_full_range_is_used_when_requested(tmp_path):
    import services.agentd.ai_runtime as rt

    runtime = AgentRuntime(
        root=tmp_path,
        agent_id="agent-test",
        job_id="job-test",
        kind="gezinme",
        initial_input="",
        emit=lambda *args, **kwargs: None,
        stopped=lambda: False,
    )
    seen = {}
    runtime._masscan_enumerate_ports = lambda ip, rng, rate: seen.setdefault("rng", rng) or []
    result = runtime._port_scan_live_ip({"ip": "193.233.126.126", "port_range": "1-65535"})
    assert seen["rng"] == "1-65535"
    assert result["scan_range"] == "1-65535"


def test_open_ports_validate_without_waiting_for_planner(tmp_path):
    """The planner must not be the bottleneck for mechanical validation:
    open ports are validated by the runtime, not one per LLM turn."""
    runtime = AgentRuntime(
        root=tmp_path,
        agent_id="agent-test",
        job_id="job-test",
        kind="gezinme",
        initial_input="",
        emit=lambda *args, **kwargs: None,
        stopped=lambda: False,
    )
    probed: list[tuple[str, int]] = []

    def fake_validate(host, port, target_url, protocols):
        probed.append((host, port))
        return {"protocols": protocols, "validated": [], "results": [], "egress": False}

    runtime._validate_port_direct = fake_validate
    validation = runtime._validate_open_ports("193.233.126.126", [22, 8000, 16866])
    assert sorted(probed) == [
        ("193.233.126.126", 22),
        ("193.233.126.126", 8000),
        ("193.233.126.126", 16866),
    ]
    assert validation["checked"] == 3
    assert validation["total"] == 3
    assert runtime._pending_open_ports() == []
    assert validation["egress_hits"] == []


def test_open_port_validation_reports_egress_hit(tmp_path):
    runtime = AgentRuntime(
        root=tmp_path,
        agent_id="agent-test",
        job_id="job-test",
        kind="gezinme",
        initial_input="",
        emit=lambda *args, **kwargs: None,
        stopped=lambda: False,
    )

    def fake_validate(host, port, target_url, protocols):
        return {
            "protocols": protocols,
            "validated": [{"protocol": "http_connect", "egress_confirmed": True}],
            "results": [{"protocol": "http_connect", "egress_confirmed": True}],
            "egress": True,
        }

    runtime._validate_port_direct = fake_validate
    validation = runtime._validate_open_ports("1.2.3.4", [3128])
    assert validation["checked"] == 1
    assert validation["egress_hits"] == [{"host": "1.2.3.4", "port": 3128}]


def test_proxy_auth_required_is_recognised_as_real_proxy(tmp_path):
    """Measured on the real VDS: 138.124.79.160:10000 answered
    'HTTP/1.1 407 Proxy Authentication Required'. That is a real proxy that
    needs credentials, not an open one; it must be classified distinctly from
    a web server answering 400/404."""
    runtime = AgentRuntime(
        root=tmp_path,
        agent_id="agent-test",
        job_id="job-test",
        kind="gezinme",
        initial_input="",
        emit=lambda *args, **kwargs: None,
        stopped=lambda: False,
    )

    class FakeSock:
        def __init__(self, payload):
            self.payload = payload
        def sendall(self, data):
            pass
        def settimeout(self, _t):
            pass
        def close(self):
            pass
        def recv(self, _n):
            chunk, self.payload = self.payload, b""
            return chunk

    target = {"host": "httpbin.org", "port": 443, "path": "/ip", "scheme": "https"}
    fake = FakeSock(b"HTTP/1.1 407 Proxy Authentication Required\r\nProxy-Authenticate: Basic\r\n\r\n")
    import services.agentd.ai_runtime as rt
    original = rt.socket.create_connection
    rt.socket.create_connection = lambda addr, timeout=None: fake
    try:
        result = runtime._probe_protocol("1.2.3.4", 10000, "http_connect", target)
    finally:
        rt.socket.create_connection = original
    assert result["http_status"] == 407
    assert result["egress_confirmed"] is False
    assert result["proxy_detected"] is True
    assert result["auth_required"] is True


def test_web_server_400_is_not_flagged_as_proxy(tmp_path):
    runtime = AgentRuntime(
        root=tmp_path,
        agent_id="agent-test",
        job_id="job-test",
        kind="gezinme",
        initial_input="",
        emit=lambda *args, **kwargs: None,
        stopped=lambda: False,
    )

    class FakeSock:
        def __init__(self, payload):
            self.payload = payload
        def sendall(self, data):
            pass
        def settimeout(self, _t):
            pass
        def close(self):
            pass
        def recv(self, _n):
            chunk, self.payload = self.payload, b""
            return chunk

    target = {"host": "httpbin.org", "port": 443, "path": "/ip", "scheme": "https"}
    fake = FakeSock(b"HTTP/1.1 400 Bad Request\r\nServer: nginx\r\n\r\n")
    import services.agentd.ai_runtime as rt
    original = rt.socket.create_connection
    rt.socket.create_connection = lambda addr, timeout=None: fake
    try:
        result = runtime._probe_protocol("1.2.3.4", 8000, "http_connect", target)
    finally:
        rt.socket.create_connection = original
    assert result["proxy_detected"] is False
    assert result["auth_required"] is False


def test_hunter_instruction_names_operator_product_ports(tmp_path):
    """The notebook must reach the model in prose, not only as snapshot JSON:
    the live agent kept retrying 3128/1080 and never used the vendor ports."""
    from services.agentd.ai_runtime import _hunter_instruction

    instruction = _hunter_instruction([])
    assert "8000" in instruction or "12323" in instruction or "10000" in instruction
    assert "urun" in instruction.lower() or "ürün" in instruction.lower()


def test_notebook_ports_are_tried_before_legacy_ports(tmp_path):
    """The model kept choosing 1080 despite the notebook. Make the operator's
    product ports a deterministic priority list, not a suggestion."""
    runtime = AgentRuntime(
        root=tmp_path,
        agent_id="agent-test",
        job_id="job-test",
        kind="gezinme",
        initial_input="",
        emit=lambda *args, **kwargs: None,
        stopped=lambda: False,
    )
    priority = runtime._priority_hunt_ports()
    assert 12323 in priority
    assert 8000 in priority
    assert 10000 in priority
    # script-kiddie legacy ports must come after the operator's product ports
    assert priority.index(12323) < priority.index(3128) if 3128 in priority else True
    assert priority.index(8000) < priority.index(1080) if 1080 in priority else True


def test_recovery_restarts_persisted_running_agent(tmp_path):
    """Regression: after an agentd restart every persisted running agent became
    'unknown' and stayed dead until the operator manually created a new one.
    Recovery must re-launch the worker and return it to running."""
    import services.agentd.supervisor as sup
    from services.agentd.state import StateStore

    root = tmp_path / "agentd"
    store = StateStore(root)
    agent = store.create_agent("gezinme", "kalici", None, "devam et")
    store.update_agent(agent["agent_id"], state="running", pid=12345, process_group=12345)

    import asyncio

    supervisor = sup.Supervisor.__new__(sup.Supervisor)
    supervisor.root = root
    supervisor.store = store
    supervisor._handles = {}
    restarted: list[str] = []

    async def fake_start(command: dict) -> dict:
        restarted.append(command["agent_id"])
        return {"agent_id": command["agent_id"], "pid": 999}

    supervisor._start = fake_start
    asyncio.run(supervisor._recover_persisted_processes())

    refreshed = store.get_agent(agent["agent_id"])
    assert restarted == [agent["agent_id"]], "persisted running agent must be restarted"
    assert refreshed["state"] in {"running", "created"}, refreshed["state"]
    assert refreshed["state"] != "unknown"


def test_open_port_validation_has_no_arbitrary_cap(tmp_path):
    """A full port scan can produce thousands of open ports; every one must be
    worked instead of stopping at an invented 64."""
    runtime = AgentRuntime(
        root=tmp_path,
        agent_id="agent-test",
        job_id="job-test",
        kind="gezinme",
        initial_input="",
        emit=lambda *args, **kwargs: None,
        stopped=lambda: False,
    )
    runtime._validate_port_direct = (
        lambda host, port, target_url, protocols: {"results": [], "validated": []}
    )
    result = runtime._validate_open_ports("193.233.126.126", list(range(1, 71)))
    assert result["checked"] == 70
    assert result["pending"] == 0


def test_expand_live_ip_registers_open_ports_for_validation(tmp_path):
    """Vertical expansion is the same flow as a full port scan: every open port
    becomes work to validate instead of being shown and dropped."""
    import services.agentd.ai_runtime as rt

    runtime = AgentRuntime(
        root=tmp_path,
        agent_id="agent-test",
        job_id="job-test",
        kind="gezinme",
        initial_input="",
        emit=lambda *args, **kwargs: None,
        stopped=lambda: False,
    )
    original = rt.socket.create_connection

    class FakeConn:
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def fake(addr, timeout=None):
        if addr[1] in (1080, 3128):
            return FakeConn()
        raise OSError("closed")

    rt.socket.create_connection = fake
    try:
        result = runtime._expand_live_ip({
            "ip": "193.233.126.126",
            "ports": [1080, 3128, 9999],
            "concurrency": 4,
            "timeout": 0.05,
        })
    finally:
        rt.socket.create_connection = original
    assert result["open_port_count"] == 2
    assert runtime._pending_open_ports() == [
        {"host": "193.233.126.126", "port": 1080},
        {"host": "193.233.126.126", "port": 3128},
    ]


def test_invoke_port_scan_validates_every_open_port(tmp_path):
    """The full tool flow: port_scan_live_ip finds open ports and every one of
    them is validated before the next planner turn."""
    import services.agentd.ai_runtime as rt

    runtime = AgentRuntime(
        root=tmp_path,
        agent_id="agent-test",
        job_id="job-test",
        kind="gezinme",
        initial_input="",
        emit=lambda *args, **kwargs: None,
        stopped=lambda: False,
    )
    original = rt.socket.create_connection

    class FakeConn:
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def fake(addr, timeout=None):
        if addr[1] in (22, 8000):
            return FakeConn()
        raise OSError("closed")

    rt.socket.create_connection = fake
    runtime._masscan_enumerate_ports = lambda ip, rng, rate: [22, 8000, 9999]
    probed: list[int] = []

    def fake_validate(host, port, target_url, protocols):
        probed.append(port)
        return {"results": [], "validated": []}

    runtime._validate_port_direct = fake_validate
    try:
        runtime._invoke("port_scan_live_ip", {
            "ip": "193.233.126.126",
            "port_range": "1-65535",
            "concurrency": 1024,
            "timeout": 0.05,
        })
    finally:
        rt.socket.create_connection = original
    result = runtime.last_tool_result
    assert result["open_port_count"] == 2
    assert result["validation_total"] == 2
    assert result["validated_ports"] == 2
    assert result["pending_open_ports"] == 0
    assert sorted(probed) == [22, 8000]


def test_port_scan_evidence_survives_observation_window_trim(tmp_path):
    """The live agent lost its L4 evidence when the 100-item observation window
    rolled over. A real full-port scan must stay valid for the whole run."""
    runtime = AgentRuntime(
        root=tmp_path,
        agent_id="agent-test",
        job_id="job-test",
        kind="gezinme",
        initial_input="",
        emit=lambda *args, **kwargs: None,
        stopped=lambda: False,
    )
    runtime._absorb_observation_facts({
        "tool": "port_scan_live_ip",
        "result": {
            "ip": "193.233.126.126",
            "open_ports": [8000],
        },
    })
    runtime.observations = [{"tool": "runtime_context", "result": {}}]
    facts = runtime._hunt_facts()
    assert "193.233.126.126" in facts["live_ips"]
    assert runtime._target_provenance_error(
        "port_scan_live_ip", {"ip": "193.233.126.126"}
    ) is None
    assert runtime._target_provenance_error(
        "validate_proxy", {"host": "193.233.126.126", "port": 8000}
    ) is None


def test_myip_owner_ranges_become_provider_target_evidence(tmp_path):
    """myip.ms depth (All Owner IP Ranges / Other Sites on IP) must feed every
    provider range into the target evidence, not just the parent range."""
    runtime = AgentRuntime(
        root=tmp_path,
        agent_id="agent-test",
        job_id="job-test",
        kind="gezinme",
        initial_input="",
        emit=lambda *args, **kwargs: None,
        stopped=lambda: False,
    )
    runtime.observations.append({
        "tool": "browse_public_source",
        "result": {
            "url": "https://myip.ms/info/whois/158.173.74.217",
            "status": 200,
            "body_preview": "",
            "owner_ranges": [
                "198.55.30.0/24",
                "157.97.120.0/24",
                "158.173.74.0/24",
            ],
        },
    })
    facts = runtime._hunt_facts()
    cidrs = {str(cidr) for cidr in facts["cidrs"]}
    assert {
        "198.55.30.0/24",
        "157.97.120.0/24",
        "158.173.74.0/24",
    } <= cidrs


def test_tool_outcomes_are_persisted_and_exposed_to_planner(tmp_path):
    """Planner feedback must be the real outcome of the last tool calls, not a
    score invented by the code."""
    import json

    runtime = AgentRuntime(
        root=tmp_path,
        agent_id="agent-test",
        job_id="job-test",
        kind="gezinme",
        initial_input="",
        emit=lambda *args, **kwargs: None,
        stopped=lambda: False,
    )
    runtime._record_outcome(
        "masscan_liveness",
        {"cidr": "79.119.0.0/16", "ports": [7777]},
        {"discovered": [{"ip": "79.119.0.62", "port": 7777}], "cidr": "79.119.0.0/16"},
        12.5,
    )
    path = runtime.output_dir / "outcomes.jsonl"
    record = json.loads(path.read_text(encoding="utf-8").splitlines()[-1])
    assert record["tool"] == "masscan_liveness"
    assert record["l4_positive_count"] == 1
    assert record["error_class"] is None
    snapshot = runtime._planner_snapshot()
    assert snapshot["recent_outcomes"][-1]["tool"] == "masscan_liveness"
    assert snapshot["durable_evidence"] == {}


def test_real_l4_evidence_survives_agent_restart(tmp_path):
    """A worker restart must not force the hunter to rediscover L4 evidence it
    already paid for."""
    runtime = AgentRuntime(
        root=tmp_path,
        agent_id="agent-test",
        job_id="job-test",
        kind="gezinme",
        initial_input="",
        emit=lambda *args, **kwargs: None,
        stopped=lambda: False,
    )
    runtime._absorb_observation_facts({
        "tool": "masscan_liveness",
        "result": {"discovered": [{"ip": "193.233.126.126", "port": 7777}]},
    })
    restarted = AgentRuntime(
        root=tmp_path,
        agent_id="agent-test",
        job_id="job-test",
        kind="gezinme",
        initial_input="",
        emit=lambda *args, **kwargs: None,
        stopped=lambda: False,
    )
    facts = restarted._hunt_facts()
    assert "193.233.126.126" in facts["live_ips"]


def test_l7_outcome_records_real_egress_truthfully(tmp_path):
    runtime = AgentRuntime(
        root=tmp_path,
        agent_id="agent-test",
        job_id="job-test",
        kind="gezinme",
        initial_input="",
        emit=lambda *args, **kwargs: None,
        stopped=lambda: False,
    )
    runtime._record_outcome(
        "validate_proxy",
        {"host": "79.119.0.62", "port": 7777, "protocols": ["http_connect"]},
        {
            "host": "79.119.0.62",
            "port": 7777,
            "results": [{"protocol": "http_connect", "egress_confirmed": True}],
            "validated": [{"protocol": "http_connect", "egress_confirmed": True}],
        },
        30.0,
    )
    record = runtime._outcome_records[-1]
    assert record["egress_confirmed"] is True
    assert record["l7_validated_count"] == 1
    assert record["l7_results"] == [
        {"protocol": "http_connect", "egress_confirmed": True}
    ]


def test_claude_planner_decide_passes_prompt_via_stdin_pipe(monkeypatch):
    """Claude harness must receive prompt on stdin, avoiding Linux ARG_MAX / E2BIG."""
    from services.agentd.ai_runtime import claude_planner_decide
    import subprocess

    captured_call = {}

    def fake_run(cmd, input=None, capture_output=False, text=False, timeout=None, env=None, check=False):
        captured_call["cmd"] = cmd
        captured_call["input"] = input
        return subprocess.CompletedProcess(
            args=cmd,
            returncode=0,
            stdout='{"action": "research", "requested_tools": ["browse_public_source"], "resource_plan": {"tool_arguments": {"browse_public_source": {"url": "https://myip.ms/"}}}}',
            stderr="",
        )

    monkeypatch.setattr(ai_runtime, "_claude_planner_binary", lambda: "/usr/bin/claude")
    monkeypatch.setattr(subprocess, "run", fake_run)

    snapshot = {"agent_id": "test", "ports": list(range(1000))}
    decision = claude_planner_decide(snapshot)

    assert captured_call["cmd"] == ["/usr/bin/claude", "-p"]
    assert captured_call["input"] is not None
    assert "SNAPSHOT:" in captured_call["input"]
    assert decision["action"] == "research"


def test_sanitize_for_snapshot_compacts_massive_port_lists():
    from services.agentd.ai_runtime import _sanitize_for_snapshot

    payload = {
        "ip": "1.2.3.4",
        "open_ports": list(range(5000)),
        "masscan_reported": list(range(20000)),
    }
    sanitized = _sanitize_for_snapshot(payload, max_list=25)
    assert len(sanitized["open_ports"]) == 25
    assert sanitized["open_ports_total_count"] == 5000
    assert len(sanitized["masscan_reported"]) == 25
    assert sanitized["masscan_reported_total_count"] == 20000


def test_tool_arguments_clamps_timeout_and_concurrency_instead_of_failing():
    from services.agentd.ai_runtime import validate_tool_arguments

    validated = validate_tool_arguments(
        "expand_live_ip",
        {
            "ip": "1.2.3.4",
            "ports": [8000],
            "timeout": 25.0,  # exceeds previous 10.0 limit
            "concurrency": 4096,  # exceeds previous 1024 limit
        },
    )
    assert validated["timeout"] == 10.0
    assert validated["concurrency"] == 1024


def test_autonomous_hunt_decision_targets_pending_or_unscanned(tmp_path):
    runtime = AgentRuntime(
        root=tmp_path,
        agent_id="agent-test",
        job_id="job-test",
        kind="gezinme",
        initial_input="",
        emit=lambda *args, **kwargs: None,
        stopped=lambda: False,
    )
    # Add an unvalidated IP
    runtime._fact_store["live_ips"].add("1.2.3.4")
    decision = runtime._autonomous_hunt_decision()
    assert decision is not None
    assert decision["action"] == "expand"
    assert "port_scan_live_ip" in decision["requested_tools"]

