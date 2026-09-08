---
name: project-orchestration
description: "Kapsamlı veya belirsiz kodlama çalışmaları için OpenCode proje orkestrasyon politikası. Sınırlandırılmış araştırma, uygulama ve bağımsız incelemeyi delege ederken, ana akıl yürütme ajanının mimari, sentez ve teknik özelliklere odaklanmasını sağlar. Küçük görevler doğrudan tamamlanabilir."
---

# Proje Orkestrasyonu

Bağlam kalitesini korumak ve kapsamlı kodlama çalışmalarını daha güvenilir hale getirmek için bu yeteneği (skill) kullanın.

Amaç ajan sayısını maksimize etmek **değildir**. Amaç, delege etme işlemi bağlam kalitesini, işleme kapasitesini veya inceleme bağımsızlığını artırdığında sınırlandırılmış işleri devrederken, en güçlü akıl yürütme döngüsünü muhakemeye odaklanmış tutmaktır.

Kapsamlı çalışmalar için şunu tercih edin:

**Araştırma → Sentez → Teknik Şartname (Spec) → Uygulama → Bağımsız İnceleme**

Gerçekten küçük çalışmalar için:

**İncele → Uygula → Doğrula**

---

## Temel kurallar

1. **Muhakemenin sahibi ana akıl yürütme ajanıdır.**
   Mimari, ödünleşimler (trade-offs), sentez, uyuşmazlık çözümü, sistemler arası tasarım, teknik şartname kalitesi ve nihai kararlar ana döngüye aittir.

2. **Sorumluluğu değil, sınırları belirlenmiş işleri devredin.**
   Geniş kod tabanı incelemesi, tekrarlayan araştırmalar, mekanik uygulamalar ve rutin doğrulamalar delege edilmeye uygun adaylardır.

3. **Küçük işler küçük kalır.**
   Önemsiz ve yerel bir değişiklik için raporlar, teknik şartnameler veya birden fazla ajan oluşturmayın.

4. **Canlı depo kanıtları üstündür.**
   Mevcut kod, testler, yapılandırma, şema ve git durumu; eski raporlardan veya sohbet özetlerinden daha önceliklidir.

5. **Sohbet geçici bir çalışma bağlamıdır.**
   Tekrar kullanılabilir araştırmalar, önemli kararlar, kapsamlı şartnameler ve bitmemiş işler kalıcı proje dosyalarında yer almalıdır.

6. **Paralellik isteğe bağlıdır.**
   Yalnızca çalışma hatları birbirinden gerçekten ayrıştırılabilir olduğunda kullanın.

---

## Rol modeli

Somut model isimleri bu yeteneğin dışında, OpenCode ajan/yapılandırma dosyalarında yapılandırılır.

### Ana akıl yürütme / orkestratör

En güçlü akıl yürütme katmanını şunlar için kullanın:

- mimari;
- belirsiz gereksinimler;
- birden fazla araştırma çıktısının sentezi;
- ödünleşimler ve muhakeme gerektiren kararlar;
- sistem genelini etkileyen (cross-cutting) tasarım;
- teknik şartnameleri yazmak veya onaylamak;
- çelişkileri çözmek;
- bir sonucun güvenilir olup olmadığına karar vermek;
- nihai proje durumu kararları.

Ana döngü; sınırlandırılmış bir delege ajan muhakemeden ödün vermeden bu işleri yapabildiğinde, geniş mekanik depo taramalarından veya büyük uygulama farklarından (diff) kaçınmalıdır.

### Araştırma

Maliyet açısından verimli ve yetenekli bir katmanı şunlar için kullanın:

- kod tabanı haritalama;
- kontrol/veri akışını izleme;
- mevcut kalıpları (patterns) tespit etme;
- bağımlılıkları keşfetme;
- commit/geçmiş incelemesi;
- odaklanmış karşılaştırma çalışmaları;
- kanıt toplama;
- rutin doğrulama adımları.

Araştırma, bir uygulama farkı (diff) değil, **kavrayış** sunar.

### Uygulama

Yetenekli bir kodlama/çalıştırma katmanını şunlar için kullanın:

- yeterince eksiksiz bir şartnameyi uygulamak;
- tanımlanmış kısıtlamalarla taşımalar (migrations) ve yeniden düzenlemeler (refactors);
- kabul kriterlerine göre test yazımı;
- tekrarlayan veya sınırları iyi çizilmiş özellik geliştirme işleri.

