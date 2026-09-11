# Otonom Avcı, Saha Verisi Hasadı ve C2 Mimarisi Şartnamesi

## 1. Büyük Resim ve Hedef

Bu sistem yalnızca internetten rastgele proxy toplayan bir araç değildir. Sistem iki temel ve yüksek katma değerli varlık üretir:

1. **Doğrulanmış, Satılabilir PaidProxy Havuzu:**
   - Dışarıya çıkışı (egress IP), protokolü (HTTP CONNECT / SOCKS5), anonimliği ve gecikmesi nötr uç noktalardan teyit edilmiş vekil sunucular.
2. **Saha Davranışı Veri Seti (Ground-Truth Agent Behavioral Dataset):**
   - Bir otonom ajanın gerçek dünya işletim sisteminde (Linux / Sway / Terminal / Ağ Araçları) yaptığı her keşif, karar, hata, düzeltme ve terminal etkileşiminin; **zaman damgalı ekran kaydı (video/frame) + LLM düşünce/karar izi + OS girdi/çıktısı (PTY) + ağ paketleri** ile multimodal bir eğitim setine dönüştürülmesi.
   - Bu veri; tescilli modellerin fine-tuning edilmesinde, ajanın kendi kendine öğrenmesinde (distillation/RL) ve operatörün kendi tersine mühendislik bilgi setini güçlendirmesinde kullanılır.

---

## 2. Hariç Tutulanlar (Non-Goals)

- Körü körüne, rastgele `/24` subnetlerine 8 port sıkıp bekleyen "script-kiddie" kaba kuvvet (brute-force) taraması.
- Tek bir IP üzerindeki sahte/firewall portlarında (ör. 3.105 port) saatlerce kilitlenip kalan senkron döngüler.
- Canlı ekran akışını saniyede onlarca megabaytlık Base64 PNG stringleri olarak JSON IPC içine gömüp Tauri'yi ve ağı kilitlemek.
- Proxy'leri Netflix, Google gibi hızla banlanan veya hedef odaklı platformlarda ilk doğrulamaya sokup false-negative üretmek.

---

## 3. Mevcut Durum ve Kırılma Noktaları

| Bileşen | Mevcut Durum | Neden Kırıldı? |
| :--- | :--- | :--- |
| **Keşif Katmanı (Recon)** | Sadece 3 bayat IP ve kısıtlı RDAP/Masscan | İstihbarat sensörü (BGP, PTR, JARM) yok; LLM veri olmadan "götten sallamak" zorunda kaldı. |
| **Port Doğrulama (Triage)** | `ai_runtime.py` içinde senkron `validate_proxy` çağrıları | Prompttaki katı kural yüzünden tek bir modemdeki 3.105 sahte porta tek tek 7 sn harcandı (6 saat kilitlendi). |
| **Görselleştirme (Cockpit)** | Sway -> `grim` (PNG) -> Base64 -> JSON -> Tauri IPC | Her saniye megabaytlarca JSON üretildi; arayüz dondu, operatör müdahaleleri (interventions) kayboldu. |
| **Saha Verisi Kaydı** | Parçalı PNG ekran görüntüleri ve şişen `events.jsonl` | Düzenli video (H.264), multimodal eğitim verisi ve aksiyon-gözlem zinciri halinde paketlenmedi. |

---

## 4. İstenen Mimari (4 Temel Sütun)

### Sütun I: Keşif & İstihbarat Katmanı (Grounded Reconnaissance)
LLM'in görevi rastgele tahmin yürütmek değil; gerçek dünya telemetrisinden **örüntü yakalamak ve nokta atışı hipotez kurmaktır**.

1. **İstihbarat Sensörleri (Recon Tools):**
   - `recon_bgp_context(asn)`: Hedef ASN'in anons ettiği prefix'leri, upstream sağlayıcılarını ve komşu AS'leri çeker (`stat.ripe.net`, `bgp.he.net`).
   - `recon_ptr_patterns(cidr)`: Hedef bloktaki ters DNS (PTR) kalıplarını örnekler (`pool-*.datacenter.com`, `dyn-*.isp.net`, `gateway-*`).
   - `recon_cert_jarm(host, port)`: Karşı tarafın TLS el sıkışma parmak izini (JARM/JA3) ve SSL Subject/SAN alanlarını çıkarır (Squid, Envoy, 3proxy imzaları).
