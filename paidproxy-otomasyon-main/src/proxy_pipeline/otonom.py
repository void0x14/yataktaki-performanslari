"""Tek düğme: yapay zekâ bulur, denetler, orkestre eder, ilerletir.

Girdi boş olabilir; o zaman yapay zekâ kendi adayını seçer.
Araçlar (masscan, el sıkışma) yapay zekânın denetiminde çalışır.
Elle adım, onay ve bekleme yoktur. Her adım pencereye ve kayda akar.
"""
from __future__ import annotations

def yurut(baslangic: str = "", bak=None) -> dict:
    def duyuru(adim, bilgi=""):
        if bak:
            bak(adim, bilgi)
    from proxy_pipeline.discovery.seed_flow import resolve_seed_to_targets
    from proxy_pipeline.discovery.sibling import sibling_prefixes
    from proxy_pipeline.discovery.otonom_bul import bul as otonom_bulus
    from proxy_pipeline.decision.service import DecisionService
    from proxy_pipeline.domain.models import DecisionContext
    from proxy_pipeline.agents.select import select_routes, BEYIN
    from proxy_pipeline.flow import mark_high_ports
    from proxy_pipeline.tarama_plani import hiz_karari
    from proxy_pipeline.safety import KillSwitch, RunGate
    from proxy_pipeline.scanners.adapter import MasscanAdapter
    from proxy_pipeline.scanners.runner import MasscanRunner, operator_manifest
    from proxy_pipeline.yuruyus import kaydet

    giris = (baslangic or "").strip()
    if giris:
        duyuru("başlangıç", giris)
        cozum = resolve_seed_to_targets(giris)
        if not cozum.get("ok"):
            return {"tamam": False, "neden": cozum.get("reason")}
        aralik = cozum["targets"][0]["cidr"]
        asn = cozum["targets"][0].get("asn")
        koken = cozum["info"].get("provenance", "")
        discovery_snapshot = dict(cozum.get("info") or {})
    else:
        secim = otonom_bulus()
        if not secim:
            duyuru("başlangıç", "av kaynağı/koku bulunamadı; tarama yok")
            return {"tamam": False, "neden": "av kaynağı/koku bulunamadı; güvenli biçimde durdu"}
        aralik, asn, koken = secim["cidr"], secim.get("asn"), secim["provenance"]
        discovery_snapshot = dict(secim)
        duyuru("başlangıç", f"yapay zekâ seçti: {aralik} ({koken})")
    duyuru("aralık", f"{aralik} (asn={asn})")
    kardes_sayisi = 0
    if asn is not None:
        try:
            kardes = sibling_prefixes(int(asn))
            kardes_sayisi = kardes["count"]
            duyuru("kardeş", f"{kardes_sayisi} aralık")
        except Exception as e:
            duyuru("kardeş", f"bakılamadı: {e}")
    yollar, beyin, _ = select_routes()
    duyuru("beyin", beyin)
    hizmet = DecisionService(routes=yollar)
    etiket = giris or aralik
    tercih = "derin" if kardes_sayisi > 200 else "hizli"
    duyuru("görev biçimi", tercih)
    discovery_snapshot.update({"cidr": aralik, "baslangic_ip": giris or None, "model_tercihi": tercih,
                               "provenance": koken})
    baglam = DecisionContext("aday", f"otonom-{etiket}", discovery_snapshot, "oto-s", "oto-m")
    try:
        kayit = hizmet.decide(baglam, fresh=True)
    except Exception as e:
        return {"tamam": False, "neden": f"karar durdu: {e}"}
    karar = kayit.decision
    eylem_tr = {"sample": "örnekle", "research": "araştır", "expand": "genişlet",
                "full_scan": "tam-tara", "defer": "ertele", "drop": "bırak",
                "reassess": "yeniden-değerlendir", "deep_test": "derin-ele"}.get(karar.action.value, karar.action.value)
    duyuru("karar", f"{eylem_tr} neden={karar.expected_value}")
    hedefler = [(h.cidr, tuple(h.ports)) for h in karar.targets]
    if not hedefler or not hedefler[0][1]:
        duyuru("karar", "ilk port gerekçeli seçilmedi; tarama yok")
        return {"tamam": False, "neden": "AI ilk portu gerekçeli seçmedi; tarama yok", "karar": karar.action.value}
    cidr, portlar = hedefler[0]
    hiz, hiz_uyarisi = hiz_karari(getattr(karar, "resource_plan", {}) or {})
    dizge = str((getattr(karar, "resource_plan", {}) or {}).get("port_araligi", "") or "").strip() or None
    bildiri = operator_manifest(cidr, tuple(int(x) for x in portlar), port_dizgesi=dizge)
    KillSwitch().check()
    komut = MasscanRunner(MasscanAdapter(RunGate())).command(bildiri, rate=hiz)
    duyuru("kuru-komut", " ".join(komut))
    if hiz_uyarisi:
        duyuru("hız uyarısı", hiz_uyarisi)
    kaydet("otonom", etiket, f"{eylem_tr} {cidr}")
    return {"tamam": True, "karar": karar.action.value, "aralik": aralik,
            "kardes": kardes_sayisi, "komut": komut, "beyin": beyin, "hiz": hiz,
            "port_dizgesi": dizge,
            "portlar": mark_high_ports(portlar),
            "neden": karar.expected_value, "guven": karar.confidence}