Uygulama katmanı mutabık kalınan yaklaşımı yürütmelidir, onu sessizce yeniden tasarlamamalıdır.

### Bağımsız inceleme

Bağımsız ve yetenekli bir katmanı şunlar için kullanın:

- teknik şartnameye uygunluk;
- regresyon analizi;
- eksik testler;
- doğruluk;
- güvenlik/veri riskleri;
- zorunlu kontrollerin doğrulanması.

Kimlik doğrulama, izinler, güvenlik, ödemeler, kalıcılık (persistence), taşımalar, yıkıcı işlemler veya doğruluk açısından kritik yollar için daha güçlü bir incelemeci kullanın.

Kullanıcı kapsamı belirlenmiş bir görev için açıkça bir model seçerse, o görev için bu seçime uyun.

---

## Görev sınıflandırması

### Küçük görev — doğrudan yapın

Aşağıdakilerin çoğu doğru olduğunda bir görev genellikle küçüktür:

- istenen davranış zaten açıktır;
- etkilenen kod yereldir (lokalize);
- yakındaki mevcut bir kalıp belirgin şekilde uygulanabilir;
- mimarinin değişmesi gerekmez;
- veri modeli, genel API, kimlik doğrulama, güvenlik veya geriye dönük uyumluluk anlamlı bir şekilde etkilenmez;
- doğrulama basittir;
- kapsamlı bir araştırma değişiklikten daha maliyetli olacaktır.

Örnekler:

- bariz bir nedeni olan küçük bir hata;
- yerel bir yapılandırma düzeltmesi;
- küçük bir arayüz/metin değişikliği;
- tek dosyada mekanik bir düzeltme;
- mevcut basit bir kalıbı tekrarlamak.

İş akışı:

1. ilgili minimum bağlamı inceleyin;
2. doğrudan uygulayın;
3. odaklanmış doğrulamayı çalıştırın;
4. sadece formalite icabı orkestrasyon çıktıları oluşturmayın.

### Kapsamlı görev — orkestre edin

Aşağıdakilerden biri veya birkaçı doğru olduğunda tam iş akışını kullanın:

- gereksinimler belirsizdir;
- önce mevcut mimarinin anlaşılması gerekir;
- birden fazla modül/sistem etkileşim halindedir;
- kimlik doğrulama, güvenlik, kalıcılık, taşımalar, ödemeler veya genel sözleşmeler dahildir;
- değişiklik geniş çaplı bir yeniden düzenlemedir;
- anlamlı uyumluluk/regresyon riskleri mevcuttur;
- uygulama, henüz toplanmamış gerçeklere bağlıdır;
- görevin oturumlar arası sürmesi muhtemeldir;
- kullanıcı önce araştırma/tasarım/teknik şartname talep etmiştir.

---

## Bağlam yükleme

Her şeyi önceden yüklemek yerine bağlamı aşamalı olarak yükleyin.

Varsa tipik kalıcı dosyalar:

- `AGENTS.md`
- `context/PROJECT.md`
- `context/ARCHITECTURE.md`
- `context/DECISIONS.md`
- `reports/` altındaki ilgili dosyalar
- `specs/` altındaki ilgili dosyalar
- `backlog/BACKLOG.md`

Süreç:

1. proje genelindeki talimatları okuyun;
2. mevcut soruyu tanımlayın;
3. yalnızca ilgili kalıcı bağlamı yükleyin;
4. ana döngüyü boğacak geniş çaplı keşifleri delege edin;
5. daha fazla bağlamı yalnızca kanıtlar gerekli olduğunu gösterdiğinde getirin.

Sırf burada listelendikleri için eksik dosyaları oluşturmayın.

---

## Araştırma politikası

Araştırmayı başlatmadan önce eksik olan soruyu açıkça tanımlayın.

İyi brifingler:

- "İstek girişinden veritabanı yüklemesine kadar kiracı (tenant) yapılandırmasını izleyin."
- "Kimlik doğrulama oturumlarını oluşturan veya geçersiz kılan her yolu haritalandırın."
- "Mevcut yetenek yükleyiciyi referans tasarımla karşılaştırın ve eksiklikleri döndürün."
- "İlgili son commit'leri inceleyin ve davranış değişikliklerini açıklayın."
- "Bu servisi çağıranları bulun ve uyumluluk kısıtlamalarını belirleyin."

Kaçınılması gerekenler:

- "Tüm depoyu oku."
- "Her şeyi anla."
- Geçerli bir neden olmaksızın aynı belirsiz soruyu araştıran mükerrer ajanlar.

