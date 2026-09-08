from types import SimpleNamespace

def test_canli_akış_sahte_telde_ucar(tmp_path):
    from proxy_pipeline.uzak_tara import yurut_canli
    from proxy_pipeline.validators.protocols import ValidationResult
    sahte_cikti = "open tcp 3128 198.51.100.7\n"
    class SahteDogru:
        def validate(self, ip, port, protokoller, timeout=3, **k):
            assert (ip, port) == ("198.51.100.7", 3128)
            return [SimpleNamespace(result=ValidationResult.VALIDATED, protocol="http_connect")]
    out = yurut_canli(None, "198.51.100.0/28", (3128,), hiz=50,
                      calistirici=lambda k: sahte_cikti, dogrulayici=SahteDogru(),
                      makara=tmp_path / "acik.txt", bulgu_dizini=tmp_path)
    assert out["tamam"] is True
    assert out["acik"] == [{"ip": "198.51.100.7", "port": 3128}]
    assert out["dogrulanan"][0]["protokol"] == "http_connect"
    assert "198.51.100.7" in (tmp_path / "acik.txt").read_text(encoding="utf-8")
    kayitlar = list(tmp_path.glob("bulgu-*.jsonl"))
    assert len(kayitlar) == 1

def test_bos_cikti_bulgu_yazmaz(tmp_path):
    from proxy_pipeline.uzak_tara import yurut_canli
    out = yurut_canli(None, "198.51.100.0/28", (3128,), hiz=50,
                      calistirici=lambda k: "#masscan\n",
                      makara=tmp_path / "acik.txt", bulgu_dizini=tmp_path)
    assert out["acik"] == [] and out["dogrulanan"] == []
    assert list(tmp_path.glob("bulgu-*.jsonl")) == []

def test_canli_cikti_durum_satirlarinda_durmaz(tmp_path):
    from proxy_pipeline.uzak_tara import yurut_canli
    from proxy_pipeline.validators.protocols import ValidationResult
    from types import SimpleNamespace
    sahte_cikti = ("Starting masscan 1.3.2\n"
                   "rate:  0.10-kpps,  8.40% done,   0:01:06 remaining, found=0\n"
                   "open tcp 3128 198.51.100.7\n")
    class SahteDogru:
        def validate(self, ip, port, protokoller, timeout=3, **k):
            return [SimpleNamespace(result=ValidationResult.TIMEOUT, protocol="http_connect")]
    out = yurut_canli(None, "198.51.100.0/28", (3128,), hiz=50,
                      calistirici=lambda k: sahte_cikti, dogrulayici=SahteDogru(),
                      makara=tmp_path / "acik.txt", bulgu_dizini=tmp_path)
    assert out["acik"] == [{"ip": "198.51.100.7", "port": 3128}]
    assert out["dogrulanan"] == []
