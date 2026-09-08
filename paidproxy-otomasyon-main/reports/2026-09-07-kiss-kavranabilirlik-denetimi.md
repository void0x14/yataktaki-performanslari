# KISS ve İnsan/AI Kavranabilirliği Denetimi

Tarih: 2026-09-07
Kapsam: Proje kökü, desktop başlatma yolları, frontend/Tauri ağaçları, üretim çıktıları ve Git sınırı.

## Kullanıcı ilkesi

> Bir insanın ve bir AI ajanının birlikte bütünüyle kavrayabileceği sistemler kur.

Bu rapor, mevcut yapıyı bu ilkeye göre değerlendirir. Bu aşamada uygulama kodu değiştirilmemiştir.

## Kısa karar

En büyük sorun klasör sayısı değil, aynı PaidProxy ürününün birden fazla resmiymiş gibi görünen uygulama ve kaynak ağacına bölünmesidir.

Önerilen sıra:

1. Git sınırını bağımsız proje olarak netleştir.
2. Tek resmi masaüstü uygulaması seç.
3. Tek frontend kaynağı ve tek Tauri kaynağı bırak veya Tauri'yi tamamen çıkar.
4. Üretilmiş çıktıları kaynak ağacından ayır ve ignore et.
5. Tek, konumdan bağımsız başlatıcı ve tek kurulum komutu bırak.
6. Klasör sözlüğünü README'nin en üstüne koy.

## Doğrulanmış gerçekler

### 1. Git kökü yanlış sınırda

`git rev-parse --show-toplevel` sonucu `/home/void0x14/Belgeler` dönüyor. Proje kendi klasöründe bağımsız Git köküne sahip değil. Üst repository'nin remote adı da PaidProxy ile doğrudan uyuşmuyor.

Bu, yanlış klasörlerin aynı commit'e veya push'a girmesi riskini yaratır.

### 2. Aynı frontend/Tauri yapısı iki kez var

Hem kökte hem `cockpit/` altında aynı tür yapı bulunuyor:

- `app/src/`
- `src-tauri/`
- `dist-ui/`
- `package.json`
- `package-lock.json`
- `vite.config.ts`

Özellikle kök `src-tauri/tauri.conf.json` ile `cockpit/src-tauri/tauri.conf.json` aynı ürün adı, identifier ve port ayarlarını taşıyor. `app/src/main.ts` ve `cockpit/app/src/main.ts` de aynı kokpitin kopyaları gibi görünüyor.

Bir geliştirici için cevaplanamayan sorular:

- Hangi `main.ts` değiştirilecek?
- Hangi `src-tauri` build edilecek?
- Hangi `dist-ui` güncel?
- Hangi binary dağıtılacak?

### 3. Üç farklı masaüstü yolu var

1. **PySide6 uygulaması:** `./desktop-launch` → `desktop.app.main`
2. **Tauri/Vite uygulaması:** `./cockpit/KOKPITI-AC.sh`
3. **Linux uygulama menüsü:** `desktop/install.sh` ile kurulan `.desktop` girdisi; o da `desktop-launch`ı açıyor.

Dokümantasyonun ana yolu PySide6 uygulamasını resmi ürün gibi gösteriyor. Buna rağmen `cockpit/KOKPITI-AC.sh` aynı ürün adıyla farklı bir uygulama açıyor.

### 4. Tauri başlatıcısı kendi kaynak ağacıyla tutarlı değil

`cockpit/KOKPITI-AC.sh`:

- proje kökünde Vite başlatıyor;
- sonra `cockpit/src-tauri/target/debug/paidproxy-cockpit` binary'sini çalıştırıyor.

Kök Vite kök `app/src` ve kök `dist-ui` ile ilişkilidir. Cockpit Tauri yapılandırması ise `cockpit/dist-ui` bekler. Bu iki yol zamanla farklılaşırsa kullanıcı yanlış frontend'i görebilir veya eski binary çalıştırabilir.

### 5. Sabit makine yolu var

`cockpit/KOKPITI-AC.sh` içinde `/home/void0x14/Belgeler/paidproxy-otomasyon-main` sabit yazılmış. Başka klasöre taşınırsa çalışmaz.

`desktop-launch` ise kendi konumunu bulduğu için bu konuda doğru örnektir.