Araştırma çıktısı şunları birbirinden ayırmalıdır:

### Doğrulanmış gerçekler
Mevcut kod, testler, yapılandırma, şema, git geçmişi veya yetkili dokümanlar tarafından desteklenen bilgiler.

### Varsayımlar
Makul ancak kanıtlanmamış çıkarımlar.

### Bilinmeyenler
Halen kanıt veya kullanıcı kararı gerektiren sorular.

### Riskler
Regresyon, güvenlik, veri, uyumluluk veya doğruluk endişeleri.

### Öneriler
Gerçeklerden net bir şekilde ayrılmış, kanıta dayalı sonraki adımlar.

Mümkün olan her durumda dosya yolları, semboller, testler, komutlar, commit'ler veya yapılandırma anahtarları gibi kanıtları dahil edin.

---

## `reports/` politikası

`reports/` dizinini **yeniden kullanılabilir araştırma bilgisi** için kullanın.

Her küçük aramayı kaydetmeyin.

Aşağıdakilerden en az biri doğru olduğunda bir rapor oluşturun:

- araştırma geniş kapsamlı veya maliyetliydi;
- sonucun yeniden kullanılması muhtemeldir;
- birden fazla ajan aynı bulgulara ihtiyaç duymaktadır;
- çalışma başka bir oturumda devam edebilir;
- bulgular bir tasarım/şartname kararını gerekçelendirmektedir;
- araştırmayı daha sonra tekrarlamak verimsiz olacaktır.

Önerilen format:

```markdown
# <Araştırma başlığı>

Oluşturulma: <biliniyorsa tarih/saat>
Dayandığı Git HEAD: <varsa commit, aksi takdirde bilinmiyor>
Kapsam: <ne incelendi>

## Soru
## Doğrulanmış gerçekler
## Varsayımlar
## Bilinmeyenler
## Riskler
## Öneriler
## Kanıtlar / incelenen dosyalar

```

Rapor bir **anlık görüntüdür (snapshot)**, kalıcı bir gerçeklik değildir.

Önemli bir karar için eski bir rapora güvenmeden önce:

1. tarihini, commit bilgisini ve kapsamını kontrol edin;
2. kritik iddiaları mevcut depoya karşı doğrulayın;
3. kod önemli ölçüde değiştiyse raporu yenileyin veya geçersiz kılın.

Eski bir raporun canlı depo kanıtlarının önüne geçmesine asla izin vermeyin.

---

## Sentez politikası

Araştırma ajanları kanıt toplar. Sentezin sahibi ana akıl yürütme döngüsüdür.

Araştırmadan sonra:

1. bulguları karşılaştırın ve uzlaştırın;
2. kanıtları kontrol ederek çelişkileri çözün;
3. kalan bilinmeyenleri belirleyin;
4. modüller arasındaki bulguları birbirine bağlayın;
5. en küçük tutarlı yaklaşıma karar verin;
6. uyumluluk kısıtlamalarını belirleyin;
7. regresyon/güvenlik risklerini belirleyin;
8. kullanıcının gerçek bir ürün/kapsam ödünleşimi yapması gerekip gerekmediğine karar verin.

Şu ayrımı kullanın:

* **Araştırma:** Şu anda doğru olan ne?
* **Sentez:** Bu ne anlama geliyor?
* **Karar:** Ne yapmalıyız?

Raporları basitçe art arda ekleyip buna tasarım demeyin.

Kullanıcıya yalnızca gerçek bir ürün, kapsam veya ödünleşim kararı çözümsüz kaldığında danışın.

---

## Doğruluk kaynağı hiyerarşisi

**Mevcut uygulama gerçekleri** için:

1. mevcut kod, yapılandırma ve şema;
2. mevcut testler ve yürütülebilir doğrulama;
3. mevcut git durumu/geçmişi;
4. son doğrulanmış raporlar;
5. eski raporlar, özetler veya sohbet geçmişi.

**Hedeflenen davranış** için:

1. kullanıcının mevcut açık talimatı;
2. mevcut onaylanmış teknik şartname;
3. kalıcı proje kararları;
4. geriye dönük uyumluluğun korunması gerektiğinde mevcut davranış.

"Mevcut olan" ile "olması gereken" durumları birbirine karıştırmayın.

---

## Teknik Şartname (Spec) politikası

Gerçekten küçük işler için şartname zorunluluğu getirmeyin.

