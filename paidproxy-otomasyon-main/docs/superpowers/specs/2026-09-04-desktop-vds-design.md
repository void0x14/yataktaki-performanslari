# Desktop + VDS Tasarım (2026-09-04)

## Varsayım (soru sorulmadı, otonom)
- PC: Linux masaüstü, PySide6 Qt. VDS: 20.207.198.170/arm64/trixie, user mani.
- Bağlantı: SSH key (`~/.ssh/paidproxy_vds`), BatchMode. Şifre repo/kod/log'da yok.
- Şifre yalnızca operatörün bir kerelik `key-setup.sh` çalıştırmasında yazılır, saklanmaz.

## Mimari
- Desktop (`desktop/app`): MainWindow; ProcessStore (A-Z yarat/duraklat/devam/sert-öldür/yok-et);
  canlı düşünce akışı; pet (her ajan, ruh/enerji gerçek event'ten); Recall (mss/import kare + ffmpeg klip,
  `var/recall/`); VDS prob (read-only ssh, komut logda görünür).
- VDS (`ops/vds/`): `bootstrap-trixie-arm64.sh` masscan+python+pipeline+systemd;
  `inventory-check.sh` yazmasız envanter; geniş tarama varsayılan kapalı.
- Ajan: `WanderAgent` (boş gezinme+muhakeme, Aşama 1). myip.ms otomatik kazınmaz;
  seed yalnızca operatörün manuel baktığı IP. L4/L7 deterministik; hedef ve port kararı manifestte görünür.
- İz: `proxy_pipeline.recall.trace.emit` (jsonl) + `var/journal/gunluk-*.md` sentez.

## Güvenlik/ToS
- Manifest olmadan geniş `tara` yok; araçlar yalnız manifestteki hedefleri çalıştırır.
- myip.ms/RIPEstat'a rate-limit + cache; abuse'da kill-switch, otomatik restart yok.
- Recall'da secret maskeleme; kayıtlar yalnızca yerelde.

## Ölçü (1 hafta -> 1 saat)
- Değerlendirme kümesi: `evaluation/evaluation-set/` manuel kararları; wander+kesif ajanları shadow'da aynı adayları oynar.
- Kapı: precision/recall + doğrulanmış-yüksek-değerli/efor baseline altı değilse üretim.
