# Otonom Avcı, 10 Yapı Taşı, Saha Verisi Hasadı ve C2 Mimarisi Şartnamesi

## 1. Büyük Resim ve Nihai Hedef

Bu sistem, interneti körü körüne tarayan bir port tarayıcı veya amatör bir scraper değildir. Sistem iki temel ve yüksek katma değerli çıktı üretmek üzere tasarlanmış **otonom bir siber istihbarat ve operasyon motorudur**:

1. **Doğrulanmış, Satılabilir PaidProxy Havuzu:**
   - Dışarıya çıkışı (egress IP), protokolü (HTTP CONNECT / SOCKS5), anonimliği ve gecikmesi nötr uç noktalardan teyit edilmiş, anında satılabilir/kullanılabilir vekil sunucular.
2. **Saha Davranışı Veri Seti (Ground-Truth Multimodal Agent Dataset):**
   - Otonom ajanın gerçek dünya işletim sisteminde (Linux / Sway / Terminal / Ağ Araçları) gerçekleştirdiği her keşif, karar, hata, düzeltme ve terminal etkileşiminin; **kesintisiz H.264 ekran kaydı (video) + LLM düşünce/karar izi + OS PTY terminal I/O + ağ paketleri** ile multimodal bir eğitim setine dönüştürülmesi.
   - Bu veri; yerel modellerin fine-tuning edilmesinde (distillation/RL), ajanın kendi kendine öğrenmesinde ve operatörün kendi tersine mühendislik ve avcılık bilgi setini güçlendirmesinde kullanılır.

---

## 2. Hariç Tutulanlar (Non-Goals)

- Körü körüne, rastgele `/24` subnetlerine 8 port sıkıp bekleyen "script-kiddie" kaba kuvvet (brute-force) ameleliği.
- Tek bir IP üzerindeki sahte/firewall portlarında (ör. 3.105 port) saatlerce kilitlenip kalan senkron döngüler.
- Canlı ekran akışını saniyede onlarca megabaytlık Base64 PNG stringleri olarak JSON IPC içine gömüp Tauri'yi ve ağı kilitlemek.
- Proxy'leri Netflix, Google gibi hızla banlanan veya hedef odaklı platformlarda ilk doğrulamaya sokup false-negative üretmek.
- Operatörün müdahalelerini (interventions) pasif bir JSON dosyasında unutup ajanın saatlerce eski ameleliğine devam etmesi.

---

## 3. Sistemin 10 Temel Yapı Taşı (The 10 Invariant Building Blocks)

Bu 10 yapı taşı sistemin omurgasıdır; biri bile eksik veya statik şablonlarla kısıtlanmış olamaz.

```
[1. Keşif: myip.ms/RIPEstat/BGP] ──► [2. Kriter & Öncelik Hiyerarşisi] ──► [3. Değerli/Değersiz Analizi]
                                                                                      │
[6. Masscan Hız/Timeout] ◄── [5. Kokuya Göre Diş/İlk Port] ◄── [4. Dinamik Range & Pilot Isırık]
           │
           ▼
[7. Port Genleme & L7 Teyit] ──► [8. Bloklar Arası Geçiş/Sıkılma] ──► [9. Özdenetim & Pes Etmeme]
                                                                                      │
                                                                                      ▼
                                                                        [10. Mükerrer Engeli (Ledger)]
```

### Yapı Taşı 1: Hedef Keşfi (Reconnaissance & Discovery)
- **Veri Kaynakları:** `myip.ms` (unmanaged VPS, reseller hosting, colocation, bağımsız yerel ISP'ler) + `stat.ripe.net` / `bgp.he.net` (BGP anonsları, upstream AS'ler).
- **Koku Tetikleyicileri:** WHOIS ve ASN metinlerinde geçen *"cache, proxy, squid, transit, dynamic, pool, broadband, pppoe"* anahtar kelimeleri doğrudan av kokusudur.
- **Saha İstihbarat Kartı:** Ajan tek bir IP ile değil; sağlayıcının kimliği, altyapı türü, anons ettiği tüm prefix'ler ve komşuluk ilişkileriyle tam bir istihbarat kartı oluşturur.

