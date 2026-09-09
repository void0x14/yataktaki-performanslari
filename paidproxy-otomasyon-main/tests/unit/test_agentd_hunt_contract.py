import pytest

from services.agentd import ai_runtime
from services.agentd.ai_runtime import AgentRuntime, _hunter_instruction, validate_tool_arguments


def test_masscan_liveness_accepts_only_one_first_bite_port():
    accepted = validate_tool_arguments(
        "masscan_liveness",
        {"cidr": "9.9.9.0/24", "ports": [3128]},
    )
    assert accepted["ports"] == [3128]

    with pytest.raises(ValueError, match="tek ilk port"):
        validate_tool_arguments(
            "masscan_liveness",
            {"cidr": "9.9.9.0/24", "ports": [3128, 1080]},
        )

    with pytest.raises(ValueError, match="tek ilk port"):
        validate_tool_arguments(
            "masscan_liveness",
            {"cidr": "9.9.9.0/24", "port_spec": "3128-3129"},
        )


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
    enumerates ALL its open ports. Every open port becomes a candidate; one
    dead port must never discard the whole IP."""
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
    assert result["candidate_count"] == 2


def test_open_ports_become_independent_candidates(tmp_path):
    """Each open port is checked separately; the IP survives per-port failures."""
    runtime = AgentRuntime(
        root=tmp_path,
        agent_id="agent-test",
        job_id="job-test",
        kind="gezinme",
        initial_input="",
        emit=lambda *args, **kwargs: None,
        stopped=lambda: False,
    )
    candidates = runtime._candidates_from_ports("193.233.126.126", [16866, 41451])
    assert candidates == [
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


def test_pending_candidates_are_drained_without_llm_discretion(tmp_path):
    """Every candidate produced by a port scan must eventually be validated.
    The runtime must track the queue itself instead of hoping the planner
    remembers to list all 36 of them."""
    runtime = AgentRuntime(
        root=tmp_path,
        agent_id="agent-test",
        job_id="job-test",
        kind="gezinme",
        initial_input="",
        emit=lambda *args, **kwargs: None,
        stopped=lambda: False,
    )
    runtime._enqueue_candidates([
        {"host": "193.233.126.126", "port": 22},
        {"host": "193.233.126.126", "port": 8000},
        {"host": "193.233.126.179", "port": 16866},
    ])
    assert runtime._pending_candidates() == [
        {"host": "193.233.126.126", "port": 22},
        {"host": "193.233.126.126", "port": 8000},
        {"host": "193.233.126.179", "port": 16866},
    ]
    runtime._mark_candidate_validated({"host": "193.233.126.126", "port": 22})
    assert runtime._pending_candidates() == [
        {"host": "193.233.126.126", "port": 8000},
        {"host": "193.233.126.179", "port": 16866},
    ]


def test_port_scan_result_is_exposed_as_pending_work(tmp_path):
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
    assert result["candidate_count"] == 2
    assert runtime._pending_candidates() == [
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


def test_candidate_queue_drains_without_waiting_for_planner(tmp_path):
    """The planner must not be the bottleneck for mechanical validation:
    queued candidates are validated by the runtime, not one per LLM turn."""
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
    runtime._enqueue_candidates([
        {"host": "193.233.126.126", "port": 22},
        {"host": "193.233.126.126", "port": 8000},
        {"host": "193.233.126.179", "port": 16866},
    ])
    probed: list[tuple[str, int]] = []

    def fake_validate(host, port, target_url, protocols):
        probed.append((host, port))
        return {"protocols": protocols, "validated": [], "results": [], "egress": False}

    runtime._validate_candidate_direct = fake_validate
    drained = runtime._drain_candidate_queue(max_candidates=10)
    assert len(probed) == 3
    assert drained["checked"] == 3
    assert runtime._pending_candidates() == []
    assert drained["egress_hits"] == []


def test_drain_reports_egress_hit_when_candidate_works(tmp_path):
    runtime = AgentRuntime(
        root=tmp_path,
        agent_id="agent-test",
        job_id="job-test",
        kind="gezinme",
        initial_input="",
        emit=lambda *args, **kwargs: None,
        stopped=lambda: False,
    )
    runtime._enqueue_candidates([{"host": "1.2.3.4", "port": 3128}])

    def fake_validate(host, port, target_url, protocols):
        return {
            "protocols": protocols,
            "validated": [{"protocol": "http_connect", "egress_confirmed": True}],
            "results": [{"protocol": "http_connect", "egress_confirmed": True}],
            "egress": True,
        }

    runtime._validate_candidate_direct = fake_validate
    drained = runtime._drain_candidate_queue(max_candidates=10)
    assert drained["checked"] == 1
    assert drained["egress_hits"] == [{"host": "1.2.3.4", "port": 3128}]


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
