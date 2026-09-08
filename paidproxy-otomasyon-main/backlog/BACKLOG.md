# Proje Birikim Listesi (Backlog)

## Harness egemenliği (Luna / ChatGPT Desktop)
Durum: Araştırma + şartname bitti; yerel montaj kesimi ayrı oturum

### Hedef
Otonom yürütücü, operatör emrini `developer` kanalında taşısın. ChatGPT Desktop executor olmasın.

### Tamamlananlar
- Sohbet + jsonl + ikili string tablosu: `reports/2026-09-08-chatgpt-harness-instruction-usurpation.md`
- Şartname: `specs/operator-harness-sovereignty.md`
- ADR-003, AGENTS.md 4b

### Kalanlar
- Beyin SessionStart’ın “Alınan Kararlar” bloğunu developer’a basmasını kes (Void0x14OS kancası).
- `~/.codex/instruction-guard.py` kaldır.
- Executor’ı ürün dışına al; ilk istek gövdesini kaydet.

### İlgili
- spec: `specs/operator-harness-sovereignty.md`
- reports: `reports/2026-09-08-chatgpt-harness-instruction-usurpation.md`

---

## 0. 24 saat — ilk satılabilir teslim
Durum: Devam ediyor

### Hedef
Ajan CIDR sormadan avlanır (bak → ilk port → canlılık → dikey genişle → çıkış). Kokpit izler; doğrulananlar `var/teslim/` yazar.

### Tamamlananlar
- Araştırma: `reports/2026-09-08-24saat-musteri-hazirlik-arastirmasi.md`
- Avcı ruhu: `.codex/skills/hunter-soul/SKILL.md`
- Temel: `specs/hedef-ve-ilk-port.md`
- Teslim: `specs/24saat-ilk-satis.md`
- Kokpit gözlem omurgası mevcut.
- Sahiplik / kardeş / masscan / dikey / L7 araçları yazılı, faz kilidiyle kopuk.

### Kalanlar
- Av fazı: sahiplik+kardeş+av host açık; example.com kapalı; 1.1.1.1 önyükleme yok.
- İlk port sözleşmesi + küçük execute (intent_ready uyumaz).
- Canlı sonrası dikey genişleme → doğrula → yayın.
- Kokpit: neden, ilk port, liste, export, resume.
- Av defteri: operatör konuşması her kararda okunur.

### Engelleyiciler / bilinmeyenler
- VDS/agentd/echo şu anda ayakta mı (08-09 araştırmasında yeniden yoklanmadı).

### Önemli kısıtlamalar
- `/16`+ ve rastgele evren taraması yok.
- Operatörden CIDR istenmez.
- Alıcı mağazası / ödeme yok.

### Önerilen sonraki eylem
- `hedef-ve-ilk-port.md` uygula: faz kilidini av döngüsüne çevir.

### İlgili
- spec: `.codex/skills/hunter-soul/SKILL.md`, `specs/hedef-ve-ilk-port.md`, `specs/24saat-ilk-satis.md`
- reports: `reports/2026-09-08-24saat-musteri-hazirlik-arastirmasi.md`
- branch/commit: `5bcb578`

---

## 1. Ölçü Kanıtı ve Gölge Kapısı Doğrulaması
Durum: Duraklatıldı (24s satış sonrasına)

### Hedef
Bir haftalık işin bir saatte çıktığını sayılarla ve en az 5 gerçek tarihsel kararla kanıtlamak.

### Tamamlananlar
- Temel pipeline, L4 masscan entegrasyonu ve L7 handshake testleri hazır (98 test geçti).
- Hedef avcısı + gezgin tur tohumlama mimarisi çalışır durumda.

### Kalanlar
- En az 5 gerçek tarihsel kararın değerlendirme kümesine yazılması.
- Gölge kapısının doğrulanması.

### Engelleyiciler / bilinmeyenler
- Tarihsel karar kayıtlarının aktarımı.

### Önemli kısıtlamalar
- Parola ve hassas kimlik bilgileri diske yazılmaz, yalnız bellekte tutulur.

### Önerilen sonraki eylem
- İlk satılabilir teslimden sonra; 24 saat sprintini bloklamaz.

### İlgili
- spec: `specs/`
- reports: `reports/`
- branch/commit: `HEAD`

---

## 2. Geniş Tarama İzin Politikası Daraltması
Durum: Engellendi

### Hedef
Canlı geniş tarama politikası daraltılmadan ve kuru komut (dry-run) onaylanmadan canlı geniş taramaya izin verilmemesi.

### Tamamlananlar
- Kuru çalıştırma (dry-run) desteği mevcut.

### Kalanlar
- Araç yürütme politikasının netleştirilmesi.

### Engelleyiciler / bilinmeyenler
- Manifest hedeflerinin netleştirilmesi.

### Önemli kısıtlamalar
- Manifest hedefleri görünür olmadan kontrolsüz tarama başlatılamaz.

### Önerilen sonraki eylem
- Eski allow/deny wiring kalıntıları gözden geçirilecek.
