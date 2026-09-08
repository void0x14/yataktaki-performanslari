import json


def test_discovery_json_fetch_falls_back_to_stdlib_without_httpx(monkeypatch):
    import sys
    import proxy_pipeline.discovery.http_json as http_json

    monkeypatch.setitem(sys.modules, "httpx", None)

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return json.dumps({"ok": True, "source": "stdlib"}).encode()

    monkeypatch.setattr(http_json, "urlopen", lambda request, timeout: Response())
    assert http_json.get_json("https://rdap.example.test/data", timeout=2)["source"] == "stdlib"
