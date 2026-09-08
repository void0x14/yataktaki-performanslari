# MASTER-PLAN: Otonom Proxy Keşif ve Doğrulama Hattı

## 0. Belge Statüsü ve Bağlayıcı İlkeler

- **Kaynak:** Düzeltilmiş `ALPHA-PLAN (2)`; çelişen eski taslakların yerine geçer.
- **Amaç:** Otonom hedef keşfi, AI tabanlı önceliklendirme, L4/L7 doğrulama, durum yönetimi ve operatör arayüzü için uygulanabilir ana planı tanımlamak.
- **Ölçek:** 10^7+ IPv4/IPv6 aday evreni; tek makine; SQLite.
- **Kod yapısı:** Bu belge mimari ve geliştirme planıdır; uygulama kodu içermez.
- **Temel optimizasyon hedefi:** En az ağ/zaman/model eforuyla en yüksek değerli hedefleri bulmak; karar kalitesini kullanıcının manuel süreçteki deneyim, sezgi ve isabet seviyesinin altına düşürmemek.
- **AI çalışma alanı:** AI yalnızca **Aşama 1 — hedef keşif, yatırım kararı ve önceliklendirme** içinde karar verir. Masscan, L7 handshake, teknik timeout/retry ve ağ rate-limit yürütmesi deterministiktir.
- **Aşama 1 ilkesi:** Sabit skor formülü, sabit örnekleme eşiği, sabit port önceliği ve hardcoded if/else karar ağacı kullanılmaz. Her Aşama 1 karar noktası Decision Service tarafından o anki bağlama göre üretilir.
- **Manifest sınırı:** AI'ın ürettiği hedef planı immutable Execution Manifest olarak kaydedilir; ağ katmanı yalnız bu manifesti çalıştırır.
- **Kullanıcı egemenliği:** Kullanıcı tek ajan, çoklu ajan, router, ensemble, insan destekli veya ileride eklenecek başka çalışma modları arasında çalışma zamanında geçiş yapabilir. Mimari herhangi bir modele, sağlayıcıya, agent framework'üne veya karar stiline kilitlenmez.

---

## 1. Sistem Hedefleri ve Başarı Tanımı

### 1.1 Birincil hedefler

1. ASN/CIDR/prefix adaylarını açık ve lisans koşulları uygun kaynaklardan otomatik keşfetmek.
2. Kullanıcının geçmişte myip.ms ve benzeri kaynaklarla yürüttüğü hedef seçimini daha geniş veri, daha güçlü hafıza ve ölçülebilir geri bildirimle aşmak.
3. AI'ın Aşama 1 içinde hangi hedefin, ne zaman, hangi port planıyla ve ne kadar kaynakla inceleneceğine bağlama özgü karar vermesini sağlamak.
4. Masscan stdout → Unix pipe/spool → asenkron L7 doğrulama hattını yüksek throughput ve kontrollü backpressure ile işletmek.
5. Canlı, rotasyonlu, çok çıkışlı, IPv6 veya residential olma ihtimali yüksek varlıkları düşük maliyetli kanıttan derin teste doğru ilerleyen bir süreçle bulmak.
6. 10^7+ aday evrenini SQLite'ın tek-yazıcı sınırını aşmadan yönetmek.
7. Her AI kararını, yürütme sonucunu ve state değişimini yeniden oynatılabilir biçimde denetlemek.

### 1.2 Kalite kapısı: manuel süreçten geri gitmeme

Otonom sistem doğrudan üretime geçirilmez. Kullanıcının geçmiş manuel kararlarından bir **değerlendirme kümesi** hazırlanır:

- İncelenen ASN/prefix adayları,
- kullanıcının seçtiği ve elediği hedefler,
- karar gerekçeleri ve sezgisel sinyaller,
- hangi portların neden denendiği,
- tarama/doğrulama sonucu,
- bulunan varlığın gerçek değeri,
- yanlış olumlu ve kaçırılmış fırsatlar.

Ajan mimarisi gölge modunda aynı adayları değerlendirir. Üretim yetkisi ancak şu koşullarda verilir:

- yüksek değerli hedef bulma precision/recall'u manuel baseline'ın altında değildir,
- bir doğrulanmış yüksek değerli hedef başına toplam efor baseline'dan kötü değildir,
- kritik hedef kaçırma oranı kabul edilen sınırı aşmaz,
- karar gerekçeleri kullanıcı tarafından yeterli bulunur,
- farklı çalışma modları aynı değerlendirme setinde karşılaştırılabilir sonuç üretir.

Bu kapı tek seferlik değildir; model, prompt, araç, veri kaynağı veya mod değişikliğinde replay değerlendirmesi yeniden çalıştırılır.

### 1.3 Ana KPI'lar

- Doğrulanmış değerli varlık / taranan IP.
- Doğrulanmış değerli varlık / L4 paketi.
- Doğrulanmış değerli varlık / L7 bağlantısı.
- İlk değerli bulguya kadar geçen süre.
- AI'ın seçtiği hedeflerin gerçekleşen değeri ve kalibrasyonu.
- AI karar regret'i: sonradan iyi olduğu görülen ancak ertelenen/elenen hedefler.
- Manuel baseline'a göre precision, recall, nDCG ve top-k hit rate.
- Kaynak başına marjinal bilgi kazancı ve gerçekleşen getiri.
- SQLite writer gecikmesi, spool yaşı ve disk büyümesi.
- Ajan çağrı başarı oranı, şema uyumu, gecikme ve toplam maliyet.

---

## 2. Kesin Mimari Kararlar

### ADR-001 — SQLite korunur; sıcak iş kuyruğu ve hacimli payload SQLite dışındadır

SQLite kontrol düzlemi ve kalıcı sonuç state'i olarak kullanılır. Her IP için yüksek frekanslı state UPDATE yapılmaz.

- **SQLite:** ASN/prefix envanteri, karar indeksleri, güncel durum, doğrulanmış endpoint'ler, toplulaştırılmış sonuçlar ve audit metadata.
- **Disk segment kuyruğu:** Üretilecek/taranacak büyük IP-port iş listeleri, cursor, lease ve checkpoint.
- **Append-only payload store:** Ham Masscan akışı, hacimli L4 negatifleri, AI prompt/response payload'ları ve arşiv olayları.
- **Tek DB Writer:** SQLite'a yazan tek süreç; sonuçları toplu ve idempotent transaction'larla işler.

Bu seçim 10^7+ aday evrenini temsil ederken 10^7 satırı sürekli güncelleme zorunluluğunu kaldırır.

### ADR-002 — Aday evreni prefix ve segment düzeyinde temsil edilir

- IPv4 büyük prefix'leri iş segmentlerine bölünür; bölüm boyutu karar mantığı değildir, depolama/yürütme ayrıntısıdır.
- IPv6 adres uzayı sıralı taranmaz; kaynaklardan, geçmiş gözlemlerden ve AI araştırmasından gelen somut IPv6 adayları/pattern'leri kullanılır.
- Tekil endpoint kaydı yalnız L4/L7 kanıtı veya AI'ın açık inceleme adayı olduğunda oluşturulur.

### ADR-003 — AI yalnız Aşama 1'in tüm semantik kararlarını verir

AI şu kararları verir:

- hangi veri kaynaklarının o turda araştırılacağı,
- hangi ASN/prefix/subnet adaylarının değerlendirileceği,
- adayların işlenme sırası,
- her adaya ayrılacak örnekleme/tarama planı,
- port adayları ve portların hedefe özgü sırası,
- kanıt geldikten sonra genişletme, tam tarama, erken terk veya erteleme,
- yeniden değerlendirme zamanı,
- hangi adayların yüksek-değer derin testine sevk edileceği,
- rotasyon/residential/IPv6 havuz ihtimalinin ön değerlendirmesi.

Aşama 1 içinde bu kararların yerine sabit sayı, sabit ağırlık veya sabit karar ağacı konulmaz.

### ADR-004 — L4/L7 yürütmesi AI'dan ayrıdır

AI'ın onaylı planı yürütme sözleşmesine dönüştükten sonra:

- Masscan süreç yönetimi,
- SYN/ACK ayrıştırma,
- HTTP CONNECT, SOCKS4/SOCKS5 handshake,
- teknik timeout ve retry,
- concurrency/backpressure,
- ağ ve kontrol endpoint'i rate-limit'i,
- veri doğrulama ve idempotency

deterministik mühendislik bileşenleridir. Bu katmanlar yeni hedef/port kararı üretmez; yalnız AI planını güvenli ve ölçülebilir biçimde yürütür.

### ADR-005 — Çalışma modu runtime'da seçilebilir ve plug-in tabanlıdır