Kapsamlı uygulamalar için, belirgin bir kodlama başlamadan önce `specs/` altında bir dosya oluşturun veya güncelleyin.

Önerilen format:

```markdown
# <Görev / özellik>

## Hedef
## Kapsam dışı hedefler (Non-goals)
## Mevcut durum
## İstenen durum
## Gereksinimler
## Kısıtlamalar / değişmezler (invariants)
## Etkilenen alanlar
## Uyumluluk gereksinimleri
## Riskler / uç durumlar
## Kabul kriterleri
## Doğrulama
## Uygulama notları

```

İyi bir şartname uygulamayı tekdüze (öngörülebilir) hale getirmelidir.

Uygulayıcının büyük mimari veya ürün kararları icat etmesine gerek kalmamalıdır.

Kullanıcı uygulamayı zaten açıkça talep etmişse ve çözülmemiş önemli bir karar kalmamışsa, gereksiz bir onay seremonisi eklemeyin.

Kullanıcı yalnızca araştırma/planlama/şartname istediyse, bu sınırda durun.

---

## Uygulama politikası

Uygulama katmanına şunlar verilir:

* ilgili `AGENTS.md` talimatları;
* mevcut şartname;
* yalnızca yürütme için gereken araştırma/bağlam;
* kabul kriterleri;
* doğrulama gereksinimleri.

Uygulama katmanı şunları yapmalıdır:

1. mevcut kurallara (conventions) uymak;
2. gerekli değişmezleri (invariants) korumak;
3. uyumluluk gereksinimlerini korumak;
4. gereksiz kapsam genişlemesinden kaçınmak;
5. tutarlı ve incelenebilir değişiklikler yapmak;
6. zorunlu kontrolleri çalıştırmak;
7. anlamlı başarısızlıkları dürüstçe raporlamak.

Uygulama sırasında şartnameyi geçersiz kılan kanıtlar keşfedilirse:

1. büyük ve doğaçlama bir yeniden tasarıma girişmeden önce durun;
2. uyuşmazlığı ve kanıtı raporlayın;
3. muhakemeyi ana akıl yürütme döngüsüne devredin;
4. gerekirse şartnameyi/kararı güncelleyin;
5. yalnızca yaklaşım yeniden tutarlı hale geldikten sonra devam edin.

---

## Bağımsız inceleme politikası

Kapsamlı çalışmalar, uygulamadan sonra bağımsız incelemeden geçmelidir.

İncelemeci normal şartlarda **uygulamayı düzenlememelidir**.

Şunlara göre inceleyin:

* mevcut şartname;
* proje talimatları;
* gerçek fark (diff) / mevcut dosyalar;
* kabul kriterleri;
* doğrulama çıktısı;
* regresyon riskleri;
* göreve uygun güvenlik/doğruluk endişeleri.

Önerilen sonuç formatı:

```markdown
## Karar
GEÇTİ (PASS) | KALDI (FAIL)

## Şartnameye uygunluk
## Hatalar / doğruluk sorunları
## Regresyon riskleri
## Eksik veya zayıf testler
## Güvenlik / veri endişeleri
## Gerekli düzeltmeler
## Kanıtlar

```

GEÇTİ kararı kanıt gerektirir.

İnceleme başarısız olursa:

1. somut hataları uygulamaya geri gönderin;
2. doğrulanmış hataları ve ilgili kök nedenleri düzeltin;
3. etkilenen kontrolleri tekrar çalıştırın;
4. görev riski gerektirdiğinde yeniden inceleyin.

Küçük ve düşük riskli işler için odaklanmış öz-doğrulama yeterli olabilir.

---

## İnceleme sonrası kalıcı bağlam bakımı

Kapsamlı bir görev tamamlandıktan ve zorunlu incelemeden geçtikten sonra, tamamlanan değişikliğin kalıcı proje bağlamını eskitip eskitmediğini değerlendirin. Yalnızca ilgili mevcut bağlamı güncelleyin:

* `context/PROJECT.md` dosyasını yalnızca projenin amacı veya kapsamı değiştiğinde güncelleyin;
* `context/ARCHITECTURE.md` dosyasını yalnızca mimari değiştiğinde güncelleyin;
* `context/DECISIONS.md` dosyasını yalnızca kalıcı bir mimari veya ürün kararı alındığında güncelleyin;
* birikim listesini (backlog) yalnızca bitmemiş iş kaldığında güncelleyin.

