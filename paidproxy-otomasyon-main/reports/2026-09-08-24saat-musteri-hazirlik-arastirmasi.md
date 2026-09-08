# 24 saat müşteri-hazırlık araştırması

Oluşturulma: 2026-09-08T04:22:41+03:00
Dayandığı Git HEAD: `5bcb57877e90d1f0a921a6f153b964d885fcbf4c`
Kapsam: Kokpit (Tauri), VDS agentd, klasik `src/proxy_pipeline`, envanter, evaluation, son operasyon raporları. Canlı VDS yeniden yoklanmadı; kod + mevcut kanıt dosyaları esas alındı.

## Soru

24 saatte müşteriye sunulabilir bir ürün için ne yapılmalı? Masaüstü uygulamayı bitirmek birinci darboğaz mı? Kaliteli (rastgele olmayan) tarama ve proxy satışı için gerçek boşluk nedir?

## Doğrulanmış gerçekler

1. Resmi masaüstü Tauri kokpittir. `desktop/` ve kök `app/` yok; PySide kaldırılmış. Kaynak: `cockpit/README.md`, git ağacı.
2. Kokpit ajan yaratma, duraklatma, sert öldürme, olay replay, frame artifact ve Kontrolü Al ile canlı WayVNC yüzeyini gerçekten bağlar. `resume` / `start` / `destroy` UI'da yok. Terminal / Tarayıcı / Sistem / Notlar sekmeleri `data-panel` DOM'u olmadığı için dekoratiftir. `cockpit/app/src/main.ts`.
3. Kokpit `published_proxies` göstermez ve export etmez. Backend ajan state'inde alan vardır (`services/agentd/state.py:167,290-316`); UI kullanmaz.
4. Agentd araç kataloğu yazılıdır: `browse_public_source`, `inspect_owner_context`, `list_owner_ranges`, `masscan_liveness`, `expand_live_ip`, `validate_proxy`, `publish_proxy` (`services/agentd/ai_runtime.py`). `services/agentd/tools/` dizini boştur; araçlar runtime içinde tanımlıdır.
5. Canlı VDS canary'lerinde scanner bilinçli çalıştırılmaz: source gözlemi olur, geçerli discovery intent üretilmez, `MASSCAN_STARTED=false`, `PROXY_PUBLISHED=false`. `reports/iteration-17g-discovery-intent.txt`, `reports/iteration-17h2-bounded-discovery-intent.txt`.
6. Bu çalışma ağacında satılabilir doğrulanmış proxy kaydı yoktur. Envanter satırları placeholder `1.2.3.4`; canlı TR `/17` denemesi `adet=1 acik=1 dogrulanan=0` (`var/sonuclar/0-TR_v4_yok.txt`).
7. Klasik CLI hattı parçalıdır: `./pipeline tara` yalnız L4 yazar; `otonom.yurut` kuru komutta durur; birleşik L4+L7 yol `uzak_tara.yurut_canli` içindedir ve echo/egress zorunlu değildir. SQLite `endpoints`/`validations` şeması canlı tarama yoluna bağlı değildir.
8. Port politikası agentd'de `var/port-araliklari/yuksek.txt` (10000-10999, 30000-39999, 40000-49999). Klasik CLI varsayılanı 3128/8080/1080/80/8888. İki aile çatışır.
9. CIDR boyutu üst sınırı agentd'de yoktur; yalnız global IPv4. Geniş tarama politikası backlog'da engelli. Geçmişte `85.153.128.0/17` canlı taranmış.
10. Müşteri (alıcı) yüzeyi yoktur: dashboard, credential paketi, rotasyon, ödeme yok. Operatör kokpiti vardır.
11. `evaluation/evaluation-set/` boş (yalnız README). Shadow kapısı üretim yetkisi vermez.
12. Dokümanlar çelişir: `AGENTS.md` / `MIMARI.md` / `CALISTIR.md` 4 kutu CLI; `context/PROJECT.md` + `ARCHITECTURE.md` dinamik VDS agentd. `DURUM-KALAN.md` / `SABAH-RAPORU.md` (2026-09-04) "döngü akıyor" der; 17* raporları proxy yok der.
13. Git kökü proje klasörü değil `/home/void0x14/Belgeler`. Yanlış commit riski duruyor.

## Varsayımlar

- İlk para = açık (auth'suz) CONNECT/SOCKS + çalışan çıkış + kopyalanabilir liste. Alıcı mağazası, residential rotasyon ve faturalama 24 saat dışındadır.
- Operatör kaliteli ASN/prefix'i kendisi seçer; AI'nin myip.ms sezgisini taklit etmesi ilk satış için şart değildir.
- Agentd'deki intent hold unutulmuş bug değil, fail-close güvenlik kararıdır; satış yolunu keser.
- VDS hâlâ aynı host/key ile erişilebilir (bu turda yeniden yoklanmadı).

## Bilinmeyenler

- VDS üzerinde bu workspace dışındaki `validated-candidates.jsonl` veya ajan state'inde gerçek publish var mı.
- Echo servisinin production'da ayakta olup olmadığı.
- Operatörün yasal yetkili / müşteri sipariş spec'i (ülke, proto, hacim, SLA).
- Release `.deb` soğuk makinede repo/venv olmadan gerçekten açılıyor mu.

## Riskler

- Kokpit/AI tiyatrosunu bitirmek 24 saati yer; para üreten L4→L7→liste kapalı kalır.
- Echo'suz handshake "doğrulandı" yazabilir; satılabilir kanıt zayıf kalır.
- CIDR size gate yokken geniş tarama sağlayıcı şikâyeti üretir.
- Yüksek port bandı ile klasik proxy portları karışırsa yanlış varlık ailesi taranır.
- AUTH_REQUIRED elenir; "paid proxy" markası auth'lu envanter üretmez.
- Sahte sekmeler ve 15 sn poll operatöre "ürün bitti" hissi verir.

## Öneriler

1. 24 saatlik ürün tanımını daralt: operatör kaliteli hedefi seçer, sistem sınırlı tarar, L7+egress doğrular, kokpit listeler, dosya export edilir.
2. Masaüstünü "bitirme"yi birincil bottleneck sayma. Gözlem omurgası var. Para boşluğu: geçerli bounded execute + sonuç yüzeyi.
3. AI'nin source→intent döngüsünü ilk satış için dondur veya operatör niyetiyle atla.
4. Kokpite `published_proxies` + kopyala/export + resume ekle; dekoratif sekmeleri kapat.
5. CIDR size + rate hard gate olmadan canlı geniş tarama açma.
6. Shadow evaluation ve tam otonom keşif ilk satış sonrasına bırak.

## Kanıtlar / incelenen dosyalar

- `cockpit/app/src/main.ts`, `cockpit/src-tauri/src/lib.rs`, `cockpit/README.md`, `cockpit/install-desktop.sh`
- `services/agentd/{ai_runtime,state,protocol,worker}.py`
- `src/proxy_pipeline/{uzak_tara,otonom,cli/main,safety,feedback,validators/protocols}.py`
- `var/sonuclar/0-TR_v4_yok.txt`, `var/envanter/bulgu-2026090{4,5}.jsonl`, `var/port-araliklari/yuksek.txt`
- `reports/iteration-15b-real-human-use.txt`, `reports/iteration-17g-discovery-intent.txt`, `reports/iteration-17h2-bounded-discovery-intent.txt`
- `context/{PROJECT,ARCHITECTURE,DECISIONS}.md`, `backlog/BACKLOG.md`, `CALISTIR.md`, `MIMARI.md`
