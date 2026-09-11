# Görev Planı: Otonom Avcı (10 Yapı Taşı), Saha Verisi Hasadı ve C2 Mimarisi

> **Referans Şartname:** [specs/otonom-avci-ve-saha-verisi-mimarisi.md](file:///home/void0x14/Belgeler/paidproxy-otomasyon-main/specs/otonom-avci-ve-saha-verisi-mimarisi.md)

---

## 1. Temel Hedefler
1. Ajanı sabit `/24` ve senkron tekil port prangasından kurtarmak; 10 yapı taşını harfiyen yürüten esnek, dinamik ve zeki bir avcıya dönüştürmek.
2. 3.105 sahte port tuzağını ve senkron beklemeyi yok eden 1000 eşzamanlı asenkron port triage motorunu (`fast_triage.py`) devreye almak.
3. LLM'e BGP prefix, PTR ters DNS ve ASN istihbarat sensörlerini (`recon.py`) vererek körü körüne tahmin yerine nokta atışı gerekçeli hipotez kurmasını sağlamak.
4. VDS üzerinde kesintisiz H.264 video kaydı + State-Action-Reward veri seti derleyicisini (Multimodal Saha Verisi Fabrikası) kurmak.
5. Cockpit'te canlı ekranı Base64 JSON IPC'den ayırıp noVNC/WebSocket ile isteğe bağlı hale getirmek ve öncelikli müdahale (preemptive interrupt) eklemek.

---

## 2. Görev Dağılımı ve Yol Haritası

### Faz 1: Asenkron Port Triage & Nötr Egress Doğrulama (P0 - Acil)
- [ ] **Görev 1:** `services/agentd/fast_triage.py` oluştur:
  - 1000 eşzamanlı soket (`asyncio`), `timeout >= 1.0s` (tercihen 1.5s), her porta 2 deneme (`docs/masscan-hiz-ve-timeout.md` standardı).
  - L7 HTTP CONNECT ve SOCKS5 el sıkışma sondası.
  - `1.1.1.1/cdn-cgi/trace` ve `api.ipify.org` üzerinden nötr egress doğrulaması (sıfır ban riski).
  - Doğrulanan proxy'lerin anında `var/proxies/live_proxies.jsonl`'e yazılması.
  - *Doğrulama:* `python3 -m unittest tests/unit/test_fast_triage.py` ile sahte portların saniyeler içinde elendiğini ve gerçek vekillerin kasaya yazıldığını test et.
- [ ] **Görev 2:** `services/agentd/ai_runtime.py` güncelle:
  - Tekil senkron `validate_proxy` zorunluluğunu ve `open_ports_to_validate` kilitlerini kaldır.
  - Masscan'den dönen port kümesini doğrudan `fast_triage` motoruna devret ("port genleme").
  - *Doğrulama:* Ajanın binlerce portluk bir hedefte kilitlenmeyip 2 saniyede gerçek portlara indiğini simüle eden birim test yaz ve çalıştır.

### Faz 2: İstihbarat & Keşif Katmanı (Grounded Recon) (P1)
- [ ] **Görev 3:** `services/agentd/recon.py` oluştur:
  - RIPE Stat BGP prefix sorguları (`stat.ripe.net`), PTR ters DNS örnekleme ve ASN komşuluk çıkarımı.
  - `myip.ms` arama ve önceliklendirme süzgeci (DC kovanı -> uzun ömürlü DC/Res -> 4G/5G Mobil).
  - *Doğrulama:* `python3 -c "import services.agentd.recon as r; print(r.recon_bgp_context('AS209207'))"` komutunun gerçek prefix listesini döndürdüğünü doğrula.
- [ ] **Görev 4:** `ai_runtime.py` avcı karar promptunu güncelle:
  - `config/hunt/av-defteri.txt` sezgilerini her kararda dinamik enjekte et.
  - Sabit `/24` kısıtlamasını kaldır; pilot ısırık (sampling) ve tüm prefix'e genişleme mantığını bağla.
  - Taranan bloklar muhasebesini (Ledger) ekleyerek mükerrer (duplicate) taramayı tamamen engelle.
  - *Doğrulama:* Test harness ile kararların dayanaksız değil, recon verisi ve koku referanslı üretildiğini teyit et.

### Faz 3: Saha Verisi & Davranış Kaydı Motoru (P1)
- [ ] **Görev 5:** `services/agentd/dataset_recorder.py` oluştur:
  - Sway ekranını `wf-recorder` ile arka planda 720p 15fps H.264 MP4 olarak kaydeden servis.
  - Olayları (State + Prompt + Thought + Action + PTY I/O + Outcome + Reward) JSONL olarak eşleştiren trajectory kaydedici.
  - *Doğrulama:* VDS üzerinde test kaydı al; üretilen `.mp4` ve `trajectory.jsonl`'in senkron olduğunu doğrula.

### Faz 4: Cockpit C2 & noVNC Ayrıştırması (P2)
- [ ] **Görev 6:** VDS'te `wayvnc` arkasına `websockify` ekle; Cockpit (Tauri/Vite) içine sadece "VDS Canlı Ekran" sekmesinde çalışan hafif `noVNC` bağla (Base64 JSON polling'i kaldır).
  - *Doğrulama:* Cockpit açıldığında arka planda JSON IPC trafiğinin sıfıra indiğini ve CPU tüketiminin düştüğünü doğrula.
- [ ] **Görev 7:** Ajan sürecine öncelikli `CancelToken` / Interrupt soketi bağla; operatör direktif verdiğinde anlık soket görevinin milisaniyede kesilmesini sağla.
  - *Doğrulama:* Cockpit'ten "DUR" butonuna basıldığında ajanın hemen durduğunu loglardan gör.

### Faz X: Nihai Canlı Doğrulama (Verification)
- [ ] **Görev 8:** Canlı VDS üzerinde temiz bir av başlat:
  - İstihbarat toplanacak,
  - Gerekçeli hedef seçilecek (pilot ısırık ile damar aranacak),
  - Asenkron triage ile saniyeler içinde taranacak ve genlenecek,
  - Doğrulanmış proxy'ler `var/proxies/live_proxies.jsonl`'e düşecek,
  - Arka planda `screen.mp4` ve `trajectory.jsonl` veri seti eksiksiz üretilecek.
