"""Yürüyüş izi: ajanın baktığı her yer buraya düşer, göz paneli buradan okur."""
from __future__ import annotations
import json
from datetime import datetime
from pathlib import Path

IZ = Path("var/yuruyus/yuruyus.jsonl")

def kaydet(kaynak: str, adres: str, bulgu: str = "", kim="gezgin") -> dict:
    IZ.parent.mkdir(parents=True, exist_ok=True)
    kayit = {"zaman": datetime.now().isoformat(timespec="seconds"), "kim": kim,
             "kaynak": kaynak, "adres": adres, "bulgu": bulgu[:300]}
    with IZ.open("a", encoding="utf-8") as h:
        h.write(json.dumps(kayit, ensure_ascii=True) + "\n")
    return kayit

def son(kac=30, yol=IZ) -> list:
    try:
        satirlar = Path(yol).read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []
    cikti = []
    for s in satirlar[-kac:]:
        try:
            cikti.append(json.loads(s))
        except Exception:
            continue
    return cikti