Sistem tek bir “doğru” ajan mimarisi dayatmaz. Kullanıcı çalışma başlamadan veya güvenli checkpoint'te:

- tek ajan,
- yönetici + uzman subagent'lar,
- router ile görev/model yönlendirme,
- paralel ensemble + judge,
- tartışma/consensus,
- insan destekli karar,
- harici agent runtime/strateji plug-in'i

seçebilir. Mod değişikliği mevcut kararları bozmaz; yeni kararlar yeni `mode_version` ile üretilir.

### ADR-006 — Aynı karar bağlamında tekrarlanabilirlik varsayılandır; taze değerlendirme kullanıcı seçeneğidir

Varsayılan **reproducible mode**:

- canonical input snapshot,
- model ve sağlayıcı sürümü,
- prompt/tool sürümü,
- mode graph sürümü,
- mümkünse temperature=0 ve provider seed,
- tam tool sonucu hash'leri

ile karar kimliği oluşturur. Aynı karar kimliği tekrar gelirse ledger'daki committed karar kullanılır. Kullanıcı **fresh reevaluation mode** seçerse yeni karar üretilir ve önceki kararla farkı kaydedilir. Böylece non-determinism kontrol altında tutulur fakat kullanıcı deney/keşif özgürlüğünü kaybetmez.

### ADR-007 — Aşama 1'de AI yoksa karar verilmez

Birincil model/ajan kullanılamıyorsa yalnız kullanıcının yapılandırdığı başka AI route'u veya agent modu denenir. Hiçbiri çalışmıyorsa Aşama 1 `DECISION_BLOCKED` durumunda bekler; hardcoded skor veya gizli deterministik fallback devreye girmez. Daha önce committed planlar istenirse yürütülebilir, ancak yeni semantik hedef kararı üretilmez.

---

## 3. Uçtan Uca Aşamalar

### Aşama 0 — Kaynak hazırlığı

1. Kaynak katalogları ve gözlem kanıtları hazırlanır.
2. Discovery connector'ları veriyi provenance ile toplar.
3. Discovery connector'ları veriyi provenance ile toplar.
4. Feature/Context Builder yeni ve güncellenmiş aday bağlamlarını üretir.

### Aşama 1 — AI hedef keşfi ve önceliklendirme

1. Decision Service seçili çalışma modunu yükler.
2. Ajan, kaynak kataloğunu ve mevcut aday özetlerini inceler.
3. Gerekirse yeni kaynak sorguları için tipli araç çağrıları yapar.
4. ASN/prefix/subnet adaylarını ve kanıtlarını karşılaştırır.
5. Her karar noktasında somut action plan üretir.
6. Karar ve ham bağlam audit store'a yazılır.
7. Geçerli plan immutable Execution Manifest'e dönüştürülür.

### Aşama 2 — L4 keşfi

1. Segment Manager manifest'ten disk tabanlı işleri üretir.
2. Masscan Adapter yalnız manifestteki hedef/portları çalıştırır.
3. Stdout event stream parser'a ve gerektiğinde spool'a akar.
4. L4 pozitifleri anında L7 kuyruğuna; toplu sonuçlar DB Writer'a gider.

### Aşama 3 — L7 doğrulama

1. Validator Pool desteklenen protokolleri yürütme profilinde belirtilen sırada dener.
2. Kontrollü echo endpoint'i üzerinden gerçek proxy geçişi doğrulanır.
3. Sonuçlar reason code, latency ve exit gözlemiyle saklanır.
4. Teknik retry/timeout yalnız execution profile'a göre uygulanır.

### Aşama 4 — Geri bildirim ve yüksek-değer değerlendirmesi

1. Aggregator L4/L7 sonuçlarını ASN/prefix/port ve zaman penceresi bazında özetler.
2. Yeni evidence snapshot oluşur.
3. Aşama 1 Decision Service senkron çağrıyla genişletme, terk, erteleme, yeniden değerlendirme veya derin test kararını verir.
4. Derin teste sevk edilen endpoint'lerde deterministik test executor çalışır.
5. Gerçekleşen değer karar ledger'ına outcome olarak bağlanır.

---

## 4. Sistem Bileşenleri

2. **Source Catalog** — Veri kaynaklarının yetenek, lisans, kota, tazelik ve sağlık metadata'sı.
3. **Discovery Connectors** — RIR, BGP, PeeringDB, IRR/RPKI, passive DNS ve diğer kaynak adaptörleri.
4. **Normalizer & Entity Resolver** — ASN, organization, prefix ve ağ operatörü kimliklerini uzlaştırır.
5. **Context Builder** — AI için ham kayıt yerine kanıtlı, provenance içeren karar bağlamı üretir.
6. **Decision Service** — Her Aşama 1 kararını senkron işler; mode runtime, schema validation ve decision ledger'ı yönetir.
7. **Mode Registry / OmniRouter** — Kullanıcının seçtiği ajan grafiğini, modeli, route/fallback zincirini ve araç setini yükler.
8. **Execution Manifest Builder** — AI kararını immutable yürütme planına dönüştürür.
9. **Segment Queue Manager** — Büyük işleri dosya segmenti, lease ve cursor ile yönetir.
10. **Masscan Adapter** — L4 sürecini ve stdout akışını yönetir.
11. **L7 Validator Pool** — HTTP CONNECT, SOCKS4/SOCKS4a ve SOCKS5 doğrulaması.
12. **High-Value Test Executor** — Rotasyon, exit çeşitliliği ve kontrollü kapasite ölçümü.
13. **Result Aggregator** — Teknik sonuçları karar bağlamına uygun evidence snapshot'lara çevirir.
14. **DB Writer** — SQLite'a yazan tek süreç.
15. **Scheduler** — Yalnız committed AI planlarını ve teknik bakım işlerini zamanlar; hedef önceliği üretmez.
16. **Telemetry API / Operator UI** — Mod seçimi, karar açıklaması, veri kaynakları, tarama ve sistem sağlığı.
17. **Controlled Echo Service** — Proxy üzerinden görülen çıkış IP'sini nonce ile doğrular.

### 4.1 Bağımlılık sınırı

- Decision Service scanner komutu veya socket açamaz.
- Scanner/validator yeni hedef seçemez.
- Scheduler hedef skoru hesaplayamaz.
- Execution sınırı: yalnız AI kararından üretilen manifest yürütülür; hedef kalitesi burada değerlendirilmez.
- DB Writer karar üretmez; yalnız doğrulanmış event/state yazar.

---

## 5. Hedef Keşif Kaynakları

### 5.1 Çekirdek açık kaynaklar

- **RIR RDAP ve bulk delegation:** ARIN, RIPE NCC, APNIC, LACNIC, AFRINIC; tahsis, organization ve prefix sahipliği.
- **NRO delegated statistics:** RIR tahsislerinin birleşik ve verimli bulk görünümü.
- **BGPView:** ASN → announced prefix, upstream/downstream ve ASN metadata.
- **RIPEstat:** Routing status, announced prefixes, ASN komşuluğu ve geçmiş görünüm.
- **RouteViews ve RIPE RIS:** BGP table dump/update; origin değişimi, yeni duyuru ve görünürlük.
- **PeeringDB:** Network type, facility, exchange ve operatör beyanı.
- **IRR kaynakları/RADB:** Route/route6, maintainer ve organization ilişkileri; güven düzeyi provenance ile tutulur.
- **RPKI ROA verisi:** Prefix-origin yetkilendirme ve origin tutarlılığı.
- **CAIDA AS Rank / AS Organizations / AS Relationships:** Ağ rolü, organizasyon eşleme ve ilişki grafiği.
- **Team Cymru IP-to-ASN/DNS servisi veya bulk eşdeğeri:** Seed IP'den ASN/prefix genişletme.
- **Regional delegated ve geofeed kayıtları:** Coğrafi/operasyonel sinyal; tek başına residential kanıtı değildir.

### 5.2 Zenginleştirme ve aday üretme kaynakları

Lisansı ve kullanım şartı Source Catalog'da açıkça işaretlenmek şartıyla:

- Rapid7 Open Data/Sonar türevleri,
- public passive DNS veya reverse DNS dataset'leri,
- Certificate Transparency kayıtları,
- public internet measurement dataset'leri,
- GeoLite2 ASN/City gibi indirilebilir ASN/coğrafya verileri,
- operatörün geçmiş tarama sonuçları,
- manuel seed listeleri ve kullanıcının geçmiş myip.ms kararları,
- doğrulanmış endpoint'ten ASN, sibling prefix ve organization genişletme.

