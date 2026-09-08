def test_taranmis_aralik_atlanir(tmp_path, monkeypatch):
    import proxy_pipeline.discovery.otonom_bul as b
    gunluk = tmp_path / "gunluk-x.md"
    gunluk.write_text("- x [s] canlı tarama sonucu: 9.9.9.0/28 sessiz\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    (tmp_path / "var" / "journal").mkdir(parents=True, exist_ok=True)
    gunluk.rename(tmp_path / "var" / "journal" / "gunluk-x.md")
    assert "9.9.9.0/24" in b.tarananlar()
    assert b._temizle("9.9.9.5/28", {"9.9.9.0/24"}) is False
    assert b._temizle("8.8.8.0/24", {"9.9.9.0/24"}) is True