### Yapı Taşı 2: Kriterler ve Öncelik Hiyerarşisi
Hedefler kâr/maliyet ve yaşama ömrü dengesine göre 3 katı kademede önceliklendirilir:
1. **Öncelik 1 (En Yüksek Getiri / Hızlı Kovan):** Unmanaged, güncellenmeyen ucuz hosting / VPS sağlayıcıları. Unutulmuş Squid/3proxy kovanları barındırma ihtimali yüksektir; tek vuruşta toplu proxy çıkarır.
2. **Öncelik 2 (Uzun Yaşama Ömrü):** Küçük kurumsal ISP'ler ve statik tahsisli forward vekiller. Banlanma riski çok düşüktür, haftalarca ayakta kalır.
3. **Öncelik 3 (Piyasa Değeri En Yüksek):** 4G/5G ve residential dinamik ISP havuzları (CGNAT/PPPoE).
- Ajan önceliği yüksek koku varken gidip düşük getirili veya ölü zeminlere bakamaz.

### Yapı Taşı 3: Değerli / Değersiz Hedef Kararı (Risk ve Yaratıcılık)
- **Ölü Zemin (Kesinlikle Yasak):** Cloudflare (AS13335), Google (AS15169), Microsoft Azure, AWS kurumsal CDN'leri, bankacılık ve savunma sistemleri. Buralarda açık vekil avı yoktur.
- **Değerli Zemin (Kan Kokusu):** Unmanaged reseller hostingler, ev cihazlarında açık bırakılmış portlar, unutulmuş colo merkezleri.
- **En Değerli Kural (Kardeş Damar):** Son isabet alınan IP'nin ait olduğu ASN ve komşu bloklar soğuk bir ASN'den daima katbekat önceliklidir.
- **Risk Alma:** Ajan bilinen kalıpların dışındaki egzotik ISP'leri (ör. Doğu Avrupa, Güneydoğu Asya yerel sağlayıcıları) denemekten çekinmez.

### Yapı Taşı 4: Dinamik Range Seçimi (Asla Statik /24 Yok!)
- Sağlayıcının anons ettiği range `/18`, `/20`, `/21` veya birden fazla `/24` olabilir. Ajan hiçbir zaman yapay bir `/24` sınırına hapsedilemez.
- **Pilot Isırık (Sampling):** Devasa bir bloğa tek seferde körü körüne girilmez. Bloğun içinden küçük bir örneklem dilimi (pilot) seçilerek kokuya uygun ilk dişle ısırılır.
- **Genişleme Kararı:**
  - Pilot ısırıkta canlılık (SYN-ACK) gelirse: O range "damar" kabul edilir ve range'in tamamına dikey/yatay olarak yayılınır.
  - Pilot ısırık tamamen karanlıksa: O range derhal terk edilir, sağlayıcının diğer prefix'ine geçilir.

### Yapı Taşı 5: Kokuya Göre Diş (İlk Port) Seçimi
`hunter-soul` kuralı: *"Türün dişini seçer, tüm ağız birden değil."*
- **Hosting / VPS Kokusu:** İlk diş `3128` (Squid), `8080`, `3129`.
- **Residential / Modem / CPE Kokusu:** İlk diş `1080` (SOCKS5), `7777` (residential gateway), `7000`, `823`, `6060`.
- **Ticari Proxy Ağı Kokusu:** `10000`, `12323`, `8000`.
- Asla aynı anda 65.535 portla kör dövüşü yapılmaz. Hedefin kimliğine uyan **tek bir ilk portla** kapı tıklatılır. Kapı açılırsa diğer olası portlara geçilir.

### Yapı Taşı 6: Masscan Hız ve Timeout Fiziği (`docs/masscan-hiz-ve-timeout.md`)
VDS üzerindeki fiziksel ölçüm sonuçları kanundur:
1. **Timeout Güvenli Tabanı:**
   - 0.5s timeout gerçek açık portları düşürür (yanlış negatif).
   - **Kural: `timeout >= 1.0s` (tercihen 1.5s), her porta 2 deneme.**