2. **Gerekçeli Hipotez Protokolü:**
   - Ajan Masscan çalıştırmadan önce şu kontratı üretmek zorundadır:
     ```json
     {
       "target_cidr": "x.x.x.0/24",
       "intelligence_source": "PTR naming pattern shows dedicated proxy egress pool",
       "hypothesis": "Bu blokta HTTP CONNECT proxy kümesi barınıyor",
       "selected_initial_ports": [8000, 8080, 10000],
       "rationale": "Veri merkezi BGP anonsu ve PTR kayıtları Squid kümesine işaret ediyor"
     }
     ```

### Sütun II: Asenkron Port Genleme & Hızlı Triage Motoru
Tekil port doğrulaması LLM'in işi değildir; bu görev makinenin asenkron soket motoruna aittir.

1. **1000 Eşzamanlı Asenkron Triage (`asyncio` / `epoll`):**
   - Masscan'den ister 10, ister 3.105 açık port dönsün; portlar havuza atılır ve tek bir event loop ile taranır.
   - Her porta paralel olarak 300 ms zaman aşımlı **L7 protokol sondası** gönderilir:
     - HTTP Probe: `CONNECT 1.1.1.1:443 HTTP/1.1\r\nHost: 1.1.1.1:443\r\n\r\n`
     - SOCKS5 Probe: `\x05\x01\x00`
   - Firewall'lar, tarpit'ler ve sahte açık portlar 300 ms içinde elenir. 3.000 portluk sahte liste **1.5 saniye içinde** 2-3 gerçek servis portuna indirgenir ("genlenir").
2. **Nötr Egress Doğrulama:**
   - Ayıklanan portlar anında nötr ve ban riski olmayan hedeflerden test edilir:
     - `https://1.1.1.1/cdn-cgi/trace` (Cloudflare CDN egress)
     - `https://api.ipify.org?format=json`
     - Özel düşük gecikmeli VDS reflect endpoint'i.
   - Dış IP (egress IP) doğrulanır doğrulanmaz proxy anında `var/proxies/live_proxies.jsonl`'e yazılır.

### Sütun III: Saha Verisi & Multimodal Davranış Kaydı Motoru
Bu sistemin "kara kutusu" ve değer üreten veri fabrikasıdır.

1. **Kesintisiz Headless Arka Plan Kaydı (Continuous VDS Capture):**
   - VDS üzerinde `wf-recorder` (veya hafif H.264 pipe) ile Sway ekranı kesintisiz olarak 720p / 1080p, 15 FPS hızında `.mp4` olarak diske yazılır (`var/recordings/{agent_id}/screen.mp4`).
   - Saniyede 15 adet PNG üretmek yerine H.264 donanım/yazılım sıkıştırması kullanılarak disk yükü 100 kat azaltılır.
2. **State-Action-Reward Veri Eşlemesi:**
   - Her ajanın yaşam döngüsü şu veri yapısıyla kaydedilir:
     ```json
     {
       "timestamp": "2026-09-12T00:15:00.000Z",
       "video_frame_timestamp_ms": 124500,
       "prompt_context": "... (ajanın gördüğü istihbarat)",
       "llm_thought": "... (ajanın kurduğu hipotez)",
       "action_taken": "async_probe_range",
       "os_pty_output": "... (terminal çıktısı)",
       "outcome": {"egress_confirmed": true, "proxy": "x.x.x.x:8080"},
       "reward_score": 1.0
     }
     ```
   - Bu veri seti, gelecekteki lokal modelleri (Llama-3, DeepSeek, Mistral) fine-tuning ederek frontier modellerden daha uzman bir siber avcı haline getirmek için hazır tutulur.

### Sütun IV: Cockpit & Ayrık Komuta Kontrol (C2) Protokolü
Ekran izleme ile komuta kontrol kanalı birbirinden kesin çizgilerle ayrılır.

1. **Ekran Akışının Ayrıştırılması (On-Demand Stream):**
   - Ekran görüntüsü Base64 JSON üzerinden TAŞINMAZ.
   - VDS'teki `wayvnc` (5900) önüne hafif bir `websockify` yerleştirilir. Cockpit içinde `noVNC` bileşeni kullanılır.
   - Operatör Cockpit'te "Ekran / VDS Görünümü" sekmesine geçtiği anda RFB WebSocket bağlantısı açılır; pencereler kapandığında veya başka sekmeye geçildiğinde akış durur. Sıfır JSON IPC yükü, sıfır ağ şişmesi.