Ücretli/ticari kaynaklar zorunlu değildir; plug-in olarak eklenebilir. Kaynak lisansı, kullanım amacı ve yeniden dağıtım kısıtı connector etkinleştirilmeden önce görünür olmalıdır.

### 5.3 Kaynak seçimi ve ağırlıklandırma

Kaynaklara sabit global ağırlık veya sorgu sırası atanmaz. Her turda AI şu bağlamı görür:

- kaynağın kapsadığı veri türü,
- son başarılı güncelleme ve freshness,
- son kararlar üzerindeki bilgi kazancı,
- geçmiş doğruluk/çelişki kaydı,
- sorgu maliyeti ve rate-limit durumu,
- hedef sınıfı için ayırt edicilik,
- provenance completeness,
- lisans ve kullanılabilirlik.

AI hangi kaynakları hangi sırada çağıracağına ve ne zaman yeterli kanıt oluştuğuna karar verir. Source Catalog yalnız teknik erişim, kota ve lisans sınırlarını uygular.

### 5.4 Manuel sezginin modele aktarılması

Kullanıcının deneyimi salt “etiket” olarak değil, karar izi olarak toplanır:

- baktığı veri kaynakları,
- dikkat ettiği organization/ASN ilişkileri,
- şüpheli veya değerli bulduğu isim/pattern'ler,
- block size ve sibling prefix yorumu,
- port kümelenmesi,
- geçmiş başarı/başarısızlık bağlamı,
- seçmediği adaylar ve nedenleri,
- sonradan iyi/kötü çıkan kararlar.

Bu veriler few-shot örnek, retrieval memory, evaluator seti ve mode karşılaştırma benchmark'ı olarak kullanılır. Sistem kullanıcı düzeltmelerini outcome'a bağlayarak öğrenme havuzuna ekler.

---

## 6. Aşama 1 Decision Service

### 6.1 Karar noktaları

Decision Service aşağıdaki event'lerde senkron çağrılır:

- yeni ASN/organization/prefix bulundu,
- mevcut adayın kaynak verisi anlamlı biçimde değişti,
- bir önceki AI planının örnekleme sonucu tamamlandı,
- L4/L7 evidence snapshot oluştu,
- yüksek-değer ön değerlendirmesi gerekiyor,
- AI'ın belirlediği yeniden değerlendirme zamanı geldi,
- kullanıcı yeni bir seed, hedef sınıfı veya amaç verdi,
- kullanıcı mode/model/strateji değiştirdi.

### 6.2 Karar girdisi

Her istek canonical bir Decision Context taşır:

- decision type ve correlation id,
- ASN, organization, prefix/subnet ve sibling ilişkileri,
- tüm kaynak bulguları ve provenance,
- routing/IRR/RPKI/PeeringDB sinyalleri,
- önceki tarama ve doğrulama özetleri,
- port dağılımı ve geçmiş port kanıtları,
- maliyet/efor ve makine kapasitesi görünümü,
- geçmiş AI kararları ve gerçekleşen outcome,
- benzer hedeflerden retrieval edilen örnekler,
- kullanıcının aktif amacı ve tercihleri,
- mode/model/tool sürümleri,

### 6.3 Karar çıktısı

Çıktı şeması karar mantığını sınırlamaz; yürütülebilir sonucu standartlaştırır:

- `action`: araştır, örnekle, genişlet, tam tara, ertele, terk et, yeniden değerlendir, derin teste sevk et,
- hedef ASN/prefix/subnet listesi,
- hedefe özgü port adayları ve sırası,
- ayrılacak kaynak/tarama planı,
- örnek adres üretim yaklaşımı,
- stop/reassessment koşulunun doğal dil + yapılandırılmış ifadesi,
- yeniden değerlendirme zamanı veya event'i,
- beklenen değer ve confidence,
- kullanılan kanıtlar ve karşı kanıtlar,
- alternatifler ve neden elendiği,
- istenen ek tool/source çağrıları,
- kararın riskleri,
- model/mode metadata'sı.

Sabit threshold kütüphanesi karar üretmez. AI isterse o karara özel bir eşik veya örnekleme miktarı üretebilir; bu değer yalnız o decision record ve execution manifest için geçerlidir.

### 6.4 Senkronluk ve throughput

- Her **Aşama 1 semantik karar noktası** bir AI karar kaydına sahiptir.
- Bir API isteği bir aday veya aday batch'i taşıyabilir; batch çıktısında her aday için ayrı action ve decision item zorunludur.
- Masscan/L7 akışı her paket için LLM beklemez. Yalnız evidence batch tamamlandığında yeni Aşama 1 kararı beklenir.
- Decision Service eşzamanlı worker havuzu, provider quota awareness ve user-configured AI route'ları kullanır.
- Sağlayıcı limitine ulaşıldığında yeni Aşama 1 işleri bekler; yürürlükteki committed manifestler teknik katmanda devam edebilir.

### 6.5 Tutarlılık ve karar yaşam döngüsü


Yan durumlar:

- `INVALID_OUTPUT`: Şema/semantik bütünlük sağlanmadı; aynı veya başka AI route'uyla yeniden karar istenir.
- `DECISION_BLOCKED`: Kullanılabilir AI route'u yok.
- `DECISION_BLOCKED`: Kullanılabilir AI route'u yok.
- `SUPERSEDED`: Yeni mode/strategy ile yeni karar üretildi.
- `CANCELLED`: Operatör iptali.

Aynı input snapshot ve strategy/mode sürümünde varsayılan olarak committed karar tekrar kullanılır. Taze değerlendirme seçilirse yeni karar, önceki kararın parent id'siyle kaydedilir.

### 6.6 Karar kalitesi geri bildirimi

Her execution manifest tamamlandığında şu outcome'lar decision item'a bağlanır:

- taranan IP/port miktarı,
- süre ve kaynak tüketimi,
- L4 pozitifleri,
- L7 doğrulanan endpoint'ler,
- rotasyon/exit çeşitliliği,
- yüksek değer sınıfı,
- false positive/false negative incelemesi,
- operatör puanı ve düzeltmesi,
- beklenen değer ile gerçekleşen değer farkı.

Bu veri sonraki karar bağlamına ve mode/model leaderboard'una girer. Sabit formül üretmez; AI'a geçmiş sonuç ve örnek sağlar.

---

## 7. Modüler Ajan ve OmniRouter Mimarisi

### 7.1 Zorunlu çalışma modları

#### Mod A — Tek Ajan

Tek model tüm keşif araçlarını kullanır, adayları değerlendirir ve final kararları üretir. Düşük orkestrasyon maliyeti ve kolay debug sağlar.

#### Mod B — Yönetici + Uzman Subagent'lar

Yönetici; source research, network intelligence, historical pattern, high-value assessment ve critic rollerine görev dağıtır. Final action yönetici tarafından birleştirilir.

#### Mod C — Router

Karar tipi, context boyutu, araç ihtiyacı veya kullanıcı tercihi üzerinden farklı model/ajanlara yönlendirme yapar. Route kuralları kullanıcı tarafından tanımlanır ve sürümlenir.

#### Mod D — Ensemble + Judge

Birden fazla ajan bağımsız aday sıralaması üretir; judge ajan kanıtları karşılaştırıp final action verir. Yüksek kalite gereken kararlar için uygundur.

#### Mod E — Debate/Consensus

Ajanlar lehte/aleyhte argüman üretir; finalizer belirsizliği ve karşı kanıtı değerlendirir.

#### Mod F — Human-in-the-loop

AI önerir, kullanıcı değiştirir/onaylar. Kullanıcı düzeltmesi eğitim/retrieval verisine dönüşür.

### 7.2 Plug-in sözleşmeleri

Aşağıdaki bileşenler registry üzerinden eklenip çıkarılabilir:

- model provider,
- model route,
- agent runtime/framework,
- agent role,
- tool/connector,
- prompt pack,
- retrieval/memory backend,
- decision mode graph,
- output validator,
- evaluator,
- high-value classifier/enricher.

Her plug-in capability manifest, config schema, health check, version, permission set ve telemetry hook sunar. Core servis plug-in'in iç uygulamasını bilmez.

### 7.3 Kullanıcı kontrol yüzeyi

UI/CLI üzerinden kullanıcı:

- aktif modu seçer,
- her role model atar,
- route ve fallback sırasını belirler,
- araçları açar/kapatır,
- prompt/memory paketini seçer,
- fresh/reproducible karar modunu belirler,
- shadow/canary/production durumunu seçer,
- karar için insan onayı gerekip gerekmediğini ayarlar,
- harici bir agent runtime'ı kaydeder,
- modu güvenli checkpoint'te değiştirir.

### 7.4 Mod değişikliği

