# PaidProxy Otonom Avcı ve Doğrulama Motoru — İnşaat ve Operasyon Planı (Agent-Agnostic)

> **Bu Belgenin Amacı:** Bu dosya, herhangi bir yapay zeka modelinin (Claude, GPT, Gemini, DeepSeek vb.) veya insan geliştiricinin oturum koptuğunda ya da kota dolduğunda hiçbir bağlam kaybı yaşamadan projeyi kaldığı yerden devam ettirmesini sağlayan **kendi kendine yeten (self-contained) teknik inşaat ve icra planıdır.**

---

## 1. Projenin Temel Misyonu ve Değişmezleri (Invariants)

1. **Nihai Çıktı:** Dışarıya çıkışı (egress IP) doğrulanmış, satılabilir HTTP CONNECT ve SOCKS5 proxy listesi (`var/proxies/live_proxies.jsonl`).
2. **Yan Çıktı (Saha Verisi):** VDS üzerinde gerçekleşen her arama, karar, terminal çıktısı ve video kaydını içeren multimodal eğitim veri seti (`var/datasets/`).
3. **Kalıcı Kural:** Asla `/24` subnetine sıkışıp kalma; hedef BGP anonsuna göre dinamik pilot ısırık (`sampling`) atılır, damar bulunursa bütün anons edilen prefix'e yayılınır.
4. **Hız/Timeout Kuralı (`docs/masscan-hiz-ve-timeout.md`):**
   - Socket timeout tabanı: `timeout >= 1.0s` (tercihen 1.5s), her porta 2 deneme.
   - Masscan hızı: `--rate 5000 --wait 3` (büyük bloklarda 2500-4000 pps).
5. **Mükerrer Tarama Yasağı:** Taranan her ASN, CIDR ve port kalıcı deftere (`ledger`) yazılır; yeni BGP prefix'i gelmedikçe aynı aralığa tekrar gidilmez.

---

## 2. Mimari Bileşenler ve Dosya Haritası

```
paidproxy-otomasyon-main/
├── services/agentd/
│   ├── ai_runtime.py       # Ajanın ana döngüsü, karar motoru ve araç yöneticisi
│   ├── fast_triage.py      # [YENİ] 1000 eşzamanlı soket ile asenkron L7 triage ve nötr egress motoru
│   ├── recon.py            # [YENİ] BGP prefix sorguları, PTR desen analizcisi, ASN komşulukları
│   ├── observer.py         # Deterministik doğrulama kapısı ve süreç bekçisi (watchdog)
│   ├── supervisor.py       # Ajan yaşam döngüsü, HTTP API ve olay yayıncısı
│   └── worker.py           # Ajan sürecini başlatan CLI sarmalayıcısı
├── config/hunt/
│   └── av-defteri.txt      # Operatör sezgileri, port kokuları ve tarihi tecrübeler
├── var/
│   ├── agentd/             # Ajan çıktıları, kanıtlar ve olay kütüğü
│   └── proxies/
│       └── live_proxies.jsonl # [HEDEF] Doğrulanmış satılabilir proxy'lerin ana kasası
├── tests/unit/
│   ├── test_fast_triage.py # [YENİ] Asenkron port triage birim testleri
│   └── test_recon.py       # [YENİ] İstihbarat ve BGP çekim birim testleri
└── cockpit/                # Tauri + Vite masaüstü yönetim paneli
```

---

## 3. Adım Adım İnşaat Yol Haritası (İlerleme Durumu)

### FAZ 1: Asenkron Port Triage ve Nötr Egress Motoru (P0 - Acil)
- [ ] **Adım 1.1:** `services/agentd/fast_triage.py` modülünün yazılması.
  - *İşlevi:* Masscan'den dönen 1 veya 3.000 portluk açık port listesini alır; `asyncio` ile 1000 eşzamanlı sokette 1.5s timeout ile HTTP CONNECT ve SOCKS5 el sıkışması yapar.
  - *Egress Doğrulama:* Başarılı el sıkışmalara anında `1.1.1.1/cdn-cgi/trace` veya `api.ipify.org` üzerinden nötr dış IP doğrulaması atar.
  - *Çıktı:* Doğrulanmış vekilleri anında `var/proxies/live_proxies.jsonl`'e ekler.
- [ ] **Adım 1.2:** `tests/unit/test_fast_triage.py` birim testlerinin yazılması ve çalıştırılması.
  - *Doğrulama Komutu:* `pytest tests/unit/test_fast_triage.py`
- [ ] **Adım 1.3:** `services/agentd/ai_runtime.py` içine entegre edilmesi:
  - Eski senkron tekil `_validate_proxy` kilitlerinin kaldırılması; Masscan sonuçlarının doğrudan `fast_triage` motoruna verilmesi.

### FAZ 2: BGP/PTR İstihbarat ve Dinamik Keşif Sensörleri (P1)
- [ ] **Adım 2.1:** `services/agentd/recon.py` modülünün yazılması.
  - *İşlevi:* RIPE Stat API (`stat.ripe.net/data/announced-prefixes`) ile hedef ASN'in tüm prefix'lerini toplar; PTR desenlerini analiz eder; hedef öncelik kartı üretir.
- [ ] **Adım 2.2:** `ai_runtime.py` karar promptunun güncellenmesi:
  - Ajana gerekçeli hipotez kontratının zorunlu kılınması (`target_cidr`, `why`, `initial_port`).
  - Statik `/24` yerine dinamik pilot ısırık (sampling) stratejisinin bağlanması.
- [ ] **Adım 2.3:** Kalıcı Tarananlar Defteri (`Ledger`) ile mükerrer taramanın engellenmesi.

### FAZ 3: Saha Verisi ve Multimodal Kayıt Motoru (P1)
- [ ] **Adım 3.1:** VDS üzerinde Sway oturumunu arka planda kesintisiz H.264 MP4 olarak kaydeden ve olay zaman damgalarıyla eşleştiren servisin entegrasyonu.
- [ ] **Adım 3.2:** Karar (Thought) + Terminal Çıktısı (PTY) + Egress Çıktısı (Reward) veri formatının derlenmesi.

### FAZ 4: Cockpit Telemetri ve C2 Entegrasyonu (P2)
- [ ] **Adım 4.1:** Cockpit içindeki Base64 JSON polling'in temizlenmesi; yerine doğrudan hafif telemetri HUD'ı ve isteğe bağlı noVNC akışının bağlanması.
- [ ] **Adım 4.2:** Operatör acil müdahale (Preemptive Interrupt) sinyalinin bağlanması.

---

## 4. Bir Sonraki Ajan / Geliştirici İçin Acil Eylem Kılavuzu

Eğer bu oturum kesilirse veya yeni bir ajan olarak bu dosyayı okuyorsan:
1. `git log -n 3` komutuyla en son yapılan commiti gör.
2. Yukarıdaki **3. Adım Adım İnşaat Yol Haritası** tablosundaki ilk `[ ]` işaretli adıma odaklan.
3. İlgili modülü yaz, birim testini koştur, ardından git commit yapıp bir sonraki adıma geç.
