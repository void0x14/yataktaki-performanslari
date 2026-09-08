# Mimari ve Sistem Tasarımı

## Dinamik VDS agentd modeli

    VDS kanıtı + operatör müdahalesi + araç kataloğu
                         |
                         v
    AI kararı: araştır / gözlemle / gezin / sentezle / tara / doğrula / teslim et
                         |
                         v
    AI'nin seçtiği araçlar VDS üzerinde çalışır
                         |
                         v
    Değişmez olay + çıktı + frame/video/artifact referansları
                         |
                         +----> aynı kanıtla AI yeniden değerlendirmesi

Bu modelde önceden belirlenmiş anlamlı aşama sırası, sabit hedef listesi, sabit port ailesi veya sabit kalite puanı yoktur. Teknik kaynak, süre, eşzamanlılık ve güvenlik sınırları korunur; araştırma ve seçim kararı AI'ye aittir.

## Sahiplik sınırı

- services/agentd/ VDS üzerindeki tek operasyon sahibidir: AI runtime, ağ araçları, L7 doğrulama, kanıt, replay ve yayınlama burada çalışır.
- cockpit/ yalnız Tauri arayüzü, kullanıcı komutları, artifact önbelleği ve VDS'den yerel teslim katmanıdır.
- Yerel tarafta tarayıcı, AI ajanı, masscan, socket genişletmesi veya proxy doğrulama fallback'i çalışmaz.
- VDS bağlantısı kesilirse uygulama durumu belirsizliği görünür kılar; sahte ilerleme üretmez.

## Görünürlük ve müdahale

Her ajan için pet, canlı düşünce, karar, araç başlangıcı/sonu, kanıt, çıktı, frame, video yeteneği, replay ve operatör yönlendirme geçmişi saklanır. Hard pause, resume ve hard kill mevcut süreç grubuna uygulanır. Metin yönlendirmesi append-only mailbox üzerinden ajanın bir sonraki AI kararına aktarılır.

## Gerçek VDS görsel kanıtı

paidproxy-evidence.service, VDS üzerinde WLR_BACKENDS=headless ile kalıcı bir Sway oturumu açar. Ajanların gerçek olay alanı bu Wayland yüzeyindeki terminale yazılır; grim aynı çıktıyı PNG olarak alır, wf-recorder çalışan yüzeyin video segmentlerini üretir ve wayvnc yalnız VDS loopback üzerinde canlı izleme sağlar. Masaüstü, canlı izlemeyi SSH local-forward ile açar; kare/video artifact'lerini yine VDS'den alır. Bu zincir fiziksel monitör, soyut frame veya hash görseliyle ikame edilemez. Sway/Wayland/wayvnc/grim/wf-recorder yoksa sistem yetenek hatasını yayınlar ve sahte kanıt üretmez.

Kare alma worker içinde yapılmaz: worker event'ini günceller ve evidence service'in bounded still-capture kuyruğuna bırakır. Kuyruk öğesi event_id/render_revision ile gerçek Sway surface -> render acknowledge -> grim zincirinden geçer; immutable frame provenance completion journal'a yazılır. Video kaydı evidence service'in ayrı video-owner lease'iyle yüzeyi rezerve eder; yalnız durdurulmuş, boyutu doğrulanmış ve provenance sidecar'ı yazılmış wf-recorder segmenti durable video ref olur. Seçili ajan canlı görünümü aynı yüzey seçimini kullanır.

Evidence service üç görünüm niyetini ayrı tutar: operator-selected-agent, capture-request-agent ve bounded video-lease-agent. Video lease'leri evidence service tarafından adil sırayla verilir; biten lease aynı ajanı bekleyen başka ajanlar varken hemen yeniden alamaz ve uzun worker çağrılarında demand service tarafından canlı tutulur. Operatör seçimi önce pending request olarak finalize/commit/render edilir; sınırlı TTL ile yenilenebilir, display_release ile bırakılır ve yüzeyi pasif kuyruğun altından korur. Bir worker duraklatılır veya sert öldürülürse supervisor lease revoke acknowledgement alır, finalize edilen kanıtı completion journal'dan state'e taşır ve ancak sonra süreci dondurur.

## Proxy kanıt zinciri

AI önce uygun hedefi ve protokol niyetini seçer. VDS runtime L7 el sıkışmasını ve gerçek HTTP(S) hedefinden çıkışı kanıtlar. Yayınlama, yalnız aynı ajana ait validation referansında host, port, protokol ve egress kanıtı eşleşiyorsa gerçekleşir. Kalite sınıflandırması AI etiketi ve gerekçesi olarak saklanır; deterministik skor kullanılmaz.

## Dizin Yapısı

- src/ : mevcut çekirdek domain ve uyumluluk bileşenleri
- services/ : VDS agentd, worker, supervisor ve protokol
- cockpit/ : native masaüstü, remote state, artifact ve sonuç teslimi
- config/ : teknik kaynak, capture ve retention sınırları
- reports/ : araştırma anlık görüntüleri
- specs/ : uygulama teknik şartnameleri
- context/ : kalıcı proje, mimari ve karar dokümanları
- backlog/ : tamamlanmamış görev ve durum takibi
