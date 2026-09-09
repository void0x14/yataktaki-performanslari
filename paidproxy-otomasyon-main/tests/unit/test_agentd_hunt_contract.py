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