- Devam eden inference eski `mode_version` ile tamamlanır veya kullanıcı tarafından iptal edilir.
- Committed Execution Manifest immutable kalır.
- Yeni kararlar yeni mode version kullanır.
- Aynı context, iki modla shadow çalıştırılıp sonuçları karşılaştırılabilir.
- Rollback önceki mode manifestini yeniden etkinleştirir; veri migration gerektirmez.

### 7.5 Model seçme kriterleri

Belirli model önerilmez. Her rol için ölçülecek kriterler:

- yapılandırılmış çıktı ve tool-call güvenilirliği,
- çok adımlı araştırma/araç kullanımı,
- target ranking kalitesi,
- kullanıcı değerlendirme kümesi başarısı,
- uzun bağlam ve retrieval kullanımı,
- non-determinism ve tekrar üretilebilirlik,
- latency, throughput ve provider eşzamanlılık sınırı,
- karar başı ve bulunan değerli varlık başı maliyet,
- hata sonrası toparlanma ve fallback uyumu,
- self-hosted/hosted, gizlilik ve veri saklama seçenekleri.

Model leaderboard'u tek ağırlıklı sabit skor yerine bu ölçümleri ayrı eksenlerde gösterir; hangi trade-off'un seçileceğine kullanıcı karar verir.

---

## 8. AI Tabanlı Önceliklendirme ve Anti-Waste

### 8.1 Hardcoded olmayan kaynak tahsisi

Sistem aşağıdaki değerleri global sabit olarak tanımlamaz:

- bir prefix'ten kaç IP örnekleneceği,
- kaç pozitifin genişletme için yeterli olduğu,
- exploration/exploitation oranı,
- prefix/ASN özelliklerinin yüzdesel ağırlığı,
- cold/warm/hot karar eşiği,
- portların evrensel öncelik sırası,
- bir bloğun sabit yeniden deneme süresi.

AI her karar bağlamında örnekleme planı, port planı, stop koşulu ve reevaluation koşulu üretir.

### 8.2 Port keşfi

3128, 1080 veya 30000–40000 yalnız geçmiş gözlem veya kaynaklardan gelen aday sinyallerdir; evrensel Squid/Proxy varsayımı değildir. Port aday havuzu şu kanıtlardan oluşabilir:

- hedef/sibling prefix geçmiş sonuçları,
- aynı organization/ASN'deki doğrulanmış endpoint'ler,
- kullanıcı geçmişi,
- passive/active measurement kaynakları,
- hizmet banner/metadata kanıtı,
- modelin araçlarla ulaştığı güncel araştırma,
- daha önce başarısız veya başarılı port kümeleri.

AI hedefe özgü port listesini ve sırasını üretir. Masscan yalnız bu listeyi uygular.

### 8.3 Mikro-örnekleme

“Mikro-örnekleme” önceden belirlenmiş sabit kademeli bir protokol değil, AI action türüdür. Karar çıktısı:

- kaç adres,
- hangi adres seçme yaklaşımı,
- hangi portlar,
- hangi kanıtta genişletileceği,
- hangi kanıtta bırakılacağı,
- ne zaman yeniden bakılacağı

bilgilerini o hedef için taşır. Sonuç geldiğinde karar hardcoded eşiğe göre değil, yeni Decision Service çağrısıyla verilir.

### 8.4 Early drop ve tekrar değerlendirme

`DROP`, kalıcı silme değildir. AI kararında:

- kanıt gerekçesi,
- confidence,
- tekrar değerlendirme zamanı veya tetikleyici event,
- hangi yeni kanıtın kararı değiştireceği

bulunur. Routing değişimi, yeni sibling başarısı, yeni seed, port pattern'i veya kullanıcı isteği adayın yeniden değerlendirilmesini tetikleyebilir.

### 8.5 Yüksek değer ön elemesi

AI, doğrulama öncesinde şu sinyallerden yüksek-değer ihtimali çıkarır:

- aynı organization/ASN'de çok sayıda ilgili prefix,
- geçmişte benzer port/endpoint kümelenmesi,
- exit ve target ASN ilişkisi,
- IPv6 address/prefix sinyalleri,
- residential ISP/hosting/eyeball ağ göstergeleri,
- rotasyon veya gateway mimarisine işaret eden geçmiş kanıt,
- kullanıcının benzer vakalardaki seçimleri.

Bu yalnız derin teste sevk kararıdır; gerçek rotasyon/residential sınıfı L7 ve echo kanıtıyla belirlenir.

---

## 9. State ve Feedback Loop

### 9.1 Aday state'leri

`DISCOVERED → CONTEXT_READY → DECISION_PENDING → SELECTED/DEFERRED/DROPPED`

Seçilen aday:

`SELECTED → MANIFEST_READY → SAMPLING/SCANNING → EVIDENCE_READY → REASSESSMENT_PENDING`

AI reassessment sonucu:

- `EXPAND_SELECTED`
- `FULL_SCAN_SELECTED`
- `DEEP_TEST_SELECTED`
- `MONITOR_SELECTED`
- `DEFERRED`
- `DROPPED`

Bu state adları action tipleridir; geçişin semantik sebebi her defasında AI decision id ile bağlıdır.

### 9.2 Teknik yürütme state'leri

- Segment: `CREATED → READY → LEASED → PARTIAL/COMPLETED → ARCHIVED/FAILED`.
- Endpoint: `L4_OPEN → L7_PENDING → VALIDATED/PROTOCOL_MISMATCH/AUTH_REQUIRED/TIMEOUT/UNREACHABLE`.
- Aktif endpoint: `ACTIVE → DEGRADED → INACTIVE`.
- Decision: Bölüm 6.5'teki yaşam döngüsü.

Teknik retry state'leri AI kararı değildir; ağ işinin güvenilir yürütülmesidir. Ancak teknik denemeler tükendiğinde oluşan evidence, Aşama 1'de yeni AI kararını tetikler.

### 9.3 Event → DB → AI akışı

1. Connector veya executor append-only event üretir.
2. Aggregator idempotency denetimi ve toplulaştırma yapar.
3. DB Writer current state ve counter'ları batch transaction ile günceller.
4. Karar için yeterli yeni event seti tamamlandığında `decision.requested` üretilir.
5. Context Builder snapshot oluşturur ve hash'ler.
6. Decision Service senkron çıkarım yapar.
7. Decision committed olur; Execution Manifest oluşturulur.
8. Manifest yürütülür.
9. Outcome decision kaydına bağlanır ve retrieval/evaluation havuzuna girer.

### 9.4 Teknik retry/backoff

Teknik transport retry'ları konfigüre edilebilir execution profile'dır; hedef değeri hakkında karar vermez. Profil en az şunları tanımlar:

- retry edilebilir hata sınıfları,
- maksimum teknik deneme,
- connect/handshake/total timeout,
- jitter/backoff yöntemi,
- concurrency sınırı,
- circuit breaker koşulları.

Varsayılan değerler load/pilot testinde ölçülür ve kullanıcı tarafından değiştirilir. Bir hedefin tekrar yatırım alıp almayacağı ise teknik retry profilinden bağımsız olarak AI kararıdır.

---

## 10. L4/L7 Yürütme Tasarımı

### 10.1 Masscan akışı

`Execution Manifest → Segment Queue → Masscan stdout → Parser → bounded pipe/spool → L7 Validator Pool → Result Spool → DB Writer`

Masscan Adapter:

- manifest hedefi ve kimliğini doğrular,
- yalnız manifestteki CIDR/portları çalıştırır,
- her event'e run/segment/decision kimliği ekler,
- malformed satırları dead-letter'a yollar,
- backpressure durumunda hız düşürür veya spool'a döker,
- checkpoint'ten idempotent devam eder.

### 10.2 Pipe event sözleşmesi

- schema version,
- event id ve timestamp,
- decision id, manifest id, scan run id, segment id,
- target IP, port, ASN/prefix referansı,
- L4 sonucu ve scanner metadata,
- idempotency key,
- correlation/causation id.

### 10.3 L7 protokolleri

İlk protokoller:

- HTTP CONNECT,
- SOCKS5,
- SOCKS4/SOCKS4a.

Hepsi modüler validator olarak desteklenir. Protokol yürütme sırası global hardcode değildir; kullanıcı execution profile'ı veya Aşama 1'in hedefe özgü port/protocol intent'iyle belirlenebilir. Handshake sonucu ilgili protokol spesifikasyonuna göre deterministik değerlendirilir.

### 10.4 Concurrency ve timeout

Tek evrensel concurrency/timeout sayısı dokümana gömülmez. Startup calibration ve pilot ölçümleriyle şu sınırlara göre execution profile üretilir:

