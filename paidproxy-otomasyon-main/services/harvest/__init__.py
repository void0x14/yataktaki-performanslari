"""Harvest: otonom proxy hasat boru hattı (VDS tarafı, stdlib-only).

Bağımsız dağıtılabilir paket — repo import zincirine ve pip bağımlılığına
ihtiyaç duymaz. VDS'e tek başına kopyalanıp çalışır.

Modüller:
  ripe      — RIPEstat hedef motoru (ülke/ASN/prefix, koku skoru, ölü zemin yasağı)
  classify  — 5-protokol L7 doğrulama + egress (v4/v6/rotate) sınıflandırma
  pipeline  — orkestratör: çapa → pilot ısırık → genleme → sınıflandırma → teslim
"""