2. **Dinamik Rate (pps) ve Wait:**
   - Tek IP veya küçük blok: `--rate 5000 --wait 3`.
   - Geniş CIDR blokları (/18, /16): Upstream router'da paket drop yememek için `--rate 2500-4000 --wait 3`.
3. **Socket Teyidi:** Masscan yalnızca L4 SYN canlılığıdır; dönen portlar mutlaka soket el sıkışmasıyla teyit edilir.

### Yapı Taşı 7: Port Genleme ve Maksimum Proxy Damıtımı
- Masscan çıktısında ardışık veya blok portlar (ör. `10000-10050` veya `8000-8020` sticky aralıkları) görüldüğünde, sistem bunu bir "proxy kovanı" olarak tanımlar ("genleme").
- **1000 Eşzamanlı Asenkron L7 Sondası:** Bu portların tamamına tek bir event loop içinde 300-500ms zaman aşımlı HTTP CONNECT ve SOCKS5 el sıkışma paketleri fırlatılır.
- Kovan içindeki çalışan her port tek tek L7 teyidinden geçirilerek kasaya aktarılır; tek bir açık uçtan onlarca çalışan proxy elde edilir.

### Yapı Taşı 8: Bloklar Arası Geçiş ve Sıkılma Kuralı
- **Ölü Blok:** Hiç SYN-ACK dönmüyorsa range derhal terk edilir.
- **Canlı Ama Servis Portu:** (Ör. ASN 209207 tecrübesi: 88 açık uç çıktı ama hepsi web sunucusu / 407 auth verdi).
  - Ajan anlar: *"Bu blok web hosting ağırlıklı, açık vekil yok."*
  - Aynı blokta ısrar edilmez; sağlayıcının ASN'i değiştirilir veya residential kokuya geçilir.

### Yapı Taşı 9: Özdenetim, Kesintisiz Döngü ve Pes Etmeme
- Bir sağlayıcının tüm range'leri bittiğinde ve sıfır proxy çıktığında ajan:
  1. **Özdenetim Yapar:** Masscan çöktü mü? Ağda drop oldu mu? Teknik bir arıza yoksa sorun hedefin kısırlığıdır.
  2. **Döngüyü Kesintisiz Döndürür:** Durmaz, pes etmez. Hafızasına bu ASN'in kısırlığını kaydeder ve `myip.ms` havuzundaki bir sonraki taze hedefe geçer. Çalışan proxy elde edilene kadar bu döngü durmaksızın akar.

### Yapı Taşı 10: Mükerrer (Duplicate) Tarama Yasağı
- Taranan her ASN, CIDR ve port kombinasyonu kalıcı **Av Defteri Muhasebesine (Ledger)** yazılır.
- Aynı hedefin aynı range'ine yalnızca iki durumda geri dönülür:
  1. Sağlayıcı BGP'ye yeni bir prefix (yeni IP bloğu) anons ettiğinde.
  2. Operatör av defterine yeni bir koku/port eklediğinde.
- Bunun haricinde aynı aralık asla mükerrer taranmaz.

---

## 4. Desktop Cockpit'in Gerçek Fonksiyonel Rolü (C2 Masası)

Masaüstü uygulaması bir "resim görüntüleyici" değildir; bu 10 yapı taşını yöneten ve gösteren **Canlı Komuta Kontrol (C2) Merkezidir**.

### A. Telemetri ve HUD (Canlı Görünüm)
1. **Hedef & Koku Paneli:** Ajanın o an hangi ASN'e baktığı, hangi BGP prefix'ini seçtiği, kokunun gerekçesi ve öncelik seviyesi.
2. **Tarama & Genleme HUD:** Seçilen range, uygulanan masscan hızı (pps/wait), bulunan açık portlar ve genlenen aralıklar.
3. **Canlı Kasa:** Egress doğrulaması geçen proxy'ler milisaniyesinde yeşil olarak ekrana düşer (`IP:Port - Egress IP - Latency`).
4. **Canlı PTY Akışı:** Ajanın düşündüğü, attığı komutlar ve terminal çıktısı ANSI renkleriyle canlı akar (`xterm.js`).

