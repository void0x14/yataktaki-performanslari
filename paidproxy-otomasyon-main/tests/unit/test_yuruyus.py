from proxy_pipeline import yuruyus

def test_kaydet_oku(tmp_path, monkeypatch):
    iz = tmp_path / "y.jsonl"
    monkeypatch.setattr(yuruyus, "IZ", iz)
    yuruyus.kaydet("rdap", "1.1.1.1", "bulgu-x")
    adimlar = yuruyus.son(yol=iz)
    assert len(adimlar) == 1
    assert adimlar[0]["adres"] == "1.1.1.1"

def test_yoksa_bos_liste(tmp_path):
    assert yuruyus.son(yol=tmp_path / "yok.jsonl") == []