### 6. Kaynak ve üretim çıktıları karışmış

Çalışma ağacında kaynak olmayan büyük klasörler var:

- `node_modules/`
- `cockpit/node_modules/`
- `build/`
- `dist/`
- `dist-ui/`
- `cockpit/dist-ui/`
- `src-tauri/target/`
- `cockpit/src-tauri/target/`
- `var/`
- `__pycache__/`

Ölçümde `src-tauri/` yaklaşık 3 GB, `cockpit/` yaklaşık 3.4 GB, `.venv/` yaklaşık 777 MB görünüyordu. Bu boyutların önemli kısmı build ve bağımlılık çıktısıdır; insanın kaynak kodu sanmasına gerek yoktur.

`.gitignore` içinde `node_modules/`, `dist-ui/` ve `**/target/` açıkça yok.

## Klasörlerin sade sınıflandırması

Mevcut 28 üst seviye dizinin tamamı aynı önemde değil:

### Ürünün asıl kaynakları

- `src/`: Python çekirdek pipeline
- `services/`: VDS üzerindeki agentd ve servisler
- `desktop/`: PySide6 masaüstü uygulaması ve kurulumu
- `tests/`: testler
- `config/`: çalışma politikaları ve ayarlar
- `migrations/`: veritabanı değişimleri

### Proje anlaşılabilirliği için gerekli belgeler

- `docs/`: ayrıntılı teknik dokümanlar
- `context/`: kalıcı proje/mimari/karar bağlamı
- `specs/`: teknik şartnameler
- `reports/`: araştırma anlık görüntüleri
- `backlog/`: bitmemiş iş durumu
- `ops/`: kurulum, VDS, systemd ve operasyon scriptleri
- `evaluation/`: değerlendirme ve shadow testleri

### Ayrıştırılması veya tekilleştirilmesi gerekenler

- `app/`, `cockpit/app/`: duplicate frontend kaynakları
- `src-tauri/`, `cockpit/src-tauri/`: duplicate Tauri kaynakları
- `cockpit/`: hangi ürünün sahibi olduğu belirsiz ikinci uygulama

### Kaynak ağacından çıkarılması gereken çalışma çıktıları

- `build/`, `dist/`, `dist-ui/`
- `node_modules/` ve `cockpit/node_modules/`
- `src-tauri/target/` ve `cockpit/src-tauri/target/`
- `var/`

### Proje kökünde durması tartışmalı tekil dosyalar

- `0K-TR_v4_none_invalid.txt`
- `run_chk.pyn + script.encode() + bnEOFnpython3`
- `scan.pynpython3`

Bu dosyaların amacı ve aktif olup olmadığı belgelenmiyorsa `archive/` veya `scratch/` altında tutulmalı; aktif değillerse kaldırılmalıdır.

## KISS ihlallerinin kök nedenleri

1. **Tek sorumluluk yok:** `desktop`, `cockpit`, `app` ve `src-tauri` aynı ürün yüzeyine talip.
2. **Tek kaynak yok:** Aynı frontend iki farklı yerde.
3. **Tek giriş yok:** Kullanıcı iki farklı başlatıcıdan hangisini seçeceğini bilmiyor.
4. **Kaynak/çıktı ayrımı yok:** Build çıktıları kaynak klasörleriyle yan yana.
5. **Sınır yok:** Git kökü proje klasörünü kapsamıyor.
6. **İsimlendirme sözleşmesi yok:** `app`, `desktop`, `cockpit` gibi isimler ürün rolünü tek başına anlatmıyor.

## Önerilen hedef karar

Mevcut kod ve belgeler dikkate alındığında kısa vadede **PySide6 masaüstünü tek resmi uygulama olarak korumak** daha düşük riskli görünüyor:

- `desktop/app/main.py` gerçek ve kapsamlı masaüstü akışını içeriyor.
- `desktop-launch` zaten konumdan bağımsız çalışıyor.
- `desktop/install.sh` Linux uygulama menüsü kurulumu sağlıyor.
- Backend bağlantısı `desktop/app` içinde zaten mevcut.
- Tauri tarafı aynı ürünü tekrarlıyor ve başlatma akışı tutarsız.