- CPU ve event-loop lag,
- file descriptor limiti,
- yerel ephemeral port kullanımı,
- ağ bant genişliği ve packet loss,
- target/ASN başına hata oranı,
- echo endpoint kapasitesi,
- result spool ve DB writer gecikmesi.

Runtime controller teknik sağlığa göre concurrency'yi artırıp azaltabilir; bu target-value kararı değildir. Tüm alt/üst sınırlar kullanıcı konfigürasyonunda görünürdür.

### 10.5 Rate-limit ve ban riski

- Global, kaynak, hedef ASN, prefix ve endpoint başına ayrı token bucket.
- Sağlayıcı/API `Retry-After` bilgisine uyum.
- Abuse/opt-out kaydında anında pause ve denylist.
- Hata/ICMP/rate-limit artışında circuit breaker.
- Üçüncü taraf kontrol sitelerine kontrolsüz trafik gönderilmez.
- Kaynak IP rotasyonu limit aşma yöntemi olarak kullanılmaz.
- Tarama hız limitleri kullanıcıya ve yetkilendirme koşullarına göre konfigüre edilir.

### 10.6 L7 başarı kriteri

Endpoint yalnız:

- handshake geçerliyse,
- kontrollü hedefe trafik proxy üzerinden ulaştıysa,
- nonce/request id eşleşiyorsa,
- gözlenen exit IP doğrulandıysa,
- doğrudan bağlantıyla karışmadıysa,
- latency/error metadata yazıldıysa

`VALIDATED` olur.

---

## 11. Yüksek Değerli Varlık Doğrulaması

### 11.1 AI ve executor ayrımı

- AI, hangi adayın derin teste değer olduğuna ve test amacına karar verir.
- Test Executor, seçilmiş test profilini deterministik yürütür.
- Sonuç sınıflandırması kanıta dayanır; AI'ın ön tahmini nihai gerçek olarak kabul edilmez.

### 11.2 Artımlı test profilleri

Test profilleri kullanıcı tarafından düzenlenebilir ve versiyonlanır:

1. **Minimum kanıt:** Birden fazla bağımsız bağlantıda exit IP gözlemi.
2. **Rotasyon kanıtı:** Zaman aralıklı tekrarlar ve benzersiz exit dağılımı.
3. **Coğrafi/ASN çeşitlilik:** Kontrollü echo bölgeleri arasında tutarlılık.
4. **IPv6 davranışı:** IPv6 target/exit ve dual-stack kanıtı.
5. **Kapasite:** Yalnız açık operatör onayıyla kontrollü hedeflere kademeli concurrency.

Bağlantı sayısı, pencere ve bölge sayısı sabit sistem varsayımı değildir; profile ve AI'ın test amacına göre manifestte belirtilir.

### 11.3 Kanıta dayalı sınıflar

- `STATIC_EGRESS`
- `POSSIBLE_ROTATION`
- `CONFIRMED_ROTATION`
- `MULTI_EGRESS`
- `IPV6_EGRESS`
- `RESIDENTIAL_LIKELY`
- `DATACENTER_LIKELY`
- `CAPACITY_VALIDATED`
- `INSUFFICIENT_EVIDENCE`

Her sınıf; evidence listesi, örnek büyüklüğü, zaman aralığı, exit çeşitliliği, confidence ve classifier version ile saklanır. Residential/datacenter etiketi olasılıksaldır.

### 11.4 Echo altyapısı

- En az iki bağımsız yönetilen bölge/sağlayıcı hedef mimarisidir.
- TLS, nonce, timestamp ve request id kullanılır.
- Bölge sağlık/kota telemetrisi tutulur.
- Üçüncü taraf “what is my IP” servisleri üretim bağımlılığı değildir.
- Echo arızasında temel protokol doğrulaması ve derin test ayrı state'lerde raporlanır.

---

## 12. SQLite ve Kalıcı Veri Modeli

### 12.1 SQLite işletim modeli

- WAL modu.
- Tek DB Writer.
- Kısa batch transaction'lar.
- Read-only UI/analytics bağlantıları.
- Düzenli WAL checkpoint.
- Günlük quick check, periyodik integrity check.
- Append-only event/payload arşivleme.
- Online snapshot ve düzenli restore testi.

### 12.2 Kimlik ve veri gösterimi

- Dahili 64-bit integer id.
- Dış korelasyon için UUIDv7.
- UTC epoch millisecond.
- IP adresi kanonik 16-byte binary.
- CIDR için network binary + prefix length.
- Tüm şema, event, decision, mode, prompt ve manifest sürümleri açıkça saklanır.

### 12.3 Tablolar

#### `schema_migrations`

Migration version, checksum, applied_at.


#### `source_catalog`

Kaynak tipi, connector, lisans/kullanım notu, capability, quota, freshness, health, enabled state.

#### `source_fetches`

Kaynak sorgusu, request fingerprint, cache metadata, response hash, status, süre ve hata.

#### `organizations`

Kanonik organization, alias'lar, ülke, ağ rolü ve entity-resolution confidence.

#### `asns`

ASN, organization ilişkisi, routing/PeeringDB/CAIDA özetleri, first/last seen ve aggregate outcome.

#### `prefixes`

Network, prefix length, IP version, origin ASN, advertised state, first/last seen.

#### `prefix_sources`

Her prefix bulgusunun source record id, observed_at, payload hash, confidence ve conflict bilgisi.

#### `candidate_contexts`

ASN/prefix/subnet karar bağlamı snapshot'ı, feature/evidence özeti, provenance listesi, context hash ve created_at.

#### `agent_modes`

Mode adı/tipi, graph/config payload ref, version, enabled, created_by ve activation state.

#### `model_routes`

Role/capability, provider/model, fallback order, user config, health ve version.

#### `strategy_versions`

Prompt pack, tool set, retrieval policy, user objective ve mode version referansları. Sabit skor ağırlığı tablosu değildir.

#### `agent_decisions`

Her Aşama 1 karar noktası için bir satır:

- decision id/type/state,
- candidate/entity referansı,
- context snapshot id/hash,
- prompt payload ref/hash,
- raw response payload ref/hash,
- parsed action,
- target/port/resource plan özeti,
- evidence/reasoning özeti,
- confidence,
- model/provider/mode/prompt/tool version,
- parent/superseded decision,
- schema validation ve karar durumu,
- inference timing/token/cost,
- created/committed/executed timestamps.

Ham prompt ve response sıkıştırılmış append-only payload store'da tutulur; SQLite satırı bunların immutable path/object id ve checksum'unu taşır. Böylece her karar denetlenir fakat DB dosyası gereksiz BLOB yükü taşımaz.

#### `decision_items`

Batch inference kullanıldığında her aday/action için ayrı item; target, action, order, resource allocation, stop/reassessment expression ve status.

#### `execution_manifests`

Committed kararın immutable yürütme planı, target/port/protocol intent, segment planı, technical profile ve status.

#### `scan_runs`

Manifest referansı, başlangıç/bitiş, scanner profile, state, counters ve stop reason.

#### `scan_segments`

Disk segment path/id, checksum, item count, cursor, lease, retry ve state.

#### `endpoints`

IP, port, current state, first/last seen, last validation, protocol summary ve active confidence.

#### `validations`

Endpoint/protocol, result/reason, latency, echo ref, attempt, manifest/decision/run id ve timestamp.

#### `exit_observations`

Endpoint, exit IP/ASN/ülke, IP version, echo region, request hash ve observed_at.

#### `asset_assessments`

Kanıta dayalı sınıf, confidence, sample/window/diversity, evidence refs, classifier/profile version.

#### `state_events`

Entity, from/to state, reason, decision/manifest/correlation id, actor ve timestamp.

#### `decision_outcomes`

Decision/item referansı, gerçekleşen L4/L7/yüksek-değer sonucu, maliyet, süre, regret/evaluator ve user feedback.

#### `operator_feedback`

Kullanıcı onayı/düzeltmesi, gerekçe, önce/sonra action ve training/retrieval eligibility.

#### `experiments`

Mode/model/prompt karşılaştırması, cohort, objective, evaluation set ve sonuç. Aşama 1'e hardcoded karar kuralı dayatmaz.

#### `rate_limit_buckets`

Teknik global/source/ASN/prefix/endpoint/echo bucket state checkpoint'i.

#### `alerts`

Severity, source, dedupe key, first/last seen, count, status ve acknowledgement.

### 12.4 Temel indeksler

