"""Yapay zekâ havuzu: yalnız MiMo ve Gemini Web2API ile karar üretir.

- Adres ve anahtarlar yalnız ``~/.config/paidproxy/keys.txt`` içinden okunur;
  kayda düşmez.
- Kayda yalnız sağlayıcı adı, model ve oldu/olmadı düşer.
- Bağlama göre MiMo, Gemini veya iki model birlikte seçilir.
"""
from __future__ import annotations
from pathlib import Path
import json
import re
from concurrent.futures import ThreadPoolExecutor
import urllib.parse
import urllib.request
import urllib.error
import http.client

YONERGE = (
    "Açık vekil avcısısın. CONNECT/SOCKS konuşan ve gerçekten dışarı çıkan uç avlarsın. "
    "Kamera, telnet, ADB, RTSP, CVE sömürüsü avın değil. "
    "Operatör koordinat vermez; koklarsın. Yalnız JSON döndür. "
    "Alanlar: action, targets, resource_plan, stop_condition, items, "
    "evidence, counter_evidence, risks, expected_value, confidence, alternatives, "
    "requested_tools. "
    "action: research, sample, expand, full_scan, defer, drop, reassess, deep_test. "
    "Bakış: RDAP/whois/org, kardeş aralık, RIPEstat, bgp.he.net, myip.ms. "
    "Koku: unutulmuş hosting/colo/reseller, broadband/PPPoE/abone, metinde cache/proxy/squid. "
    "Ölü zemin: örnek sayfalar, genel web araması, DNS/bootstrap hedefleri, genel sağlayıcı ana sayfaları ve 'proxy nedir'. Oraya bakma. "
    "ASN zar atma. Koku yoksa ısırma. "
    "İlk ısırık tek diş: squid/cache→3128; SOCKS/MikroTik/CPE→1080; HTTP proxy kokusu→8080/8888. "
    "Banner Squid ise o kapıda kal. Hikvision görüp kamera portuna sıçrama. "
    "Kan varsa aynı dişle komşular, sonra o IP'de dikey genişle. Bir kanda dağı tarama. "
    "Küçük ısırıkta sıfır kan: bırak, başka koku. "
    "requested_tools yalnız bağlamdaki available_tools adlarıdır; curl, http_get, whois_query, dns_lookup ve httpbin geçersizdir. "
    "Her requested_tools öğesi için resource_plan.tool_arguments içinde aynı isimli bir argüman nesnesi ver; "
    "browse_public_source için yalnız url; URL olarak yalnız katalogdaki source_examples/allowed_hosts değerlerini seç, "
    "observe_vds_surface için {}, inspect_owner_context için ip, "
    "list_owner_ranges için asn, masscan_liveness için cidr+tek ilk port, expand_live_ip için ip+ports, "
    "validate_proxy için host+port+target_url+protocols, publish_proxy için validation_ref ve kanıt alanlarını ver. "
    "VDS runtime preflight zaten gözlendiyse observe_vds_surface tekrar seçme; public-source kokuya geç. "
    "L4 yalnız masscan_liveness; canlı IP dikeyi yalnız expand_live_ip. "
    "Teslim için el sıkış + gerçek HTTP çıkışı. Çıkışsız açık port vekil sayılmaz. "
    "evidence'e ne kokladığını ve neden ısırdığını yaz. Sabit skor yok."
)

ANAHTAR_DOSYASI = Path.home() / ".config" / "paidproxy" / "keys.txt"

def _anahtarlari_yukle() -> None:
    global _DOSYA_AYARLARI
    ayarlar: dict[str, str] = {}
    try:
        for satir in ANAHTAR_DOSYASI.read_text(encoding="utf-8").splitlines():
            satir = satir.strip()
            if satir and not satir.startswith("#") and "=" in satir:
                ad, _, deger = satir.partition("=")
                ayarlar[ad.strip()] = deger.strip()
    except FileNotFoundError:
        pass
    _DOSYA_AYARLARI = ayarlar


