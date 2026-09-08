def test_aralik_dosyasi_tarama_dizesine_donuser(tmp_path):
    from proxy_pipeline.tarama_plani import port_araliklarini_oku
    dosya = tmp_path / "yuksek.txt"
    dosya.write_text("30000-30999\n40000-40999\n# yorum\n", encoding="utf-8")
    assert port_araliklarini_oku(dosya) == "30000-30999,40000-40999"

def test_dikey_genisleme_ayni_ip_yeni_bant():
    from proxy_pipeline.tarama_plani import dikey_genislet
    hedef, bant = dikey_genislet("198.51.100.7", ["30000-30999"], ["30000-30999", "40000-40999"])
    assert hedef == "198.51.100.7/32" and bant == "40000-40999"

def test_hiz_karari_sinirlar_ve_uyarir():
    from proxy_pipeline.tarama_plani import hiz_karari
    hiz, uyari = hiz_karari({"hiz": 5000000})
    assert hiz == 1000000 and uyari
    hiz, uyari = hiz_karari({})
    assert hiz == 100 and not uyari