2. **Hafif Telemetri & PTY Akışı (Ana Dashboard):**
   - Ana ekranda canlı ekran yerine:
     - Gerçek zamanlı keşif grafiği (Bulunan ASN'ler, hedefler, canlı portlar).
     - Canlı proxy akışı (Yakalanan ve doğrulanmış vekiller anında düşer).
     - Canlı terminal akışı (`xterm.js` over WebSocket).
3. **Öncelikli Operatör Müdahalesi (Preemptive Interruption):**
   - Operatör bir direktif verdiğinde ("DUR", "HEDEFE ATLA", "BU ASN'İ GEÇ"), bu mesaj pasif bir JSON dosyasına yazılmaz.
   - Ajanın ana döngüsüne bir `asyncio.Event` / Cancellation Token sinyali gönderilir; ajan o anki soket ameleliğini derhal iptal eder ve operatörün emrini işleme alır.

---

## 5. Yapılacaklar Listesi (Uygulama Fazları)

### Faz 1: Asenkron Port Triage & Egress Doğrulama Motoru (Acil / P0)
- [ ] `services/agentd/fast_triage.py`: 1000 eşzamanlı soket ile HTTP CONNECT ve SOCKS5 el sıkışma sondasını koşturan asenkron motorun yazılması.
- [ ] `ai_runtime.py` içindeki tekil ve senkron `validate_proxy` zorunluluğunun kaldırılması; açık portların toplu olarak `fast_triage` motoruna devredilmesi.
- [ ] Nötr egress doğrulayıcısının (`1.1.1.1/cdn-cgi/trace` ve yedek endpoint'ler) entegre edilmesi ve bulunan proxy'lerin anında `var/proxies/live_proxies.jsonl`'e basılması.

### Faz 2: İstihbarat & Keşif Sensörleri (Grounded Recon) (P1)
- [ ] `services/agentd/recon.py`: BGP prefix sorguları (`stat.ripe.net`), PTR desen analizcisi ve RDAP hata toleranslı veri çekici.
- [ ] Ajan karar motoruna (`_hunter_instruction`) gerekçeli hipotez kontratının eklenmesi; LLM'in körü körüne tekil IP'lere saplanmasının engellenmesi.
- [ ] Operatörün `config/hunt/av-defteri.txt` sezgilerinin LLM'in karar anına dinamik olarak beslenmesi.

### Faz 3: Saha Verisi & Arka Plan Kayıt Motoru (P1)
- [ ] VDS tarafında Sway ekranını kesintisiz H.264 olarak kaydeden ve olaylarla (events) eşleştiren `recorder_daemon.py` servisinin yapılandırılması.
- [ ] Karar anı (LLM JSON) + Terminal I/O + Ekran zaman damgası eşleştirmesini yapan veri derleyicisinin oluşturulması (`var/datasets/agent_trajectories/`).

### Faz 4: Cockpit C2 & noVNC Ayrıştırması (P2)
- [ ] VDS'te `wayvnc` -> `websockify` köprüsünün açılması.
- [ ] Cockpit (Tauri/Vite) arayüzündeki Base64 JSON polling mantığının temizlenmesi; yerine isteğe bağlı açılan `noVNC` sekmesinin ve `xterm.js` canlı PTY konsolunun yerleştirilmesi.
- [ ] Preemptive operatör müdahale sinyalinin (Unix socket / WebSocket interrupt) bağlanması.

---

## 6. Gelecek Ufukları (Yapılabilecekler & İleri Seviye)

1. **Özel RL / SL Fine-Tuning Pipeline:**
   - Toplanan yüz binlerce adımdan oluşan saha verisiyle, ağ keşfi ve proxy sızması konusunda uzmanlaşmış 7B/14B parametreli yerel bir model eğitmek (API maliyetini sıfıra indirmek).
2. **Kendi Kendini İyileştiren Avcı Sürüsü (Swarm Intelligence):**
   - Birden fazla VDS'teki ajanların keşfettiği koku ve ASN istihbaratını ortak bir vektör bellekte (Vector DB / Knowledge Graph) paylaşarak birbirini beslemesi.
3. **Gerçek Zamanlı Proxy Satış API'si:**
   - `live_proxies.jsonl` dosyasına düşen vekillerin anında bir auth gateway'i (ör. 3proxy / Envoy) arkasına alınıp müşterilere API anahtarıyla otomatik rotasyonlu olarak kiralanması.
