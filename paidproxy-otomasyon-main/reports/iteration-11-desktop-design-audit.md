# Iteration 11 — Native desktop design audit

## Gerçek başlangıç bulguları

Mevcut gerçek X11 ekran görüntüsü `reports/iteration-10-artifacts/cockpit-selected-evidence.png` şu sorunları gösteriyor:

- Sol ajan alanı her ajanı çok satırlı mini-dashboard olarak render ediyor; 20+ ajan taraması için gereksiz dikey alan tüketiyor.
- Ajan rail'inde pet çizimi yerine aynı tip metin/sembol rozeti kullanılıyor; ajanlar çevresel görüşte ayırt edilemiyor.
- Seçili ajan tek generic oval yaratıkla gösteriliyor; kalıcı ajan kimliği yok.
- Gerçek kanıt önizlemesi ekranın altına sıkışıyor; VDS frame'i ve provenance okunabilir birincil yüzey olarak sunulmuyor.
- Canlı yüzey RELEASED/UNAVAILABLE durumunda doğruyu söylüyor, fakat bu durum başlı başına büyük bir boş panel; gerçek ve bekleyen durumun görsel hiyerarşisi daha açık olmalı.
- Ham UUID, event ve Python dict metni kullanıcıya dönük ana içerik gibi duruyor.
- Pause/Resume/KILL aynı ağırlıkta ve KILL bekleniyor görünümü kullanıcıya gerçek kontrol sonucu yerine kilitlenme hissi veriyor.
- 1760x1080 varsayımı ve üç eşzamanlı büyük kolon düşük çözünürlükte taşma/okunaksızlık riski yaratıyor.

## Yeni bilgi hiyerarşisi

1. Üstte kompakt global sağlık ve seçili ajan özeti.
2. Solda 48–64px kompakt, kalıcı ajan kimliği satırları.
3. Ortada seçili ajan masthead'i ve gerçek VDS/frame görseli.
4. Altında kısa, insan tarafından okunabilir Now / Looking at / Thinking / Next anlatısı.
5. Tek bir konuşma benzeri müdahale composer'ı.
6. Timeline, video ve provenance katlanabilir geçmiş çekmecesi.

## Kimlik/pet hedefi

Her ajan için agent_id'den deterministik türetilen:

- kalıcı insan okunur ad;
- en az 12 farklı özgün pet silüeti;
- simge/logo;
- sabit kimlik rengi;
- yaşam döngüsü durumundan ayrı status göstergesi.

Pet compact ve detail modunda aynı kimliği koruyacak; tıklamak yalnızca ajanı seçebilecek, hiçbir destructive komut göndermeyecek.

## Responsive hedefleri

- 1920x1080: rail + seçili çalışma alanı + görsel ağırlıklı kanıt.
- 1440x900: rail + görsel alan + aktivite bağlamı.
- 1366x768: yatay taşma olmadan ajan kimliği, seçili ajan, okunabilir gerçek kanıt, aktivite ve müdahale görünür.
- Geçmiş gerektiğinde açılıp kapanacak; ana görsel alanı kalıcı olarak sıkıştırmayacak.

## Kontrol hiyerarşisi

- Birincil: konuşma benzeri Intervene/Gönder.
- Bağlama bağlı: yalnız geçerli Pause veya Resume.
- Ayrı tehlike alanı: hard kill.
- Pending/başarısız/teslim edildi durumları gerçek backend yanıtına bağlı kalacak; sahte başarı gösterilmeyecek.

Bu rapor yalnız yerel native desktop görünümünü kapsar. VDS, ajanlar, servisler, tarama ve L7 akışına dokunulmayacaktır.