- `prefix_sources(prefix_id, observed_at)`
- `candidate_contexts(entity_type, entity_id, created_at)`
- `agent_decisions(state, decision_type, created_at)`
- `agent_decisions(context_hash, strategy_version, mode_version)`
- `decision_items(decision_id, status, order_index)`
- `execution_manifests(status, created_at)`
- `scan_segments(state, lease_until)`
- `endpoints(ip_binary, port)` benzersiz
- `validations(endpoint_id, created_at)`
- `state_events(entity_type, entity_id, occurred_at)`
- `decision_outcomes(decision_id, created_at)`

### 12.5 Saklama ve arşiv

- Güncel entity/state: SQLite'ta.
- Decision metadata ve outcome: uzun süreli.
- Ham prompt/response: kullanıcı politikasına göre sıkıştırılmış payload store; hash SQLite'ta kalıcı.
- Tekil L4 negatifleri: toplulaştırma sonrası kısa süreli.
- Validation ayrıntıları: sıcak dönemden sonra zaman bölümlü arşiv.
- Audit kayıtları: silinmez veya yasal saklama politikasına göre yönetilir.
- Silme/compaction yalnız checksum doğrulaması ve geri alınabilir bakım planıyla yapılır.

### 12.6 Yedekleme

- Saatlik online SQLite snapshot.
- Günlük DB + aktif queue/spool + payload manifest yedeği.
- Checksum ve restore doğrulaması.
- Düzenli restore tatbikatı.
- RPO/RTO gerçek makine ve disk ölçümünden sonra kullanıcı tarafından onaylanır.

---

## 13. Disk Tabanlı Kuyruk ve Backpressure

### 13.1 Segment modeli

Her segment:

- segment id,
- execution manifest id,
- schema version,
- target/port item count,
- checksum,
- cursor,
- lease owner/until,
- created/completed timestamp

taşır.

Yaşam döngüsü: `CREATED → READY → LEASED → PARTIAL/COMPLETED → ARCHIVED`. Lease kaybında cursor'dan idempotent devam edilir.

### 13.2 Spool'lar

- Masscan raw/output spool,
- normalized L4 event spool,
- L7 result spool,
- dead-letter spool,
- AI prompt/response payload store,
- archive staging.

Her spool ayrı disk kotası ve sağlık metriğine sahiptir.

### 13.3 Backpressure

Sabit yüzdeler yerine kullanıcı tarafından tanımlanan ve makine benchmark'ından üretilen teknik watermark profili kullanılır. Watermark'a göre:

- L4 üretim hızı azaltılır,
- yeni segment lease'i durdurulur,
- yalnız inflight işler tamamlanır,
- kritik dolulukta ağ çıkışı güvenli biçimde pause edilir.

Bu teknik koruma hedef önceliği üretmez; AI'ın seçtiği işlerin yürütme hızını düzenler.

---

## 14. API, GUI ve Telemetri

### 14.1 Operatör ekranları

1. **Mission Control:** Sistem sağlığı, throughput, maliyet, queue/spool ve aktif run'lar.
2. **Decision Cockpit:** Her AI kararı, kaynak bağlamı, kanıt/karşı kanıt, confidence, action ve outcome.
3. **Mode Studio:** Tek ajan/çoklu ajan/router/ensemble seçimi, graph ve model route ayarı.
4. **Source Intelligence:** Connector sağlık, freshness, lisans, kota, bilgi kazancı ve çelişkiler.
5. **Candidate Portfolio:** ASN/prefix/subnet adayları, son context, karar, reevaluation ve gerçekleşen değer.
6. **Endpoint Inventory:** Protokol, exit, IPv4/IPv6, rotasyon, sınıf ve tazelik.
7. **Comparison Lab:** Mode/model/prompt shadow ve replay karşılaştırması.
8. **Operator Feedback:** Kararı onaylama, düzeltme, açıklama ve değerlendirme kümesine ekleme.
9. **Audit Explorer:** Prompt/response hash, tool trace, state transition.
10. **Safety & Execution:** rate-limit ve kill switch.

### 14.2 Ortak event zarfı

- event id/type/schema version,
- occurred_at/producer,
- entity type/id,
- decision/decision item/manifest/run/segment id,
- correlation/causation id,
- mode/strategy version,
- payload ref/summary,
- severity.

Temel event'ler:

- `source.fetched`, `candidate.discovered`, `context.ready`,
- `decision.requested`, `decision.completed`, `decision.invalid`,
- `manifest.committed`, `scan.started`, `l4.open`, `l7.validated`, `l7.failed`,
- `evidence.ready`, `decision.outcome_attached`, `asset.assessed`,
- `mode.changed`, `route.failed`, `rate_limit.tripped`, `scan.paused`, `alert.raised`.

### 14.3 Metrikler

#### AI/karar

- decision throughput, queue age ve p50/p95 latency,
- schema/tool-call başarı oranı,
- provider/model hata ve fallback oranı,
- context/token/cost,
- mode bazlı top-k hit rate, precision/recall, nDCG ve regret,
- confidence calibration,
- fresh reevaluation disagreement rate,
- manuel override ve düzeltme oranı.

#### Tarama/doğrulama

- L4 probes/s ve hit rate,
- L7 attempts/s ve protokol sonucu,
- target/ASN/prefix başına gerçekleşen getiri,
- doğrulanmış yüksek değerli varlık,
- timeout/retry/circuit breaker,
- echo sağlık ve kota.

#### Sistem

- DB writer lag, transaction süresi, WAL size,
- segment queue depth/age,
- spool kullanımı,
- disk/CPU/RAM/FD/event-loop,
- archive/backup yaşı ve son restore sonucu.

### 14.4 Kritik alarmlar

- manifest dışı hedef üretimi veya yürütme girişimi,
- payload/hash/audit bütünlüğü hatası,
- tüm AI route'larının kullanılamaz olması,
- decision queue'nun kullanıcı SLO'sunu aşması,
- DB/spool/disk kritik watermark,
- echo doğrulama bütünlüğü hatası,
- beklenmeyen tarama trafiği artışı,
- karar kalitesinin manuel baseline altına düşmesi,
- aktif mode'da drift veya yüksek disagreement.

---

## 15. Teknoloji Seçimleri

### 15.1 Ana teknoloji yığını

- **Python 3.12+:** Orkestrasyon, connector, Decision Service, queue, L7 ve API.
- **asyncio + AnyIO/httpx:** Asenkron I/O ve provider/API çağrıları.
- **Pydantic:** Decision context/output, event, config ve plug-in şemaları.
- **SQLite 3 WAL:** Kontrol düzlemi ve current state.
- **SQLAlchemy Core + Alembic:** Açık veri erişimi ve migration.
- **Masscan:** L4 keşfi; yalnız adapter arkasında.
- **FastAPI:** Operatör/entegrasyon API'si.
- **HTMX + server-rendered templates:** İlk UI; ayrı SPA zorunlu değil.
- **OpenTelemetry + Prometheus + Grafana:** Trace, metric ve dashboard.
- **Typer:** Operatör CLI.
- **systemd:** Tek makine servis yönetimi ve kaynak sınırları.
- **Zstandard sıkıştırılmış append-only dosyalar:** Segment, payload ve arşiv.

### 15.2 Agent framework kararı

Core, framework bağımsız internal interface kullanır. LangGraph, PydanticAI, AutoGen, CrewAI, özel runtime veya ileride başka bir framework adapter olarak eklenebilir. Framework seçimi kullanıcıya aittir; veri modeli ve Decision Service sözleşmesi değişmez.

### 15.3 Neden ilk sürümde harici broker yok

Tek makine ve disk tabanlı durable segment gereksinimi için ilk sürümde Redis/RabbitMQ zorunlu değildir. Harici broker ihtiyacı şu ölçümlerden sonra yeniden değerlendirilir:

- tek makinede yeterli worker koordinasyonu sağlanamaması,
- spool/lease recovery'nin operasyonel olarak yetersiz kalması,
- birden fazla scanner host gereksinimi,
- DB Writer ve queue gecikmesinin kabul edilen SLO'yu kalıcı aşması.

### 15.4 Config ve secret

- Kullanıcı tercihleri ve mode manifestleri sürümlü TOML/YAML/JSON.
- API anahtarları config dosyasına yazılmaz.
- Provider/model/route değişiklikleri audit edilir.
- Kullanıcı tercihleri ve çalışma modları sürümlü, audit edilebilir yapılandırmalardır.
- Plug-in permission'ları least privilege uygulanır.

---

## 16. Klasör Yapısı

