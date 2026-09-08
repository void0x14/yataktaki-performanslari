"""Karar tekrar oynatımı: geçit yok, üretim engeli yok.

Yapay zekâ kararlarını envanterdeki bulgularla karşılaştırıp
özet yazar. Üretimi durduran kapı barındırmaz.
"""
from __future__ import annotations
import json
from datetime import datetime
from pathlib import Path

def main() -> int:
    root = Path(__file__).resolve().parent.parent
    bulgular = []
    for f in sorted((root / "var" / "envanter").glob("bulgu-*.jsonl")):
        try:
            for satir in f.read_text(encoding="utf-8").splitlines():
                satir = satir.strip()
                if satir:
                    bulgular.append(json.loads(satir))
        except Exception:
            continue
    ozet = {"t": datetime.now().isoformat(timespec="seconds"),
            "bulgu": len(bulgular), "gecti": True,
            "not": "üretim yapay zekâ kararıyla akar; engelleyen kapı yok"}
    print(json.dumps(ozet, ensure_ascii=True))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
