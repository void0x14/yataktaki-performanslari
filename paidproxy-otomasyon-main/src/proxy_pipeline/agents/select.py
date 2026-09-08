"""Beyin seçimi: izinli dış çıkarım havuzu, ardından yerleşik akıl yürütme.

- Havuz MiMo/Gemini yönlendirmesini bağlama göre yapar; gerekirse ikinci ajanı incelemeye alır.
- Adres ve anahtarlar yalnız ortamdan okunur; dosyaya yazılmaz.
- Hiçbiri yanıt vermezse yerleşik akıl yürütme zinciri sürdürür; bu durum kayda düşer.
- Dönen etiket pencereye yazılır; gizli dal yoktur.
"""
from __future__ import annotations

BEYIN = "yapay zekâ havuzu"

def select_routes(journal=None):
    from proxy_pipeline.agents.loader import load_routes
    from proxy_pipeline.agents.ai_havuz import HavuzBeyni
    from proxy_pipeline.agents.wander import WanderAgent
    try:
        disaridan = load_routes()
    except Exception:
        disaridan = []
    havuz = HavuzBeyni()
    yerlesik = WanderAgent(journal=journal) if journal else WanderAgent()
    yollar = [havuz] + list(disaridan) + [yerlesik]
    adlar = "+".join(getattr(r, "version", "beyin") for r in yollar)
    return yollar, f"{BEYIN} ({adlar})", False
