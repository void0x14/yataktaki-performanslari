from proxy_pipeline.otonom import yurut

def test_zincir_verilen_baslangicla(tmp_path, monkeypatch):
    import proxy_pipeline.discovery.seed as baslangic
    monkeypatch.setattr(baslangic, "lookup_seed_ip",
                        lambda ip: {"cidr": "198.51.100.0/24", "asn": None, "provenance": "sınama",
                                    "scent": "squid cache hosting"})
    adimlar = []
    sonuc = yurut("198.51.100.7", bak=lambda a, b: adimlar.append(a))
    assert sonuc["tamam"] is True
    assert [a for a in adimlar] == ["başlangıç", "aralık", "beyin", "görev biçimi", "karar", "kuru-komut"]
    assert "yapay zekâ havuzu" in sonuc["beyin"]
    assert "masscan" in sonuc["komut"][0]

def test_zincir_bos_girdiyle_kendi_urunu_secer(tmp_path, monkeypatch):
    import proxy_pipeline.discovery.otonom_bul as bulus
    monkeypatch.setattr(bulus, "bul",
                        lambda: {"cidr": "198.51.100.0/24", "asn": None, "provenance": "sınama-buluş",
                                 "scent": "squid cache hosting"})
    adimlar = []
    sonuc = yurut("", bak=lambda a, b: adimlar.append(a))
    assert sonuc["tamam"] is True
    assert adimlar[0] == "başlangıç"
    assert sonuc["aralik"] == "198.51.100.0/24"
    assert "masscan" in sonuc["komut"][0]


def test_autonomous_discovery_has_no_public_resolver_bootstrap(monkeypatch, tmp_path):
    import proxy_pipeline.discovery.otonom_bul as bulus

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(bulus, "_izden_taranmamis", lambda _ignored: None)
    monkeypatch.setattr(bulus, "_ripestat_taranmamis", lambda _ignored: None)
    monkeypatch.setattr(bulus, "ONYUKLEME", [])

    assert bulus.bul() is None


def test_empty_autonomous_discovery_stops_without_a_scan(monkeypatch):
    import proxy_pipeline.discovery.otonom_bul as bulus

    monkeypatch.setattr(bulus, "bul", lambda: None)
    result = yurut("")

    assert result["tamam"] is False
    assert "koku" in result["neden"].lower()
