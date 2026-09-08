# PaidProxy VDS Operasyon Merkezi Tasarımı

Tarih: 2026-09-05
Durum: Uygulama için kabul edilmiş tasarım
İncelenen alan: paidproxy-otomasyon-main içindeki native desktop ve VDS operasyon omurgasının yeniden kurulması.

## 1. Hedef

Yerel makine yalnızca native masaüstü uygulamasını, kaynak kodu, gözlem önbelleğini ve teslim edilen proxy sonuçlarını barındırır. Keşif, owner/range araştırması, web gözlemi, AI ajan döngüsü, port taraması, L7 doğrulama, ekran/video kaydı ve kalıcı iş yönetimi VDS üzerinde çalışır.

Başarı, masaüstünün gösterişli görünmesiyle değil; kullanıcının canlı ajan davranışını görmesi, herhangi bir işi VDS'de gerçekten durdurabilmesi ve VDS'de protokol + gerçek hedef kanıtı bulunan proxy teslimatı almasıyla ölçülür.

## 2. Mimari karar

### VDS: operasyon sahibi

VDS'de kalıcı paidproxy-agentd gözetmeni çalışır. Gözetmen:

- ajan ve iş kayıtlarını VDS'de kalıcı tutar;
- her ajanı gerçek child process ve process-group/cgroup kimliğiyle çalıştırır;
- oluşturma, başlatma, duraklatma, devam, sert sonlandırma ve yok etme komutlarını uygular;
- append-only olay günlüğü, ajan çalışma notları, ekran kareleri ve video parçaları üretir;
- masaüstü yeniden bağlandığında olayları sıra numarasından devam ettirir;
- sert sonlandırılmış işi kendiliğinden yeniden başlatmaz;
- supervisor yeniden başlasa bile terminal ajan durumunu korur.

Gözetmen yalnızca VDS loopback üzerinde dinler. Masaüstü erişimi SSH port-forward üzerinden sağlanır; public kontrol API'si açılmaz.

### Yerel: operasyon konsolu

PySide6 masaüstü:

- VDS bağlantısını ve worker sağlığını gösterir;
- uzak ajan listesini ve her ajanın petini gösterir;
- gerçek viewport, olay akışı, çalışma notu, hedef ve araç bilgisini canlı gösterir;
- komutları VDS gözetmenine yollar;
- geçmiş olay/video kayıtlarını VDS'den alır;
- yalnızca sonuç teslimi için yerel çıktı oluşturur;
- yerel tarama, yerel AI ajanı veya yerel operasyon worker'ı başlatmaz.

## 3. Uzak komut ve olay sözleşmesi

Masaüstü ile gözetmen newline-delimited JSON mesajları kullanır.

Komutlar: status, create, start, pause, resume, hard_kill, destroy, subscribe, replay, viewport.

Her olay en az şu alanları taşır:

- seq, event_id, timestamp;
- agent_id, job_id, pid, process_group;
- state, event_type, tool, target;
- working_note, hypothesis, counter_hypothesis;
- evidence_refs, decision, next_action;
- output_ref, frame_ref, video_ref;
- operator_action ve hata bilgisi.

Gizli ham model zinciri yerine kullanıcının denetleyebileceği gerçek çalışma notu, hipotez, kanıt ve karar gerekçesi yayınlanır. Çalışıyor heartbeat'i gerçek araç olayı olmadan üretilemez.

## 4. Ajan çalışma alanı

Her VDS ajanı dinamik araç kataloğuna erişir:

- owner/ASN/CIDR ve IP range araştırması;
- RIR/RDAP, BGP, IRR, RPKI, reverse DNS;
- yetkili web gözlemi ve myip.ms benzeri sayfa incelemesi;
- pasif altyapı sinyalleri;
- Masscan ile liveness;
- AI'nın seçtiği yüksek port ve port aralıkları;
- canlı IP üzerinde dikey port keşfi;
- HTTP forward/CONNECT, Squid davranışı;
- SOCKS4/4a/5 handshake;
- egress IP ve header davranışı;
- gerçek hedef site istekleri;
- gecikme, hata, TLS ve erişilebilirlik kanıtı;
- benzer aday karşılaştırması;
- hipotez/karşı hipotez ve yeniden değerlendirme.

