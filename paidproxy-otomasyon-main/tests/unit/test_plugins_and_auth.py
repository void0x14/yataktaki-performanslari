import pytest

from proxy_pipeline.auth import Authorizer, Principal, Role
from proxy_pipeline.plugins.registry import PluginManifest, PluginRegistry
from proxy_pipeline.scheduler import Scheduler
from proxy_pipeline.safety import KillSwitch


class Healthy:
    name = "ok"
    version = "1"

    def health(self):
        return True


def test_plugin_forbids_shell_and_raw_sql():
    registry = PluginRegistry()
    with pytest.raises(PermissionError):
        registry.register(
            PluginManifest("bad", "tool", "1", ("shell",), {}),
            Healthy(),
        )


def test_rbac_roles():
    auth = Authorizer([Principal("v", Role.VIEWER), Principal("a", Role.ADMIN)])
    assert auth.allow("v", "read")
    assert not auth.allow("v", "kill")
    auth.require("a", "kill")


def test_scheduler_refuses_manifest_without_decision_id():
    sched = Scheduler(KillSwitch())
    with pytest.raises(ValueError):
        sched.enqueue(type("M", (), {"decision_id": "", "status": "committed"})())