Küçük veya rutin değişiklikler için bu dosyalara dokunmayın. Sırf uygulama ayrıntılarını kaydetmek için bağlam karmaşası yaratmayın. Raporları geçmiş anlık görüntüler olarak ele alın: eski bir raporu sırf güncel görünmesi için asla yeniden yazmayın.

---

## `backlog/` politikası

`backlog/BACKLOG.md` dosyasını araştırma bilgisi için değil, **tamamlanmamış yürütme durumu** için kullanın.

İş şu durumlardayken güncelleyin:

* kasıtlı olarak duraklatıldığında;
* engellendiğinde;
* kısmen tamamlandığında;
* başka bir oturuma/ajana devredildiğinde.

Önerilen girdi:

```markdown
## <Görev>

Durum: Devam ediyor | Engellendi

### Hedef
### Tamamlananlar
### Kalanlar
### Engelleyiciler / bilinmeyenler
### Önemli kısıtlamalar
### Önerilen sonraki eylem

### İlgili
- spec:
- reports:
- branch/commit:

```

Amacı, bir sonraki oturumun sohbet geçmişinden görevi yeniden kurgulamak zorunda kalmadan devam edebilmesini sağlamaktır.

İş gerçekten bittiğinde tamamlanan maddeleri kaldırın veya arşivleyin.

---

## Kalıcı kararlar

Proje kalıcı karar takibi kullanıyorsa, önemli ve uzun ömürlü kararlar için `context/DECISIONS.md` dosyasını kullanın.

Şunları kaydedin:

* karar;
* gerekçe;
* reddedilen önemli alternatifler;
* getirilen kısıtlamalar;
* ne zaman yeniden değerlendirileceği.

Uygun adaylar:

* mimari seçimler;
* sağlayıcı/depolama kararları;
* uyumluluk politikaları;
* önemli güvenlik veya veri kısıtlamaları.

Rutin uygulama ayrıntılarını kaydetmeyin.

---

## Paralel ajan politikası

Paralellik, iş net bir şekilde ayrıldığında kullanışlıdır.

Uygun adaylar:

* arka uç analizi ve ön uç analizi;
* mevcut sistem analizi ve referans sistem analizi;
* bağımsız taşıma/test/denetim alanları;
* ayrı geçmiş commit aralıkları;
* minimum çakışan yazma işlemine sahip bağımsız uygulama hatları.

Paralel hatları başlatmadan önce:

1. her hattın kesin sorumluluğunu tanımlayın;
2. çakışmayı en aza indirin;
3. beklenen çıktıyı tanımlayın;
4. sonuçları kimin sentezleyeceğine karar verin;
5. paylaşılan proje durumuna kontrolsüz eşzamanlı düzenlemeler yapılmasından kaçının.

Tek bir belirsiz soru için birden fazla ajan açmayın.

Paralellik şunlara yardımcı olur:

* işleme kapasitesi (throughput);
* bağlam izolasyonu;
* bağımsız bakış açıları.

Bağımlılıklar sıkı olduğunda, yazma yüzeyleri çakıştığında, sorumluluklar belirsiz olduğunda veya sentez sahipliği bulunmadığında zarar verir.

---

## İsteğe bağlı paylaşılan kayıt kütüğü (shared ledger)

Paylaşılan bir kayıt kütüğü **sıradan işler için gerekli değildir**.

Yalnızca birden fazla uzun süreli hattın paylaşılan ilerleme görünürlüğüne gerçekten ihtiyacı olduğunda kullanın.

Eğer getirilirse basit tutun:

* görev/hat;
* sahip;
* durum;
* bağımlılık;
* çıktı/sonuç.

Çalışanlar (workers) durum bildirebilir, ancak paylaşılan durumun nihai yorumu orkestratöre ait olmalıdır.

Sırf mevcut olduğu için normal görevler için filo/worktree/kayıt kütüğü mekanizmalarını devreye sokmayın.

---

## Paylaşılan durum sahipliği

Varsayılan sahiplik:

* araştırmacı → araştırma bulguları/raporları;
* uygulayıcı → kod değişiklikleri;
* incelemeci → inceleme bulguları;
* orkestratör → mimari kararları, nihai sentez, paylaşılan şartnameler, kalıcı proje durumu.

Şunlar için nihai yazıcı olarak orkestratörü tercih edin:

* `context/DECISIONS.md`;
* paylaşılan birikim listesi (backlog) durumu;
* araştırma çıktıları çeliştiğinde nihai/mevcut şartnameler.

Bu bir bürokrasi değil, tutarlılık kuralıdır.

