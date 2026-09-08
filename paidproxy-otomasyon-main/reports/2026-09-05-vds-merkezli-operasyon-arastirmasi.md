# VDS merkezli operasyon omurgası araştırması

Oluşturulma: 2026-09-05
İncelenen alan: paidproxy-otomasyon-main masaüstü istemcisi, VDS çalışma durumu ve mevcut operasyon tasarımı.

## Soru

Yerel masaüstünün yalnızca kumanda/gözlem/sonuç teslimi yaptığı, bütün AI keşfi, tarama, doğrulama ve kayıt işlerinin VDS üzerinde yürüdüğü gerçek operasyon modelinin mevcut iskeletle kurulabilir olup olmadığı.

## Doğrulanmış gerçekler

- VDS erişilebilir: Debian 13 tabanlı ARM64, 2 vCPU, yaklaşık 3.8 GiB RAM ve yaklaşık 59 GiB boş disk.
- VDS'de /usr/bin/masscan ve Python 3.13.5 mevcut.
- VDS'de paidproxy-worker.service ve proxy-pipeline.service aktif değil.
- VDS'de aktif PaidProxy ajanı, proxy_pipeline prosesi veya Masscan işi yok.
- VDS'de çalışan 8888 servisi PaidProxy çıktısı değil; localhost erişimiyle sınırlandırılmış tinyproxy'dir.
- VDS repo kopyası /home/mani/paidproxy-otomasyon altındadır.
- Mevcut desktop/app/vds.py SSH üzerinden tek komutluk, bloklayan subprocess çağrısı yapıyor; kalıcı uzak iş kimliği ve event akışı yok.
- desktop/app/store.py süreçleri yalnızca masaüstü belleğinde tutuyor. hard_kill uzak PID sonlandırmıyor; yalnızca yerel status alanını değiştiriyor.
- desktop/app/recall.py yerel masaüstü görüntüsü alıyor. VDS ajan çalışma alanı, tarayıcı görüntüsü veya uzak video akışı yok.
- src/proxy_pipeline/otonom.py boş girişte sabit keşif kaynaklarına düşüyor, karar üretip Masscan komutu hazırlıyor; uçtan uca VDS işi başlatmıyor.
- src/proxy_pipeline/uzak_tara.py uzaktaki Masscan komutunu SSH ile senkron çalıştırıyor; kalıcı job, canlı süreç kontrolü ve gerçek site doğrulama zinciri eksik.
- Mevcut docs/superpowers tasarımı VDS'yi kurulum/komut noktası, desktop'u süreç sahibi kabul ediyor. Bu, güncel VDS-merkezli gereksinimle uyumlu değil.
- Mevcut UI native PySide6 masaüstü kabuğudur; fakat ajan durumu, pet, düşünce ve canlı kayıtlar gerçek uzak ajan olaylarına bağlı değildir.
- context/PROJECT.md ve context/ARCHITECTURE.md dört sabit aşamalı bir akış tarif ediyor. Bu, AI'nın araç seçimi ve sonraki adımı dinamik belirlemesi şartını karşılamıyor.

## Varsayımlar

- VDS, operasyon merkezi olarak sürekli açık ve dışarıdan yalnızca kimlik doğrulanmış masaüstü bağlantısına izin verecek şekilde kullanılacak.
- Yerel makinede tarama, L7 doğrulama veya AI iş döngüsü çalıştırılmayacak.
- İlk omurga tek VDS üzerinde başlayacak; ileride birden fazla VDS eklenebilmesi için iş/ajan kimlikleri VDS sağlayıcısından bağımsız tutulacak.

## Bilinmeyenler

- VDS'de kalıcı servis kurulumunun hangi systemd kullanıcısı ve dizin izinleriyle yapılacağı.
- VDS'de ajanların gerçek tarayıcı çalışma alanı için hangi headless browser bileşeninin kurulacağı.
- Kullanılacak AI endpoint kimlik bilgilerinin çalışma zamanında nasıl belleğe alınacağı.
- Operasyonun hangi güvenlik ve kanıt kapılarıyla sınırlandırılacağı.

## Riskler

- SSH üzerinde tek komutluk senkron çalıştırma, masaüstü kapanınca işi ve kontrolü belirsiz bırakır.
- Yerel UI status'u gerçek VDS PID'siyle eşleşmezse sert müdahale yalnızca görsel olur.
- Ekran görüntüsü ve video yalnızca yerelde alınırsa kullanıcı gerçek ajan davranışını izleyemez.
- Açık TCP portu proxy kanıtı değildir; protokol el sıkışması, gerçek hedef istekleri ve kaynak kanıtı birlikte saklanmalıdır.
- Sabit port listeleri ve eşikler yeni proxy türlerini sistematik olarak kaçırır.
- VDS'de dışarı açık kontrol uç noktası kimlik doğrulamasız bırakılırsa operasyon yüzeyi tehlikeye girer.

## Öneri

Yeni omurga VDS üzerinde kalıcı bir paidproxy-agentd gözetmeni olmalıdır. Gözetmen her ajanı ayrı uzak iş olarak yaratmalı, PID/cgroup kimliğini saklamalı, komutları ve olayları append-only kaydetmeli, canlı event akışı ve replay üretmeli, pause/resume/kill/destroy komutlarını doğrudan uygulamalıdır.

Yerel PySide6 uygulaması bu gözetmenin istemcisi olmalıdır. Her UI değişikliği uzak komut olarak gönderilmeli ve sonucunu VDS olay akışından göstermelidir. Ajan peti, yerel kalp atışından değil aynı olay akışındaki gerçek ajan eylemlerinden beslenmelidir.

Ajan döngüsü sabit hedef-tara-çıkar zinciri yerine AI'nın araç kataloğundan seçim yaptığı bir çalışma alanı sunmalıdır. Araçlar arasında owner/ASN/CIDR araştırması, pasif kaynaklar, web gözlemi, Masscan liveness, dikey port keşfi, HTTP/Squid/SOCKS el sıkışmaları, gerçek hedef istekleri, kanıt kaydı ve kendini sorgulama bulunmalıdır. Teknik güvenlik sınırları korunurken hedef, port, araştırma derinliği ve bir sonraki adım AI kararına bırakılmalıdır.

## Kanıtlar

- context/PROJECT.md
- context/ARCHITECTURE.md
- docs/superpowers/specs/2026-09-04-desktop-vds-design.md
- desktop/app/vds.py
- desktop/app/store.py
- desktop/app/recall.py
- src/proxy_pipeline/otonom.py
- src/proxy_pipeline/uzak_tara.py
- ops/systemd/proxy-pipeline.service
- ops/vds/bootstrap-trixie-arm64.sh
- VDS anlık SSH gözlemi: hostname thinkpad, aarch64, masscan mevcut, iki ilgili servis inactive, çalışan PaidProxy/Masscan işi yok.
