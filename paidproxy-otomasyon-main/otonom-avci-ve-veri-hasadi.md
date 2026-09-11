# Görev Planı: Otonom Avcı, Saha Verisi Hasadı ve C2 Mimarisi

> **Referans Şartname:** [specs/otonom-avci-ve-saha-verisi-mimarisi.md](file:///home/void0x14/Belgeler/paidproxy-otomasyon-main/specs/otonom-avci-ve-saha-verisi-mimarisi.md)

---

## Hedefler
1. 3.105 sahte port tuzağını ve senkron beklemeyi yok eden 1000'lik asenkron port triage motorunu devreye almak.
2. LLM'e BGP/PTR/ASN istihbarat sensörleri vererek körü körüne tahmin yerine nokta atışı gerekçeli hipotez kurmasını sağlamak.
3. VDS üzerinde kesintisiz H.264 video kaydı + State-Action-Reward veri seti derleyicisini (Multimodal Saha Verisi Fabrikası) kurmak.
4. Cockpit'te canlı ekranı Base64 JSON IPC'den ayırıp noVNC/WebSocket ile isteğe bağlı hale getirmek ve öncelikli müdahale (preemptive interrupt) eklemek.

---

## Görev Dağılımı ve Yol Haritası

### Faz 1: Asenkron Port Triage & Egress Doğrulama (P0 - Acil)
- [ ] **Görev 1:** `services/agentd/fast_triage.py` oluştur: `asyncio` ile 1000 eşzamanlı sokette 300ms HTTP CONNECT ve SOCKS5 el sıkışma sondası + `1.1.1.1/cdn-cgi/trace` nötr çıkış doğrulayıcısı.
  - *Doğrulama:* `python3 -m unittest tests/unit/test_fast_triage.py` ile sahte portların 1 sn altında elendiğini ve gerçek vekillerin `live_proxies.jsonl`'e yazıldığını test et.
- [ ] **Görev 2:** `services/agentd/ai_runtime.py` güncelle: Tekil senkron `validate_proxy` zorunluluğunu kaldır; Masscan'den dönen port kümesini doğrudan `fast_triage` motoruna devret.
  - *Doğrulama:* Ajanın 3.000 portluk bir hedefte kilitlenmeyip 2 saniyede gerçek portlara indiğini simüle eden birim test yaz ve çalıştır.

### Faz 2: İstihbarat & Keşif Katmanı (Grounded Recon) (P1)
- [ ] **Görev 3:** `services/agentd/recon.py` oluştur: RIPE Stat BGP prefix sorguları, PTR ters DNS örnekleme ve ASN komşuluk çıkarımı.
  - *Doğrulama:* `python3 -c "import services.agentd.recon as r; print(r.recon_bgp_context('AS209207'))"` komutunun gerçek prefix listesini döndürdüğünü doğrula.
- [ ] **Görev 4:** `ai_runtime.py` avcı karar promptunu güncelle: `config/hunt/av-defteri.txt` sezgilerini her kararda dinamik enjekte et; ajandan "target_cidr + why + initial_ports" gerekçeli kontratı zorunlu kıl.
  - *Doğrulama:* Test harness ile kararların dayanaksız değil, recon verisi referanslı üretildiğini teyit et.

### Faz 3: Saha Verisi & Davranış Kaydı Motoru (P1)
- [ ] **Görev 5:** `services/agentd/dataset_recorder.py` oluştur: Sway ekranını `wf-recorder` ile arka planda 720p 15fps H.264 MP4 olarak kaydeden ve olayları (Prompt + Thought + Terminal I/O + Outcome) JSONL olarak eşleştiren servis.
  - *Doğrulama:* VDS üzerinde 30 saniyelik test kaydı al; üretilen `.mp4` ve `trajectory.jsonl`'in senkron olduğunu doğrula.

### Faz 4: Cockpit C2 & noVNC Ayrıştırması (P2)
- [ ] **Görev 6:** VDS'te `wayvnc` arkasına `websockify` ekle; Cockpit (Tauri/Vite) içine sadece "VDS Canlı Ekran" sekmesinde çalışan hafif `noVNC` bağla (Base64 JSON polling'i kaldır).
  - *Doğrulama:* Cockpit açıldığında arka planda JSON IPC trafiğinin sıfıra indiğini ve CPU tüketiminin düştüğünü doğrula.
- [ ] **Görev 7:** Ajan sürecine öncelikli `CancelToken` / Interrupt soketi bağla; operatör direktif verdiğinde anlık soket görevinin milisaniyede kesilmesini sağla.
  - *Doğrulama:* Cockpit'ten "DUR" butonuna basıldığında ajanın hemen durduğunu loglardan gör.

### Faz X: Nihai Canlı Doğrulama (Verification)
- [ ] **Görev 8:** Canlı VDS üzerinde temiz bir av başlat:
  - İstihbarat toplanacak,
  - Gerekçeli hedef seçilecek,
  - Asenkron triage ile saniyeler içinde taranacak,
  - Doğrulanmış proxy'ler `var/proxies/live_proxies.jsonl`'e düşecek,
  - Arka planda `screen.mp4` ve `trajectory.jsonl` veri seti eksiksiz üretilecek.