8080, 3128 ve 1080 sabit varsayılan akış değildir. Port seçimi AI kararının parçasıdır; 1-65535 teknik evreni içinde dinamik yüksek port dilimleri seçilebilir. L4 açık sonucu tek başına proxy sonucu sayılmaz.

Ajan boş gezinme modunda kaynakları ve değişimleri izler, kendi hipotezini sınar, yanlış yönü açıklar, bilgi kazanımı düşükse bekleme veya yön değiştirme kararı üretir. Bu davranış sabit if/else listesiyle yazılmaz.

Her proxy iddiası, protokol davranışı + gerçek hedef isteği + egress sonucu + zaman damgalı kanıtla birlikte saklanır. Proxy türü kanıtın desteklediği kadar ifade edilir; residential/rotate gibi nitelikler yalnızca ilgili ağ ve egress kanıtı varsa gösterilir.

## 5. Pet ve görünürlük

Ajan oluşturulurken pet kimliği VDS'de atanır ve olay akışında saklanır. Masaüstündeki pet:

- araştırma, tarama, bekleme, hata, karar ve sert müdahale olaylarına tepki verir;
- yerel timer heartbeat'inden sahte ruh hali üretmez;
- ajanla birlikte geçmişteki durumlarını oynatabilir;
- kullanıcı pet üzerinden de sert müdahale edebilir.

## 6. Recall ve video

VDS her ajan için:

- viewport kareleri;
- olay zaman kodları;
- sıkıştırılmış video segmentleri;
- oturum manifesti;
- olaydan kareye ve kareden olaya bağlantı

üretir. Masaüstü canlı video akışını ve geçmiş zaman çizelgesini açar. Yerel ekran kaydı yalnızca operatörün masaüstü ekranı içindir; ajan çalışma kaydının yerine geçmez.

## 7. Kalıcılık ve sonuç teslimi

VDS'de SQLite ve append-only dosya kayıtları iş, olay, kanıt ve sonuçların sahibi olur. Desktop yeniden açıldığında VDS'deki gerçek durumu tekrar okur.

Yerel sonuç teslimi ancak şu kanıtlar eksiksizse yapılır:

- gerçek uzak ajan kimliği;
- gerçek VDS proses bilgisi;
- canlılık ve port kanıtı;
- protokol handshake;
- gerçek hedef istek sonucu;
- egress/latency/error kaydı;
- kaynak ve zaman damgası;
- ajan karar gerekçesi.

## 8. Sert müdahale sözleşmesi

hard_kill:

1. komutu olay günlüğüne yazar;
2. uzak process group/cgroup'a SIGTERM gönderir;
3. kısa sonlandırma penceresi sonunda kalan alt prosesleri SIGKILL ile bitirir;
4. PID'nin gerçekten yok olduğunu doğrular;
5. işi terminal killed durumuna alır;
6. ekran ve olay kayıtlarını korur;
7. otomatik restart yapmaz.

destroy, yalnızca durdurulmuş veya öldürülmüş işi görünür geçmişi bozmadan aktif listeden kaldırır. Kanıt dosyaları sessizce silinmez.

## 9. Native desktop yerleşimi

Sol: VDS ajan filosu, gerçek durum, pet ve PID.

Orta: canlı uzak viewport, çalışma notu, hipotez/kanıt ve olay zaman çizelgesi.

Sağ: hedef/range/port matrisi, kullanılan araçlar, sonuçlar, video geçmişi ve operasyon komutları.

Üst sağlık çubuğu: VDS bağlantısı, supervisor, event stream, video akışı ve aktif iş sayısı. Sert müdahale düğmesi her ajan için görünür ve anında erişilebilirdir.

## 10. Uygulama sırası

1. VDS kalıcı gözetmen ve gerçek process yaşam döngüsü.
2. SSH port-forward + desktop uzak komut istemcisi.
3. append-only event stream ve replay.
4. gerçek pet olay bağlama.
5. VDS viewport/kare/video akışı.
6. AI tool registry ve çok adımlı ajan döngüsü.
7. VDS Masscan, dikey port ve L7/gerçek hedef kanıt zinciri.
8. sonuç teslimi, yeniden bağlanma ve gerçek çalışma kabulü.

Her adım önceki sahte yerel davranışı kaldırır veya gerçek uzak davranışla değiştirir. Birim testleri kabul ölçütü değildir; kabul kanıtı canlı VDS prosesi, gerçek olay akışı, gerçek müdahale ve gerçek proxy kanıtıdır.
