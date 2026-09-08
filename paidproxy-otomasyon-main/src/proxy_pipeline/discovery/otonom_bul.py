"""Otonom buluş: girdi boşken gözlenmiş av kaynağından aday seçer.

Önce yürüyüşteki taranmamış kanıt, sonra RIPEstat duyuruları incelenir.
Kaynak ve koku yoksa aday uydurulmaz; görünür biçimde boş sonuç döner.
Taranmış aralık günlüğe ve ize bakılarak atlanır; aynı kapı iki kez çalınmaz.
"""
from __future__ import annotations
import ipaddress
import re
from pathlib import Path

# Public resolver/Cloudflare bootstrap is intentionally absent. A cold start
# without an observed source is a visible no-candidate result, never a scan.
ONYUKLEME: list[dict] = []

TARAMA_IZI = re.compile(r"canl[ıi]-tarama|canlı tarama sonucu", re.IGNORECASE)
ADRES_IZI = re.compile(r"\d+\.\d+\.\d+\.\d+(?:/\d{1,2})?")

def _ebeveyn(cidr: str) -> str:
    ag = ipaddress.ip_network(cidr, strict=False)
    return str(ag.supernet(new_prefix=24)) if ag.prefixlen > 24 else str(ag)

def tarananlar() -> set:
    """Günlük ve izde taraması bitmiş aralıkların /24 ebeveynleri."""
    bulunan: set = set()
    gunlukler = sorted(Path("var/journal").glob("gunluk-*.md"))
    for gun in gunlukler[-7:]:
        try:
            metin = gun.read_text(encoding="utf-8")
        except OSError:
            continue
        for satir in metin.splitlines():
            if "canlı tarama sonucu" not in satir:
                continue
            for parc in ADRES_IZI.findall(satir):
                try:
                    bulunan.add(_ebeveyn(parc if "/" in parc else parc + "/32"))
                except ValueError:
                    pass
    iz = Path("var/yuruyus/yuruyus.jsonl")
    try:
        satirlar = iz.read_text(encoding="utf-8").splitlines()[-2000:]
    except OSError:
        satirlar = []
    for satir in satirlar:
        if not TARAMA_IZI.search(satir):
            continue
        for parc in ADRES_IZI.findall(satir):
            try:
                bulunan.add(_ebeveyn(parc if "/" in parc else parc + "/32"))
            except ValueError:
                pass
    return bulunan

def _temizle(cidr: str, atlanacak: set) -> bool:
    try:
        ag = ipaddress.ip_network(cidr, strict=False)
    except ValueError:
        return False
    if ag.is_private or ag.is_loopback or ag.is_multicast:
        return False
    return _ebeveyn(str(ag)) not in atlanacak

def _izden_taranmamis(atlanacak: set) -> dict | None:
    iz = Path("var/yuruyus/yuruyus.jsonl")
    try:
        satirlar = iz.read_text(encoding="utf-8").splitlines()[-400:]
    except FileNotFoundError:
        return None
    for satir in reversed(satirlar):
        for parc in ADRES_IZI.findall(satir):
            tam = parc if "/" in parc else parc + "/32"
            if not _temizle(tam, atlanacak):
                continue
            ag = ipaddress.ip_network(tam, strict=False)
            hedef = ag if ag.prefixlen <= 24 else ag.supernet(new_prefix=24)
            return {"cidr": str(hedef), "asn": None, "provenance": "otonom-iz:kendi-geçmişi"}
    return None

# Cloudflare / public-resolver bootstrap is forbidden. No default ASN.
YASAK_ASN = {13335, 15169, 16509, 8075, 32934}

def _ripestat_kokulu_asn() -> int | None:
    """RIPEstat arama metninden hosting/cache kokusu; yasak ASN yok."""
    import json
    import urllib.request
    for kelime in ("colo hosting", "cache proxy", "broadband static"):
        url = "https://stat.ripe.net/data/searchcomplete/data.json?resource=" + kelime.replace(" ", "%20")
        try:
            with urllib.request.urlopen(url, timeout=12) as r:
                data = json.loads(r.read().decode())
        except Exception:
            continue
        for cat in (data.get("data") or {}).get("categories") or []:
            for rec in cat.get("suggestions") or cat.get("records") or []:
                ham = str(rec.get("value") or rec.get("resource") or rec)
                m = re.search(r"AS(\d+)", ham, re.I)
                if not m:
                    continue
                asn = int(m.group(1))
                if asn in YASAK_ASN:
                    continue
                return asn
    return None

def _ripestat_taranmamis(atlanacak: set, asn: int | None = None) -> dict | None:
    try:
        if asn is None:
            asn = _ripestat_kokulu_asn()
        if asn is None or int(asn) in YASAK_ASN:
            return None
        from proxy_pipeline.discovery.sibling import sibling_prefixes
        kardes = sibling_prefixes(int(asn))
        for pref in kardes.get("ipv4", []) or []:
            if not _temizle(str(pref), atlanacak):
                continue
            return {"cidr": str(pref), "asn": int(asn), "provenance": f"otonom-ripestat:koku-as{asn}"}
    except Exception:
        return None
    return None

def bul() -> dict | None:
    from proxy_pipeline.yuruyus import kaydet
    atlanacak = tarananlar()
    bulunan = _izden_taranmamis(atlanacak)
    if bulunan:
        kaydet("otonom-buluş", bulunan["cidr"], bulunan["provenance"])
        return bulunan
    bulunan = _ripestat_taranmamis(atlanacak)
    if bulunan:
        kaydet("otonom-buluş", bulunan["cidr"], bulunan["provenance"])
        return bulunan
    kaydet("otonom-buluş", "yok", "av kaynağı/koku bulunamadı; tarama yok")
    return None
