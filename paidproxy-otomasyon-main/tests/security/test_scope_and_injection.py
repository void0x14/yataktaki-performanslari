import pytest

from proxy_pipeline.plugins.registry import PluginManifest, PluginRegistry
from proxy_pipeline.sources.http_connector import JsonSourceConnector
from proxy_pipeline.sources.catalog import SourceMetadata


class Healthy:
    name = "x"
    version = "1"

    def health(self):
        return True

def test_https_only_connector_and_host_allowlist():
    meta = SourceMetadata("x", "test", "json", "local", enabled=True)
    with pytest.raises(ValueError):
        JsonSourceConnector(meta, "http://example.com/data")
    with pytest.raises(ValueError):
        JsonSourceConnector(meta, "https://evil.example/data", allowed_hosts=("good.example",))


def test_unrestricted_url_plugin_rejected():
    with pytest.raises(PermissionError):
        PluginRegistry().register(PluginManifest("p", "tool", "1", ("unrestricted_url",), {}), Healthy())
