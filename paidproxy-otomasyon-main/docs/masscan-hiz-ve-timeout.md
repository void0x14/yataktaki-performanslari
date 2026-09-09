# masscan hız/timeout notu (VDS'de ölçülmüş)

Tarih: 2026-09-09 · Ölçüm yeri: VDS 20.207.198.170 (arm64, 4 vCPU)
Hedef: 193.233.126.126 ve 193.233.126.89 (tek IP, 1-65535)

## Kısa sonuç

Tek IP tam port taraması için en doğru yol: **masscan ile numaralandır + socket ile teyit et.**
Saf socket taraması hem yavaş hem port kaçırıyor. Ölçüm:

| Yöntem | Süre | Bulunan |
|---|---|---|
| Saf socket, timeout=0.5s, 1024 thread | 250s+ (kesildi) | eksik: 22,80,443 (5432/8000/16866 kaçtı) |
| Saf socket, timeout=1.5s, 512 thread | ~200s+ | 22,80,443,5432,8000,16866 |
| masscan `--rate 10000 --wait 0` | **8.2s** | 22,80,443,5432,8000,16866 |
| masscan `--rate 5000 --wait 3` | ~10s | aynı 6 port |
| **hibrit (masscan + socket teyit)** | **15-18s** | aynı 6 port, yanlış pozitif yok |

## Neden saf socket kaçırıyor

`timeout=0.5s` ile 16866 kaçtı. Aynı port tek tek denendiğinde **5/5 açık** döndü.
Yani port ölü değildi; agresif timeout onu düşürdü.

- timeout düşük → SYN-ACK geciken portlar "kapalı" sayılır (yanlış negatif)
- thread sayısı çok yüksek + timeout düşük → yerel TCP backlog/gecikme artar, kayıp çoğalır
- 65535 port × düşük timeout tek süreçte pratikte dakikalara çıkıyor

Güvenli taban: **timeout >= 1.0s, tercihen 1.5s**; her porta 2 deneme.

## masscan parametreleri

```
masscan <ip>/32 -p1-65535 --rate <pps> --wait <sn> -oL -
```

- `--rate` = saniyedeki paket (pps), port sayısı değil. Tek IP'de 5000-10000 makul;
  hedef ağ büyüdükçe düşür, yoksa paket kaybı/yanlış negatif artar.
- `--wait 0` bizim ölçümde 3/3 koşuda aynı 6 portu buldu. Şüpheliyse `--wait 3` kullan;
  tarama sonu bekleme artar, sonuç daha stabil.
- `-oL -` liste formatı; `open tcp <port> <ip> <ts>` satırları okunur.
- Çıktıyı **socket ile teyit et**: masscan SYN gönderir, servis gerçekten cevap veriyor mu
  ayrıca kontrol edilmeli. Teyit hem yanlış pozitifi hem de tarama sonrası ölen portu eler.

## Uygulamadaki yerleşim

- `services/agentd/ai_runtime.py` → `_masscan_enumerate_ports()` (masscan çağrısı)
- `services/agentd/ai_runtime.py` → `_port_scan_live_ip()` (numaralandır + socket teyit, 1-65535)
- Varsayılan: rate 5000, socket teyit timeout 1.5s, her port 2 deneme
- Yetki: systemd `AmbientCapabilities=CAP_NET_RAW CAP_NET_ADMIN` + `NoNewPrivileges=false`,
  masscan'da `setcap cap_net_raw,cap_net_admin+eip` → sudo gerekmez

## Sık yapılan hatalar

1. `timeout` değerini "hız için" 0.5'e düşürmek → gerçek açık portları kaybeder
2. masscan çıktısını teyit etmeden "açık" saymak → ölü/yanlış pozitif portlar listeye girer
3. `--rate`'i port sayısıyla karıştırmak → aşırı paket, kayıp
4. Tek IP için saf socket ile 65535 taramak → dakikalar, üstelik eksik sonuç