_DOSYA_AYARLARI: dict[str, str] = {}


def _ayar(ad: str, varsayilan: str = "") -> str:
    "Yapılandırma yalnız keys.txt içinden okunur; ortam değişkenleri kullanılmaz."
    return _DOSYA_AYARLARI.get(ad, varsayilan)

_YUKLENDI = False

MIMO_MODEL = "mimo-v2.5-pro"
GEMINI_MODEL = "gemini-3.5-flash-thinking-lite"
MIMO_BASE_URL = "https://api.xiaomimimo.com/v1"
MIMO_TOKEN_PLAN_BASE_URL = "https://token-plan-cn.xiaomimimo.com/v1"
GEMINI_BASE_URL = "http://127.0.0.1:8081/v1"


def _ilk_ayar(*adlar: str) -> str:
    for ad in adlar:
        deger = _ayar(ad)
        if deger:
            return deger
    return ""

def saglayicilar() -> list:
    global _YUKLENDI
    _anahtarlari_yukle()
    _YUKLENDI = True

    kursun: list[dict] = []

    def ekle(ad: str, taban: str, anahtar: str, model: str, *, anahtar_gerekli: bool = True) -> None:
        if not model or (anahtar_gerekli and not anahtar):
            return
        kursun.append({
            "ad": ad,
            "taban": taban.rstrip("/"),
            "anahtar": anahtar,
            "model": model,
            "auth_header": "authorization",
        })

    mimo_anahtar = _ilk_ayar(
        "MIMO_API_KEY",
        "XIAOMI_MIMO_API_KEY",
        "MIMO_TOKEN_PLAN_API_KEY",
        "XIAOMI_TOKEN_PLAN_API_KEY",
        "XIAOMI_MIMO_TOKEN_PLAN_API_KEY",
        "XIAOMI_API_KEY",
    )
    if mimo_anahtar:
        mimo_taban = _ilk_ayar("MIMO_BASE_URL", "XIAOMI_MIMO_BASE_URL")
        if not mimo_taban and mimo_anahtar.startswith("tp-"):
            mimo_taban = _ayar("MIMO_TOKEN_PLAN_BASE_URL", MIMO_TOKEN_PLAN_BASE_URL)
        ekle(
            "mimo",
            mimo_taban or MIMO_BASE_URL,
            mimo_anahtar,
            MIMO_MODEL,
        )
        kursun[-1]["auth_header"] = "api-key"

    gemini_anahtar = _ilk_ayar(
        "GEMINI_WEB2API_API_KEY",
        "GEMINI_WEB2API_KEY",
        "GEMINI_API_KEY",
    )
    ekle(
        "gemini-web2api",
        _ilk_ayar(
            "GEMINI_WEB2API_BASE_URL",
            "GEMINI_BASE_URL",
            "GEMINI_API_BASE_URL",
        ) or GEMINI_BASE_URL,
        gemini_anahtar,
        GEMINI_MODEL,
        anahtar_gerekli=False,
    )

    return kursun

def _istek(
    taban: str,
    anahtar: str,
    model: str,
    govde: dict,
    sure: float = 25,
    tur: str = "acik-uyumlu",
    auth_header: str = "authorization",
) -> dict:
    veri = json.dumps(govde).encode()
    baslik = {"content-type": "application/json"}
    if anahtar:
        baslik[auth_header] = anahtar if auth_header == "api-key" else f"Bearer {anahtar}"
    istek = urllib.request.Request(f"{taban}/chat/completions", data=veri, headers=baslik, method="POST")
    with urllib.request.urlopen(istek, timeout=sure) as yanit:
        return json.load(yanit)

class ProviderOutputError(ValueError):
    """Sağlayıcının HTTP başarılı fakat karar JSON'u üretmediğini belirtir."""