```text
project-root/
├── pyproject.toml
├── README.md
├── MASTER-PLAN.md
├── config/
│   ├── defaults.toml
│   ├── execution-profiles/
│   ├── modes/
│   ├── model-routes/
│   ├── policies/
│   └── schemas/
├── migrations/
├── src/
│   └── proxy_pipeline/
│       ├── domain/
│       ├── sources/
│       │   ├── registry/
│       │   └── connectors/
│       ├── discovery/
│       ├── context/
│       ├── decision/
│       ├── modes/
│       ├── routing/
│       ├── agents/
│       ├── memory/
│       ├── plugins/
│       ├── manifests/
│       ├── queue/
│       ├── scanners/
│       ├── validators/
│       ├── assessment/
│       ├── persistence/
│       ├── telemetry/
│       ├── api/
│       ├── ui/
│       └── cli/
├── services/
│   └── echo/
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── contract/
│   ├── replay/
│   ├── shadow/
│   ├── load/
│   ├── failure/
│   └── fixtures/
├── evaluation/
│   ├── evaluation-set/
│   ├── mode-benchmarks/
│   └── reports/
├── ops/
│   ├── systemd/
│   ├── monitoring/
│   ├── backup/
│   └── runbooks/
├── var/
│   ├── db/
│   ├── queue/
│   ├── spool/
│   ├── payloads/
│   ├── archive/
│   ├── cache/
│   └── logs/
└── docs/
    ├── adr/
    ├── protocols/
    ├── decision-contracts/
    ├── data-model/
    └── operations/
```

Bağımlılık yönü: domain/contracts ← application services ← adapters/plugins. Hiçbir model veya agent framework core domain'e doğrudan bağımlılık oluşturmaz.

---

## 17. Güvenlik ve Yetkilendirme

1. AI kararı immutable Execution Manifest'e dönüştürülmeden yürütmeye verilemez.
3. Scanner manifest dışı hedef kabul etmez.
4. Private, loopback, link-local, multicast, reserved ve denylist adresler policy ile dışlanır.
5. Prompt injection riski taşıyan kaynak metni untrusted content olarak etiketlenir; araç yetkisi genişletemez.
6. Agent tool'ları allowlist ve capability bazlıdır; shell, ham SQL veya sınırsız URL erişimi verilmez.
7. UI/API özel yönetim ağına bağlanır; authentication ve RBAC uygulanır.
8. Roller: viewer, operator, mode-editor, approver, admin.
9. Prompt/response payload'ları hassas veri politikasına göre şifrelenir veya redakte edilir.
10. Route, mode, prompt, model ve rate-limit değişiklikleri audit edilir.
11. Kill switch yeni decision execution'ı, Masscan ve L7 çıkışını durdurur; state flush edilir.
12. Opt-out/abuse kaydı gecikmeden denylist'e girer.

---

## 18. Test ve Değerlendirme Stratejisi

### 18.1 Teknik testler

- Unit: CIDR/IP, manifest, segment, cursor, idempotency, state transition.
- Property-based: canonical context/hash ve event/manifest şemaları.
- Contract: tüm source connector, provider, tool, mode plug-in ve Masscan parser.
- Integration: kontrollü HTTP CONNECT/SOCKS4/SOCKS5 proxy fixture'ları.
- Failure injection: DB lock, disk full, corrupt segment, provider 429/5xx, model timeout, echo outage.
- Load: 10^7 aday metadata'sı, yoğun decision kayıtları, yüksek L4 output ve L7 concurrency.
- Security: manifest bypass, prompt injection, SSRF, tool permission ve secret leakage.
- Recovery: crash sonrası queue/spool/decision/manifest uzlaştırması.
- Restore: DB + payload + segment yedeği.

### 18.2 AI kalite testleri

- Değerlendirme kümesi replay.
- Kullanıcı kararlarıyla top-k ranking karşılaştırması.
- Karar gerekçesi ve kanıt doğruluğu incelemesi.
- Tool-use ve source coverage testi.
- Aynı context'te reproducibility testi.
- Fresh reevaluation disagreement analizi.
- Tek ajan vs. multi-agent vs. router vs. ensemble karşılaştırması.
- Model/prompt/tool ablation testi.
- Outcome calibration ve regret analizi.
- Shadow mode canlı karşılaştırma.

### 18.3 Kabul kriterleri

- Manifest dışı yürütme sıfır.
- Aşama 1'de AI decision id'si olmayan manifest sıfır.
- Aşama 1 semantik kararını veren hardcoded skor/eşik/if-else yok.
- Her decision için context, prompt, response, parsed action, model/mode sürümü ve outcome izi mevcut.
- Manuel değerlendirme kümesi performansı baseline'ın altında değil.
- AI route'ları kapalıyken yeni hedef kararı üretilmiyor.
- Mode değişimi veri kaybı veya migration gerektirmiyor.
- Restart sonrası committed manifest ve execution state tutarlı.
- L4/L7 kontrollü sette doğrulama doğruluğu kabul edilen hedefte.
- DB, queue ve spool tek makine load testini karşılıyor.

---

## 19. Geliştirme Yol Haritası

### Faz 0 — Kullanıcı bilgisini ve başarı kriterini yakalama

- Manuel myip.ms iş akışını karar günlüğü olarak belgele.
- Eski başarılı/başarısız hedefleri ve gerekçeleri değerlendirme kümesine dönüştür.
- “Yüksek değer” tanımını ve outcome etiketlerini kullanıcıyla kesinleştir.
- Kaynak lisans ve abuse/opt-out kayıt politikasını kesinleştir.
- Tek makine benchmark planını hazırla.

**Çıkış:** Ölçülebilir manuel baseline ve değerlendirme kümesi.

### Faz 1 — Domain, SQLite ve dayanıklı storage

- Veri modeli, migration ve tek DB Writer.
- Append-only payload store.
- Segment queue, lease, cursor, checkpoint ve spool.
- Event envelope, idempotency ve backup/restore.

**Çıkış:** 10^7 sentetik aday metadata'sında restart/veri kaybı testi başarılı.

### Faz 2 — Source Catalog ve keşif connector'ları

- RIR/NRO, BGPView/RIPEstat, RouteViews/RIS, PeeringDB, IRR/RPKI, CAIDA ve seed expansion.
- Cache, provenance, entity resolution ve source health.
- Yeni connector plug-in sözleşmesi.

**Çıkış:** Seçilen test evreni için uzlaştırılmış ve provenance'lı aday envanteri.

### Faz 3 — Decision Service çekirdeği

- Canonical context ve decision schema.
- Senkron karar yaşam döngüsü.
- Prompt/response audit payload'ları.
- Reproducible/fresh mode ve decision deduplication.
- Manifest builder ve karar izi.

**Çıkış:** Her Aşama 1 kararının tam audit izi ve karar bütünlüğü.

### Faz 4 — Mod Registry ve router

- Tek ajan modu.
- Manager/subagent modu.
- Router ve provider/model fallback.
- Ensemble/judge ve human-in-the-loop.
- Runtime mod değiştirme ve shadow comparison.

**Çıkış:** Aynı context'in modlar arasında değiştirilip replay edilebilmesi.

### Faz 5 — L4/L7 execution pipeline

- Masscan adapter, stdout parser, pipe/spool ve backpressure.
- HTTP CONNECT, SOCKS5 ve SOCKS4/SOCKS4a validators.
- Controlled echo service.
- Teknik timeout/retry/concurrency/rate-limit profiles.

**Çıkış:** Kontrollü fixture setinde doğru protokol ve exit doğrulaması; crash recovery başarılı.

### Faz 6 — Feedback loop ve AI anti-waste

- Evidence snapshots ve outcome attachment.
- AI üretimli sample/expand/drop/defer/reevaluate kararları.
- Hedefe özgü port planları.
- Operator feedback ve retrieval memory.

**Çıkış:** Aşama 1'de sabit eşik olmadan kapalı döngü; karar → sonuç → yeni karar zinciri denetlenebilir.

### Faz 7 — Yüksek-değer doğrulama

- Rotasyon, multi-egress, IPv6 ve residential/datacenter kanıtları.
- Artımlı test profiles.
- Kapasite testi için operatör onayı.
- AI ön tahmini ile gerçekleşen sınıf karşılaştırması.

**Çıkış:** Kontrollü static/rotating/IPv6 fixture'larında kanıta dayalı sınıflandırma.

### Faz 8 — Gölge ve kalite pilotu

- AI kararlarını manuel süreçle paralel çalıştır.
- Değerlendirme kümesi ve canlı shadow sonuçlarını karşılaştır.
- Kullanıcı düzeltmelerini sisteme ekle.
- En iyi mode/model/prompt kombinasyonlarını kullanıcıya raporla.

**Çıkış:** Manuel baseline'dan geri gitmeme kapısı sağlanır.

### Faz 9 — Ölçek pilotları