### B. Kesintisiz Video vs İsteğe Bağlı Ekran Ayrımı (Decoupling)
- **VDS Tarafı (Her Zaman Açık):** `wf-recorder` Sway masaüstünü 720p/15fps H.264 MP4 olarak kesintisiz kaydeder (`var/recordings/{agent_id}/screen.mp4`). Sıfır ağ harcar, diski şişirmez.
- **Cockpit Tarafı (İsteğe Bağlı):** Operatör sadece "VDS Canlı Ekran" sekmesini açtığında, VDS'teki `wayvnc` -> `websockify` üzerinden doğrudan native noVNC (WebSocket) açılır. Sekme kapandığında ağ akışı sıfırlanır. Araya asla Base64 JSON girmez.

### C. Öncelikli Müdahale (Preemptive Interrupt)
- Operatör Cockpit'ten "DUR", "BU BLOĞU GEÇ", "ŞU ASN'E ATLA" dediğinde; mesaj pasif bir JSON'a yazılmaz.
- Ajanın sürecine anında bir `CancelToken` sinyali ulaşır; ajan mevcut soket ameleliğini o salisede keser ve yeni emre döner.

---

## 5. Saha Verisi Hasadı (Multimodal Dataset Fabrikası)

Ajanın her adımı, gelecekteki modelleri fine-tune etmek üzere yapılandırılmış bir **State-Action-Reward** zinciri olarak saklanır:

```json
{
  "timestamp": "2026-09-12T00:30:00.000Z",
  "agent_id": "ajan-xxxx",
  "video_timecode_ms": 45210,
  "state": {
    "target_asn": "AS209207",
    "target_cidr": "138.124.79.0/24",
    "intelligence_source": "myip.ms unmanaged vps",
    "pilot_result": "SYN-ACK on port 10000"
  },
  "llm_thought": "Pilot ısırıkta 10000 portu yanıt verdi. Kovan ihtimali yüksek, 10000-10050 aralığını genleyip asenkron L7'ye veriyorum.",
  "action": {
    "tool": "fast_triage_range",
    "ports": [10000, 10001, 10002, 10003]
  },
  "terminal_pty_stdout": "... [L7 PROBE] 138.124.79.160:10000 -> HTTP CONNECT 200 OK ...",
  "outcome": {
    "egress_confirmed": true,
    "exit_ip": "138.124.79.160",
    "latency_ms": 142
  },
  "reward": 1.0
}
```

---

## 6. Uygulama Adımları ve Doğrulama Kriterleri

1. **`services/agentd/fast_triage.py`:**
   - 1000 eşzamanlı soket, `timeout >= 1.0s`, HTTP CONNECT ve SOCKS5 el sıkışması, `1.1.1.1/cdn-cgi/trace` nötr egress kontrolü.
   - Doğrulama: Sahte 3.000 portluk senaryoda 1.5 saniyede triage testi.
2. **`services/agentd/recon.py`:**
   - BGP prefix çekimi (RIPEstat), PTR desen analizi, ASN komşulukları.
   - Doğrulama: `AS209207` sorgulandığında tüm anons edilen CIDR'ların doğru listelenmesi.
3. **`services/agentd/ai_runtime.py` Entegrasyonu:**
   - Sabit `/24` ve senkron tekil port prangasının kaldırılması.
   - Karar motoruna bu 10 yapı taşını zorunlu kılan operasyonel kontratın bağlanması.
4. **`services/agentd/dataset_recorder.py`:**
   - Sway ekranının `wf-recorder` ile H.264 MP4 olarak arka planda kaydedilmesi ve telemetri JSONL ile senkronlanması.
5. **Cockpit C2 & noVNC:**
   - Tauri içinde Base64 polling yerine doğrudan noVNC sekmesi ve anlık iptal (interrupt) sinyalinin bağlanması.
