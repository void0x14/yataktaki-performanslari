"""Tarama planı: yüksek port aralıkları ve yatay/dikey genişleme.

- Aralık dosyaları satır satır "başlangıç-bitiş" yazar; tarama dizesine çevrilir.
- Dikey genişleme: canlı çıkan IP aynı kalır, denenmemiş sonraki bant taranır.
- Yatay genişleme: aynı üst aralıktaki taranmamış dilimler döner.
- Hız yapay zekânın kaynağından gelir; üst sınırda tek satır uyarı düşer.
"""
from __future__ import annotations
import ipaddress
import re
from pathlib import Path as _P

ARALIK_IZI = re.compile(r"^(\d{1,5})\s*-\s*(\d{1,5})$")
VARSAYILAN_DOSYA = _P("var/port-araliklari/yuksek.txt")
VARSAYILAN_HIZ = 100
AZAMI_HIZ = 1000000

def port_araliklarini_oku(yol=_P("var/port-araliklari/yuksek.txt")) -> str:
    bantlar = []
    for satir in _P(yol).read_text(encoding="utf-8").splitlines():
        satir = satir.strip()
        if not satir or satir.startswith("#"):
            continue
        es = ARALIK_IZI.match(satir)
        if not es:
            continue
        bas, bit = int(es.group(1)), int(es.group(2))
        if 1 <= bas <= bit <= 65535:
            bantlar.append(f"{bas}-{bit}")
    if not bantlar:
        raise ValueError("aralık dosyası boş")
    return ",".join(bantlar)

def bant_listesi(yol=_P("var/port-araliklari/yuksek.txt")) -> list:
    return port_araliklarini_oku(yol).split(",")

def dikey_genislet(ip: str, denenen: list, tum: list | None = None) -> tuple:
    havuz = list(tum) if tum else bant_listesi()
    for bant in havuz:
        if bant not in (denenen or []):
            return f"{ipaddress.ip_address(ip)}/32", bant
    return f"{ipaddress.ip_address(ip)}/32", havuz[0]

def yatay_genislet(ebeveyn_cidr: str, taranan_ebeveynler: set, dilim: int = 28) -> str | None:
    ag = ipaddress.ip_network(ebeveyn_cidr, strict=False)
    for alt in ag.subnets(new_prefix=dilim):
        if str(alt) not in taranan_ebeveynler and str(alt.supernet(new_prefix=24)) not in taranan_ebeveynler:
            return str(alt)
    return None

def hiz_karari(kaynak: dict | None) -> tuple:
    try:
        hiz = int((kaynak or {}).get("hiz", VARSAYILAN_HIZ))
    except (ValueError, TypeError):
        hiz = VARSAYILAN_HIZ
    hiz = max(50, min(AZAMI_HIZ, hiz))
    uyari = ""
    if hiz > 100000:
        uyari = "yüksek hız: barındıran taraf huysuzlanabilir, gözün üstünde olsun"
    return hiz, uyari
