import asyncio
import json

import pytest

from services.agentd.kahin_source import collect_myip_source


def test_kahin_source_rejects_non_myip_host():
    with pytest.raises(ValueError, match="myip.ms"):
        collect_myip_source("https://example.org/", runner=lambda url: {})


def test_kahin_source_combines_visual_ocr_and_dom_into_observed_facts(tmp_path):

    async def fake_runner(url):
        assert url == "https://myip.ms/"
        return {
            "navigation": {"url": url},
            "screenshot_bytes": b"PNG",
            "ocr": {"text": "AS64501 9.9.9.9 9.9.9.0/24"},
            "dom_text": "Example broadband reseller ASN 64501",
        }

    result = collect_myip_source("https://myip.ms/", runner=fake_runner)
    assert result["source_provenance"] == "kahin-mirage-google-vision"
    assert result["observed_ips"] == ["9.9.9.9"]
    assert result["observed_cidrs"] == ["9.9.9.0/24"]
    assert result["observed_asns"] == [64501]
    assert result["_screenshot_bytes"] == b"PNG"
    assert "broadband reseller" in result["body_preview"]