Kademeli evren büyütülür; her basamakta karar kalitesi, decision queue, provider quota, DB writer, spool, disk, ağ ve abuse sinyali gözlenir. Ölçek basamaklarının boyutu ve geçiş kararı kullanıcı tarafından benchmark sonucuna göre onaylanır; dokümana sabit büyüklük dayatılmaz.

**Çıkış:** 10^7+ aday evreninin tek makinede sürdürülebilir biçimde temsil ve işlenmesi.

### Faz 10 — Üretim sertleştirme

- systemd, least privilege ve resource limits.
- Dashboard, alarm ve runbook.
- Backup/restore ve disaster exercise.
- Mode rollback, provider outage ve kill-switch tatbikatı.
- Güvenlik ve uyum incelemesi.

**Çıkış:** Operasyonel kabul ve üretim devri.

---

## 20. Pilot ve Deney Planı

### 20.1 Karşılaştırılacak yaklaşımlar

- Kullanıcının manuel kararları.
- Tek ajan.
- Yönetici + uzman subagent.
- Router ile görev/model seçimi.
- Ensemble + judge.
- Reproducible ve fresh reevaluation.
- Farklı source/tool paketleri.

### 20.2 Deney tasarımı

- Aynı zamanda görülebilen aynı aday havuzu kullanılır.
- Execution profile ve ölçüm penceresi eşit tutulur.
- AI mode yalnız Aşama 1 kararını değiştirir.
- L4/L7 executor aynı kalır; sonuç farkı hedef seçimine bağlanabilir.
- Holdout değerlendirme kümesi mode/prompt geliştirmede kullanılmaz.
- Sonuçlar top-k hit rate, nDCG, değer/efor, recall, regret ve kullanıcı puanıyla raporlanır.

### 20.3 Terfi ve rollback

- Yeni mode/model önce replay, sonra shadow, sonra canary çalışır.
- Manuel baseline'ın altına düşen değişiklik production olamaz.
- Drift veya outcome bozulmasında önceki mode_version'a rollback yapılır.
- Kullanıcı isterse kalite/maliyet/gecikme trade-off'una göre farklı modu bilinçli seçebilir; sistem seçimi gizlice değiştirmez.

---

## 21. Operasyon Runbook Özeti

### Normal başlatma

1. Disk, DB integrity, payload manifest ve backup yaşını doğrula.
2. DB Writer, telemetry ve payload store'u başlat.
3. Queue/spool/manifest recovery çalıştır.
4. Source connector'ları ve Context Builder'ı başlat.
5. Kullanıcının seçtiği mode/model route'larını health check et.
6. Decision Service'i aç.
7. Yalnız committed ve kanıtlı manifestleri execution'a ver.

### Mod değiştirme

1. Yeni mode config'i validate et.
2. Replay/shadow sonucu varsa operatöre göster.
3. Güvenli checkpoint seç.
4. Yeni mode_version aktive et.
5. Devam eden kararları tamamla veya iptal et.
6. Yeni kararları yeni sürümle audit et.

### Kontrollü durdurma

1. Yeni decision request kabulünü kapat.
2. Yeni manifest üretimini durdur.
3. Masscan ve L7 inflight işleri profile göre bitir/pause et.
4. Result spool ve decision metadata'yı flush et.
5. WAL checkpoint ve snapshot al.

### Acil durdurma

Manifest dışı hedef, abuse bildirimi, audit bütünlüğü hatası, bozuk DB, kritik disk/spool veya beklenmeyen trafik durumunda kill switch tüm ağ yürütmesini durdurur. Kanıt korunur; otomatik yeniden başlatma yapılmaz.

---

## 22. Açık Riskler ve Çözümler

### 22.1 AI çağrı hacmi

**Risk:** On binlerce/yüz binlerce ASN/prefix kararı provider quota'sına takılabilir.
**Çözüm:** Batch request içinde aday başına ayrı decision item, eşzamanlı route havuzu, exact-context deduplication, user-selected multi-provider routing ve decision queue SLO'su. AI kararı atlanmaz.

### 22.2 AI gecikmesi

**Risk:** Hedef planı üretimi yavaşlayabilir.
**Çözüm:** Aşama 1'i paket/bağlantı yürütmesinden ayırmak; committed manifestlerin L4/L7'de AI beklemeden akması; paralel context/inference worker'ları.

### 22.3 Non-determinism

**Risk:** Aynı aday farklı zamanlarda farklı değerlendirilebilir.
**Çözüm:** Canonical snapshot, exact decision ledger reuse, pinned versions, temperature/seed kontrolü, fresh mode'un açık kullanıcı seçimi ve disagreement telemetrisi.

### 22.4 SQLite büyümesi

**Risk:** Her Aşama 1 kararının prompt/response'u ve yoğun validation geçmişi DB'yi şişirir.
**Çözüm:** Her decision için SQLite metadata satırı; ham payload'ın sıkıştırılmış immutable store'da tutulması; validation/event arşivi; tek writer ve batch insert.

### 22.5 Ajanın manuel sezgiyi yakalayamaması

**Risk:** Geniş veri kullanmasına rağmen kullanıcıdan daha kötü hedef seçmesi.
**Çözüm:** Değerlendirme kümesi, shadow mode, user feedback capture, retrieval memory, regret analizi ve baseline altındaki mode'un production'a alınmaması.

### 22.6 Kaynak yanlılığı ve güncellik

**Risk:** Tek kaynağa güvenme veya stale veri.
**Çözüm:** Provenance, source conflict görünümü, AI'ın çoklu kaynak araştırması, source health/freshness ve outcome tabanlı geri bildirim.

### 22.7 Mimari kilitlenme

**Risk:** Tek agent framework/model/stratejiye bağımlılık.
**Çözüm:** Internal contracts, Mode Registry, provider/tool/plugin adapters, runtime mode switch ve immutable versioning.

---

## 23. Ölçek Büyütme ve Yeniden Mimari Tetikleyicileri

Aşağıdakiler gerçek ölçümlerle kabul edilen SLO'yu sürekli aştığında yeni ADR açılır:

- SQLite writer lag veya WAL/maintenance penceresi,
- decision ledger/payload store büyümesi,
- segment/spool recovery süresi,
- tek makinenin CPU/RAM/disk/FD/ağ sınırı,
- provider quota nedeniyle decision queue'nun sürdürülemez büyümesi,
- birden çok scanner host ihtiyacı,
- UI analitiğinin operasyon DB'sini etkilemesi.

Olası sonraki adımlar PostgreSQL, analitik store ve durable broker olabilir; ilk sürüme peşinen dayatılmaz. Port/adapter/event/manifest sözleşmeleri bu geçişi mümkün kılar.

---

## 24. Definition of Done

- 10^7+ aday evreni prefix/segment düzeyinde tek makine üzerinde yönetiliyor.
- RIR/NRO, BGP, PeeringDB, IRR/RPKI, CAIDA ve seed kaynakları provenance ile çalışıyor.
- Kullanıcı istediği agentic modu/model route'unu runtime'da seçebiliyor, ekleyebiliyor ve çıkarabiliyor.
- Aşama 1'deki her hedef seçme, kaynak ayırma, port planlama, genişletme, early-drop, yeniden değerlendirme ve derin test sevk kararı AI decision id'sine bağlı.
- Aşama 1'de sabit mikro-örnekleme eşiği, sabit skor ağırlığı, sabit queue oranı veya sabit port önceliği yok.
- AI yalnız Aşama 1'de; Masscan/L7/retry/timeout/rate-limit teknik katmanda deterministik.
- Her AI kararının canonical context'i, ham prompt/response'u, model/mode sürümü, parsed action'ı ve outcome'u audit edilebiliyor.
- Reproducible ve fresh reevaluation modları kullanıcı tarafından seçilebiliyor.
- AI unavailable olduğunda gizli deterministic fallback yerine karar üretimi güvenli biçimde bekliyor.
- Masscan → pipe/spool → asenkron L7 zinciri backpressure, retry ve crash recovery ile çalışıyor.
- HTTP CONNECT, SOCKS4/SOCKS4a ve SOCKS5 kontrollü endpoint üzerinden doğrulanıyor.
- Rotasyon, multi-egress, IPv6 ve residential/datacenter sınıfları kanıta dayalı raporlanıyor.
- SQLite tek writer, WAL, append-only payload, arşiv, backup ve restore ile işletiliyor.
- GUI'de mode seçimi, karar açıklaması, kaynaklar, feedback, karşılaştırma ve audit görünür.
- Değerlendirme kümesi ve shadow pilotta sistemin manuel baseline'dan geri gitmediği kanıtlanmış.
- Teknik ve AI kalite testleri, güvenlik kontrolleri, runbook ve kill switch kabul edilmiş.