---

## Bağlam bütçesi disiplini

Ana akıl yürütme döngüsünü mekanik gürültüden koruyun.

Şunları tercih edin:

* dar kapsamlı araştırma brifingleri;
* kanıtla desteklenen özetler;
* maliyetli bulgular için kalıcı raporlar;
* hedefe yönelik bağlam yükleme;
* kararları yürütülebilir sözleşmelere sıkıştıran şartnameler.

Kaçınılması gerekenler:

* her araç günlüğünü (log) ana döngüye dökmek;
* tüm depoyu tekrar tekrar okumak;
* doğrulanmış bir özet yeterliyken devasa ham araştırma dökümlerini döndürmek;
* bir neden olmaksızın birden fazla ajanın aynı soruyu yanıtlaması;
* önemli kararların tek kaydı olarak uygulama sohbetine güvenmek.

Delege etme, hem **işleme kapasitesi** hem de **bağlam izolasyonu** açısından değerlidir.

---

## Başarısızlık ve eskalasyon

Uzmanlaşmış bir rol yapılandırılmamışsa:

* delege etme gerçekleşmiş gibi davranmayın;
* hattı mevcut oturumda bilinçli olarak dar bir kapsamla yürütün;
* araştırma, sentez, uygulama ve inceleme arasındaki kavramsal ayrımı koruyun.

Daha ucuz bir araştırma katmanı zayıf veya çelişkili çıktılar verirse:

1. kesin zor soruyu belirleyin;
2. yalnızca o soruyu daha güçlü akıl yürütme katmanına iletin (eskale edin);
3. tüm görevi daha pahalı bir modelle körü körüne yeniden çalıştırmayın.

Araştırma ajanları anlaşmazlığa düşerse:

1. kanıtları karşılaştırın;
2. kritik iddiaları canlı depo durumuna göre doğrulayın;
3. kararı ana akıl yürütme döngüsüne bırakın.

Bir görev beklenmedik şekilde büyürse:

* görevi yeniden sınıflandırın;
* ona küçük ve doğrudan bir görev muamelesi yapmayı bırakın;
* riskli çalışmaya devam etmeden önce gerekli araştırma/şartnameyi ekleyin.

---

## Tamamlanma kuralı

Kapsamlı bir görev yalnızca şu durumlarda tamamlanmış sayılır:

* hedeflenen davranış uygulanmışsa;
* kabul kriterleri karşılanmışsa veya istisnalar açıkça belirtilmişse;
* gerekli doğrulama çalıştırılmışsa;
* inceleme açısından kritik hatalar çözülmüşse;
* gerektiğinde kalıcı proje durumu güncellenmişse;
* bitmemiş işler sessizce arkada bırakılmamışsa.

İş kasıtlı olarak bitirilmemişse, temiz bir devir ile birikim listesini (backlog) güncelleyin.

---

## Hızlı yönlendirme kontrol listesi

1. **Bu gerçekten küçük bir iş mi?**
* Evet → incele, doğrudan uygula, doğrula.
* Hayır → devam et.


2. **Hangi önemli bağlam eksik?**
* Faydalı olduğu yerlerde sınırlandırılmış araştırmayı delege et.


3. **Araştırma maliyetli mi veya yeniden kullanılabilir mi?**
* Evet → `reports/` altına kaydet.


4. **Bulgular tek bir tutarlı karar halinde sentezlendi mi?**
* Hayır → uygulamadan önce sentezle.


5. **Kapsamlı bir uygulama başlamak üzere mi?**
* Evet → şartnameyi oluştur/güncelle.


6. **Uygulayıcı büyük kararlar icat etmeden şartnameyi takip edebilir mi?**
* Hayır → şartnameyi iyileştir.


7. **Değişiklik kapsamlı veya riskli mi?**
* Evet → bağımsız inceleme.


8. **İş duraklatılıyor veya devrediliyor mu?**
* Evet → birikim listesini (backlog) güncelle.


9. **Paralellik gerçekten bağımsız hatlar oluşturur mu?**
* Evet → dikkatli kullan.
* Hayır → iş akışını ardışık tut.



---

## Nihai ilke

Amaç şu değildir:

**"Mümkün olduğunca çok ajan kullanmak."**

Amaç şudur:

**"Doğru bağlamı toplamak, ana ajanın muhakeme kapasitesini korumak, önemli kararları netleştirmek, net bir sözleşmeye dayalı olarak yürütmek ve sonucu doğrulamak."**

