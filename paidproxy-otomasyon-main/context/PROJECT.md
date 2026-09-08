# PaidProxy Otomasyon — Proje Tanımı

## Amaç

VDS üzerinde çalışan, AI'nin mevcut kanıtı ve araç kataloğunu değerlendirerek bir sonraki adımı seçtiği otonom proxy keşif ve doğrulama sistemi. Yerel uygulamanın görevi native masaüstü deneyimini sunmak, gerçek VDS durumunu gözlemlemek, sert müdahaleleri göndermek ve doğrulanmış sonuçları kullanıcıya teslim etmektir.

## Temel Bileşenler

1. VDS agentd: Ajan süreçlerini yaratır, çalıştırır, duraklatır, devam ettirir, sert biçimde sonlandırır ve AI runtime'ı VDS üzerinde yürütür.
2. AI karar döngüsü: Mevcut gözlemler, operatör yönlendirmeleri ve kayıtlı kanıtlar üzerinden araç ve hedef niyetini AI seçer. Boş başlangıçta araştırma, gezinme ve sentez de geçerli kararlardır.
3. Kanıt ve replay: Kararlar, araç çağrıları, çıktılar, frame'ler, video yetenek durumu ve operatör müdahaleleri ajan bazında append-only olay zincirinde görünür.
4. Native masaüstü: Ajanların canlı düşüncesini, baktığı hedefi, araç geçişlerini, yoldaş pet'ini, VDS artifact'lerini, replay'i ve VDS'den teslim edilen proxy sonuçlarını gösterir.
5. Gerçek görsel kanıt: VDS üzerinde kalıcı Sway headless Wayland çıktısı, loopback'e bağlı wayvnc, bu yüzeyden grim PNG kareleri ve wf-recorder video segmentleri kullanılır. Still capture worker'ı bloke etmeden evidence-service kuyruğundan tamamlanır; video tamamlanmaları worker olayına bağlı kalmadan completion journal üzerinden yayınlanır. Operatör canlı görünümü sınırlı lease ile yenilenir ve display_release ile bırakılır. Fiziksel monitör veya soyut/hash kare kaynak sayılmaz; yığın yoksa durum görünür biçimde kullanılamaz kalır.

## Çalıştırma Arayüzü

- Tauri masaüstü uygulaması ajan yaratma, izleme, yönlendirme, duraklatma, devam ettirme, sert sonlandırma ve yok etme işlemlerini sağlar.
- services/agentd tek operasyon otoritesidir. VDS erişilemezse yerel tarayıcı, yerel AI veya yerel proxy operasyonu devreye girmez.
- Proxy teslimi yalnız VDS üzerinde kalıcı L7 ve çıkış kanıtı bulunan, AI'nin nitel değerlendirmesi ve gerekçesiyle yayımlanan kayıtların yerel uygulamaya aktarılmasıyla yapılır.
- Yerel canlı görüntü isteği, VDS'deki yalnız loopback wayvnc servisine SSH forward açar; wayvnc VDS'de herkese açık porta bağlanmaz.

## Orkestrasyon Politikası

Karar ve planlama paidproxy ChatGPT Project'indeki ChatGPT tarafından yapılır. Codex yalnızca alınan planı mevcut çalışma alanında uygular; başka proje veya çalışma alanına geçmez, plan dışında mimari karar üretmez.