Bu öneri ürün kararıdır; Tauri'nin gelecekte asıl ürün olması istenirse yön tersine çevrilir. Fakat iki uygulama aynı anda resmi tutulmamalıdır.

## Nasıl düzeltilecek

### Faz 1 — Güvenli netleştirme

Kod taşımadan önce:

1. `desktop-launch`ı tek resmi başlatıcı ilan et.
2. `cockpit/KOKPITI-AC.sh`ı `legacy` olarak işaretle veya çalışmasını açıkça durdur.
3. README'nin ilk ekranında sadece şu akışı bırak:

```bash
./desktop/install.sh
./desktop-launch
```

4. `docs/`, `context/`, `reports/` ve `specs/` klasörlerinin farkını bir tabloyla anlat.
5. Bu raporda bilinmeyen dosyaları sahipleriyle eşleştir.

### Faz 2 — Tekilleştirme

PySide6 seçimi korunursa:

- Tauri frontend kaynaklarını ve Tauri build ağacını arşivle veya kaldır.
- Kök `app/`, `src-tauri/`, `package.json`, `vite.config.ts` ve Node bağımlılıklarını kaldır; ancak önce gerçekten kullanılan bir akış olmadığını test et.
- `cockpit/`ı da aynı şekilde kaldır veya yalnızca tarihsel arşiv olarak `archive/cockpit-legacy/` altına taşı.
- Resmi masaüstü kaynak yolu yalnızca `desktop/app/` olur.

Tauri seçilirse bunun yerine `desktop/` içindeki PySide6 uygulaması arşivlenir ve Tauri için yalnızca bir frontend + bir `src-tauri` bırakılır. İki seçeneği birlikte sürdürmek KISS değildir.

### Faz 3 — Çıktı ve Git temizliği

`.gitignore` içine en az şunlar eklenir:

```gitignore
node_modules/
**/node_modules/
dist/
dist-ui/
build/
**/target/
var/
__pycache__/
*.py[cod]
*.sqlite3
```

Derlenmiş dosyalar release paketleme alanına veya CI çıktısına gider; kaynak klasöründe tutulmaz.

### Faz 4 — Git sınırı

En güvenli çözüm proje içinde yeni, bağımsız bir Git repository oluşturmaktır:

```text
/home/void0x14/Belgeler/paidproxy-otomasyon-main/.git
```

Bunu yapmadan önce mevcut üst repository'nin PaidProxy geçmişiyle ilişkisi doğrulanmalıdır. Üst repository üzerine körlemesine commit veya `git init` yapılmamalıdır; mevcut çalışma kaybı ve yanlış push riski vardır.

### Faz 5 — İnsan ve AI için tek sayfalık harita

README'nin başına şu tür bir harita konur:

```text
PaidProxy
├── desktop/   Kullanıcının açtığı masaüstü uygulaması
├── src/       Çekirdek pipeline
├── services/  VDS servisleri
├── config/    Ayarlar ve politikalar
├── ops/       Kurulum ve işletme scriptleri
├── tests/     Otomatik testler
└── docs/      İnsan/AI açıklamaları
```

Her klasör için üç cümlelik sözleşme bulunur:

1. Ne yapar?
2. Neye dokunmaz?
3. Nasıl çalıştırılır veya test edilir?

## Kabul kriterleri

Sadeleştirme tamamlandığında:

- Yeni bir kullanıcı yalnızca bir resmi başlatıcı görür.
- Aynı ürün için tek UI kaynak ağacı vardır.
- Aynı ürün için tek Tauri ağacı vardır veya Tauri tamamen yoktur.
- Build/cache klasörleri kaynak klasörlerinden ayrıdır ve ignore edilmiştir.
- Git kökü yalnızca PaidProxy'yi kapsar veya monorepo kararı açıkça belgelenmiştir.
- README'den masaüstünü kurup başlatmak için gereken yol tek ekranda anlaşılır.
- Bir AI ajanı, ana klasör haritasını okuyarak doğru dosyaya yönlendirilebilir.

## Açık ürün kararı

Uygulamaya geçmeden önce yalnızca şu karar kesinleştirilmelidir:

> Resmi masaüstü uygulaması PySide6 mı olacak, Tauri mi?

Mevcut kanıta göre önerim: **PySide6 kalsın, Tauri duplicate/legacy olarak çıkarılsın.**