def _safe_provider_error(exc: BaseException) -> str:
    "Gerçek HTTP nedenini sırrı ve istek gövdesini yazmadan özetler."
    if isinstance(exc, urllib.error.HTTPError):
        reason = re.sub(r"(authorization|api[_ -]?key|token|bearer)[^,; ]*", r"\1=<redacted>", str(exc.reason), flags=re.IGNORECASE)
        return f"HTTP {exc.code} {reason[:120]}"
    if isinstance(exc, urllib.error.URLError):
        reason = re.sub(r"(authorization|api[_ -]?key|token|bearer)[^,; ]*", r"\1=<redacted>", str(exc.reason), flags=re.IGNORECASE)
        return f"URL error {type(exc.reason).__name__}: {reason[:120]}"
    if isinstance(exc, http.client.BadStatusLine):
        return "BadStatusLine"
    return type(exc).__name__


def _content_as_text(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = []
        for part in value:
            if isinstance(part, str):
                parts.append(part)
                continue
            if not isinstance(part, dict):
                continue
            for key in ("text", "content", "value"):
                piece = part.get(key)
                if isinstance(piece, str):
                    parts.append(piece)
                    break
        return "\n".join(parts)
    return ""


def _provider_json_from_message(message: object) -> dict:
    if not isinstance(message, dict):
        raise ProviderOutputError("provider message shape invalid")
    decoder = json.JSONDecoder()
    for field in ("content", "reasoning_content"):
        text = _content_as_text(message.get(field)).strip()
        if not text:
            continue
        try:
            parsed = json.loads(text)
        except (TypeError, json.JSONDecodeError):
            parsed = None
        if isinstance(parsed, dict):
            return parsed
        for offset, character in enumerate(text):
            if character != "{":
                continue
            try:
                parsed, _end = decoder.raw_decode(text[offset:])
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                return parsed
    raise ProviderOutputError("provider message has no JSON object")

def _provider_decision(response: object) -> dict:
    if not isinstance(response, dict):
        raise ProviderOutputError("provider response shape invalid")
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise ProviderOutputError("provider response has no choices")
    return _provider_json_from_message(choices[0].get("message"))


EYLEMLER = {"research", "sample", "expand", "full_scan", "defer", "drop", "reassess", "deep_test"}

def _sayi(x, varsayilan=0) -> int:
    try:
        return int(x)
    except (ValueError, TypeError):
        return varsayilan

def _sozlesmeye_uyarla(karar: dict, context) -> dict:
    """Dış zekânın yanıtını çalıştırılabilir sözleşmeye döker.

    Hedef uydurmaz: aralık ve portlar yanıttan gelir, eksik zarf alanları
    boş değerle tamamlanır, öğe listesi boşsa yanıttaki hedeflerden kurulur.
    """
    karar = dict(karar or {})
    eylem = str(karar.get("action", "research"))
    if eylem not in EYLEMLER:
        eylem = "research"
    karar["action"] = eylem
    ham_hedefler = karar.get("targets", []) or []
    if isinstance(ham_hedefler, dict):
        ham_hedefler = [ham_hedefler]
    hedefler = []
    for h in ham_hedefler:
        try:
            cidr = str(h.get("cidr", "")).strip()
            if "/" not in cidr:
                continue
            portlar = []
            raw_ports = h.get("ports", []) or []
            if isinstance(raw_ports, (str, int, float)):
                raw_ports = [raw_ports]
            for x in raw_ports:
                v = _sayi(x, -1)
                if 1 <= v <= 65535:
                    portlar.append(v)
            raw_protocols = h.get("protocols", []) or []
            if isinstance(raw_protocols, str):
                raw_protocols = [raw_protocols]
            asn = h.get("asn")
            try:
                asn = int(str(asn).lstrip("AaSs")) if asn is not None else None
            except (ValueError, TypeError):
                asn = None
            hedefler.append({"cidr": cidr, "ports": portlar[:12],
                             "protocols": [str(x) for x in raw_protocols][:4],
                             "asn": asn})
        except (ValueError, TypeError, AttributeError):
            continue
    karar["targets"] = hedefler
    for alan in ("resource_plan", "stop_condition"):
        if not isinstance(karar.get(alan), dict):
            karar[alan] = {"not": str(karar.get(alan, ""))[:200]} if karar.get(alan) else {}
    for metin_alan in ("expected_value", "confidence"):
        if karar.get(metin_alan) is not None and not isinstance(karar.get(metin_alan), str):
            karar[metin_alan] = str(karar[metin_alan])
    for alan in ("evidence", "counter_evidence", "risks", "alternatives"):
        if not isinstance(karar.get(alan), list):
            karar[alan] = [str(karar[alan])] if karar.get(alan) else []
    for alan in ("decision_id", "raw_response_ref", "provider", "model"):
        if karar.get(alan) is not None and not isinstance(karar.get(alan), str):
            karar[alan] = str(karar[alan])
    ogeler = karar.get("items", []) or []
    if isinstance(ogeler, dict):
        ogeler = [ogeler]
    duzgun = []
    for o in ogeler:
        if not isinstance(o, dict):
            continue
        o = dict(o)
        o["candidate_id"] = str(o.get("candidate_id", getattr(context, "candidate_id", "aday")))
        o["action"] = str(o.get("action", eylem)) if str(o.get("action", eylem)) in EYLEMLER else eylem
        o["order_index"] = _sayi(o.get("order_index", 0))
        ht = o.get("targets", []) or []
        duzgun_hedef = []
        for h in ([ht] if isinstance(ht, dict) else ht):
            try:
                cidr = str(h.get("cidr", "")).strip()
                if "/" not in cidr:
                    continue
                duzgun_hedef.append({"cidr": cidr, "ports": [], "protocols": []})
            except (ValueError, TypeError, AttributeError):
                continue
        o["targets"] = duzgun_hedef or hedefler
        for alan in ("resource_allocation", "stop_expression"):
            if not isinstance(o.get(alan), dict):
                o[alan] = {"not": str(o.get(alan, ""))[:200]} if o.get(alan) else {}
        duzgun.append(o)
    if not duzgun:
        kim = str(getattr(context, "candidate_id", "aday"))
        duzgun = [{"candidate_id": kim, "action": eylem, "targets": hedefler,
                   "order_index": 0, "resource_allocation": {}, "stop_expression": {}}]
    karar["items"] = duzgun
    return karar

def _model_sec(taban: str, anahtar: str, istenen: str, auth_header: str = "authorization") -> str:
    if istenen:
        return istenen
    baslik = {}
    if anahtar:
        baslik[auth_header] = anahtar if auth_header == "api-key" else f"Bearer {anahtar}"
    istek = urllib.request.Request(f"{taban}/models", headers=baslik, method="GET")
    with urllib.request.urlopen(istek, timeout=8) as yanit:
        veri = json.load(yanit)
    return (veri.get("data") or [{}])[0].get("id", "")

def _provider_body(sag: dict, model: str, anlik: dict) -> dict:
    govde = {
        "model": model,
        "temperature": 0,
        "messages": [
            {"role": "system", "content": YONERGE},
            {"role": "user", "content": json.dumps(anlik, ensure_ascii=True)},
        ],
    }
    token_field = "max_completion_tokens" if sag.get("ad") == "mimo" else "max_tokens"
    govde[token_field] = int(sag.get("kredi", 1500))
    return govde

OLU_BELLEGI: dict = {}
OLU_SURESI = 300.0

class HavuzBeyni:
    version = "havuz-beyin-1"

    def decide(self, context) -> dict:
        from proxy_pipeline.yuruyus import kaydet
        from proxy_pipeline.agents.ruflo_orchestrator import route_plan

        anlik = {"candidate_id": getattr(context, "candidate_id", ""),
                 "decision_type": getattr(context, "decision_type", ""),
                 "snapshot": dict(getattr(context, "snapshot", {}) or {})}

        catalog = {provider["ad"]: provider for provider in saglayicilar()}
        tasks = route_plan(context, ensure=True).tasks
        selected = [catalog[task.provider] for task in tasks if task.provider in catalog]
        if not selected:
            raise RuntimeError("izinli yapay zekâ sağlayıcısı yapılandırılmamış")

        if len(selected) == 1:
            kararlar = [self._attempt(selected[0], anlik, context, kaydet)]
        else:
            with ThreadPoolExecutor(max_workers=len(selected), thread_name_prefix="ruflo-lite") as pool:
                gelecekler = [pool.submit(self._attempt, sag, anlik, context, kaydet) for sag in selected]
                kararlar = [gelecek.result() for gelecek in gelecekler]

        kararlar = [karar for karar in kararlar if karar is not None]
        if kararlar:
            karar = kararlar[0]
            if len(kararlar) > 1:
                karar = self._review(karar, kararlar[1])
            return karar

        # Seçilen rol ulaşılamazsa yine yalnız izinli iki sağlayıcıdan diğerine geç.
        for sag in saglayicilar():
            if sag in selected:
                continue
            karar = self._attempt(sag, anlik, context, kaydet)
            if karar is not None:
                return karar
        raise RuntimeError("yapay zekâ havuzu yanıt vermiyor")

    @staticmethod
    def _attempt(sag, anlik, context, kaydet):
        import time

        anahtar = (sag["ad"], sag["model"])
        simdi = time.time()
        if simdi - OLU_BELLEGI.get(anahtar, 0.0) < OLU_SURESI:
            kaydet("havuz", sag["ad"], "atlandı: az önce sessizdi")
            return None
        try:
            model = _model_sec(
                sag["taban"], sag["anahtar"], sag["model"], sag.get("auth_header", "authorization")
            )
            if not model or model != sag["model"]:
                raise ProviderOutputError("izinli model listede yok")
            govde = _provider_body(sag, model, anlik)
            ham = _istek(
                sag["taban"], sag["anahtar"], model, govde,
                tur=sag.get("tur", "acik-uyumlu"),
                auth_header=sag.get("auth_header", "authorization"),
            )
            try:
                karar = _provider_decision(ham)
            except ProviderOutputError:
                kaydet("havuz", sag["ad"], f"geçersiz sağlayıcı JSON'u: ProviderOutputError attempt=1 model={model}")
                ham = _istek(
                    sag["taban"], sag["anahtar"], model, govde,
                    tur=sag.get("tur", "acik-uyumlu"),
                    auth_header=sag.get("auth_header", "authorization"),
                )
                karar = _provider_decision(ham)
            karar["provider"] = sag["ad"]
            karar["model"] = model
            karar = _sozlesmeye_uyarla(karar, context)
            kaydet("havuz", sag["ad"], f"yanıt verdi ({model})")
            return karar
        except Exception as e:
            OLU_BELLEGI[anahtar] = time.time()
            kaydet("havuz", sag["ad"], f"yanıt yok: {_safe_provider_error(e)} model={sag['model']}")
            return None

    @staticmethod
    def _review(primary: dict, review: dict) -> dict:
        result = dict(primary)
        result["review_provider"] = review.get("provider")
        result["review_model"] = review.get("model")
        primary_signature = (primary.get("action"), primary.get("targets", []))
        review_signature = (review.get("action"), review.get("targets", []))
        if primary_signature == review_signature:
            result["evidence"] = list(result.get("evidence", [])) + [
                f"İkinci ajan uyumu: {review.get('provider', 'bilinmeyen')}"
            ]
        else:
            result["counter_evidence"] = list(result.get("counter_evidence", [])) + [
                f"İkinci ajan farklı karar verdi: {review.get('provider', 'bilinmeyen')} / {review.get('action', 'bilinmeyen')}"
            ]
            result["alternatives"] = list(result.get("alternatives", [])) + [
                f"İnceleme alternatifi: {review.get('action', 'bilinmeyen')}"
            ]
        return result
