from proxy_pipeline.agents import ai_havuz


def test_provider_settings_change_without_restarting_python(tmp_path, monkeypatch):
    keys = tmp_path / "keys.txt"
    keys.write_text("MIMO_API_KEY=tp-first\n", encoding="utf-8")
    monkeypatch.setattr(ai_havuz, "ANAHTAR_DOSYASI", keys)
    monkeypatch.setattr(ai_havuz, "_YUKLENDI", False)
    assert ai_havuz.saglayicilar()[0]["anahtar"] == "tp-first"

    keys.write_text("MIMO_API_KEY=tp-second\n", encoding="utf-8")
    assert ai_havuz.saglayicilar()[0]["anahtar"] == "tp-second"
    keys.unlink()
    assert [item["ad"] for item in ai_havuz.saglayicilar()] == ["gemini-web2api"]
