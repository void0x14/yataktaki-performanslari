# 24 saat — ilk satılabilir proxy teslimi

## Hedef

Ajan operatörden CIDR almadan avlanır: av kaynağına bakar, dilim+tek ilk port seçer, küçük canlılık, canlıysa dikey genişleme, el sıkış+çıkış, kokpitte liste.

Temel sözleşme: `specs/hedef-ve-ilk-port.md`. Bu dosya teslim yüzeyini (kokpit liste, export, resume) bağlar.

24 saatin başarı tanımı: ajanın av döngüsü CIDR sormadan yürür; example.com / 1.1.1.1 yok; en az bir gerçek çıkışlı proxy **veya** dürüst sıfır + görünür neden/ilk-port izi. Placeholder IP sayılmaz.

## Hariç tutulan hedefler (Non-goals)

- Alıcı mağazası, ödeme, hesap, rotasyon API'si.
- Pet / tencere / video tiyatrosu cilası.
- IPv4 evreni veya `/8`–`/16` canlı tarama.
- Auth'lu (kullanıcı/şifreli) paid-proxy ürünü.
- Dondurulmuş tarihsel karar kümesi / shadow kapısı.
- Git kökünü ayırma (risk notu; bu sprint'in teslimi değil).
- Operatörden CIDR/ASN isteme.

## Mevcut durum

- Tauri kokpit VDS ajanını izler; `published_proxies` göstermez.
- Agentd araçları yazılı; scanner faz kilidiyle çalıştırılmaz.
- Klasik `uzak_tara` L4+L7 birleştirir ama echo zorunlu değil, SQLite'a yazmaz.
- Canlı kanıt: `PROXY_PUBLISHED=false`, TR `/17` denemesi `dogrulanan=0`.
- Port ailesi çatışması: yüksek bant vs 3128/8080/1080.

## İstenen durum

Ajan kokpitte yürür; operatör izler ve av defterine konuşur, hedef yazmaz.

1. Av kaynağı / sahiplik / kardeş ile başlar (`hedef-ve-ilk-port.md`).
2. Dilim en fazla /24, tek ilk port, gerekçe görünür; kapı dışı niyet reddedilir.
3. Kabulde masscan yalnız o manifestte çalışır; intent_ready uyumaz, execute eder.
4. Canlı IP’de dikey genişleme, sonra el sıkış + çıkış.
5. Başarılı kayıt kokpitte ve `var/teslim/proxies-YYYYMMDD.txt` içinde.
6. Resume var; sahte sekme yok.

## Gereksinimler

1. **Av niyeti ajanındır.** Operatör CIDR vermez. Karar `hedef-ve-ilk-port.md` sözleşmesine uyar.
2. **Boyut kapısı:** Canlı tarama en fazla `/24`. `/17` ve üzeri yasak.
3. **Hız kapısı:** Varsayılan rate ≤ 1000 pps; 100000+ yasak.
4. **İlk port tekdir.** Aile spreyi ilk atış değildir. Dikey genişleme ayrı adımdır.
5. **Execute:** Geçerli av niyeti `intent_ready` uyumasına düşmez; küçük canlılık çalışır.
6. **L7 + egress zorunlu.** Yalnız SYN/ACK satılabilir sayılmaz.
7. **Kokpit:** bakılan yer, neden, ilk port, canlı sonuç, yayın listesi, export.
8. **Resume UI'da vardır.** Dekoratif sekmeler kapanır.
9. **Gizli bilgi diske yazılmaz.**

## Kısıtlamalar / değişmezler (invariants)

- Tarama ve doğrulama VDS'de çalışır; yerel fallback tarama yok.
- Ajan masscan komutunu serbest uydurmaz; yalnız kapıdan geçmiş manifest.
- Parola/anahtar git'e ve log'a yazılmaz.
- L4 açık ≠ proxy.
- Geniş tarama politikası (backlog #2) bu sprintte açılmaz; daraltılır.

## Etkilenen alanlar

- `services/agentd/ai_runtime.py` — av fazı, ilk-port sözleşmesi, execute, dikey→doğrula sırası.
- `src/proxy_pipeline/discovery/otonom_bul.py` — 1.1.1.1 / AS13335 önyükleme kalkar.
- `cockpit/app/src/main.ts` — neden, ilk port, sonuç, resume.
- `var/teslim/` — müşteri dosyası.
- Testler: av-dışı URL reddi, ilk-portsuz intent reddi, faz sırası.

## Uyumluluk gereksinimleri

- Mevcut agentd JSONL komut adları korunur; yeni alanlar payload'a eklenir.
- Eski CLI `./pipeline tara --dry-run` kırılmaz.
- `publish_proxy` host/port/protocol/validation_ref eşleşme kuralı korunur.

## Riskler / uç durumlar

- AI av-dışı URL veya ilk-portsuz niyet üretir: sözleşme reddi, tarama yok.
- VDS down: kokpit belirsizliği gösterir, sahte liste yok.
- AUTH_REQUIRED: envantere girmez.
- Sıfır bulgu: dürüst boş + neden/ilk-port izi.

## Kabul kriterleri

1. Ajan CIDR sormadan av kaynağıyla başlar; example.com / 1.1.1.1 fail.
2. İlk portsuz veya /16 niyet görünür reddedilir.
3. Geçerli niyet execute edilir; masscan yalnız o dilim+ilk port.
4. Canlı sonrası dikey genişleme açılır; önce değil.
5. Çıkış geçmeyen uç yayınlanmaz.
6. Kayıt varsa kokpit + `var/teslim/proxies-*.txt`.
7. Resume çalışır. `pytest tests -q` yeşil.

## Doğrulama

- `.venv/bin/pytest tests -q`
- Birim: CIDR/rate/port kapısı, echo zorunluluğu, export biçimi.
- Entegrasyon: kokpit `published_proxies` render (VDS yoksa fixture).
- Canlı canary: CIDR sorulmadan av → ilk port → (0 veya N). N≥1 ise export.

## Uygulama notları

Sıra `hedef-ve-ilk-port.md`:

1. Faz kilidini av döngüsüne çevir (sahiplik/kardeş açık, rastgele URL kapalı).
2. İlk-port sözleşmesi + küçük execute.
3. Dikey → doğrula → yayın.
4. Kokpit neden/port/liste/resume.
5. 1.1.1.1 önyüklemeyi kaldır.
