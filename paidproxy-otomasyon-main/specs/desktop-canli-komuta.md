# Desktop canli komuta duzeltmesi

## Sorun
1. Gözlemle yalniz snapshot donduruyor, canli RFB akisi tek tikla acilmiyor.
2. Ajan secimi yuzey secmiyor/izlemiyor; kullanici canliya donuyor ama akis yok.
3. Worker exit code != 0 her zaman failed; cikti ureten ajan bile failed gorunuyor.
4. Replay her 1sn + tum thumb'lar icin ayri python+scp -> arayuz donuyor.
5. watcher degisiminde eski izleyici kaliyor, yeni ajan akisi acilmiyor.

## Degisiklik
- supervisor: yayinlanmis/dogrulanmis ciktisi olan ajan exit!=0 olsa bile completed.
- lib.rs: vnc_take eski izleyiciyi durdurup yenisini acar; vnc_watch salt-okunur izleme ekler.
- main.ts: Gozlemle = vnc_watch (tek tik canli), ajan seciminde otomatik display hedefi + sessiz canli izleme,
  replay 2.5sn + gizli sekmede duraklatma, thumb yukleme kuyrugu (max 2 eszamanli), pan surukleme, klavye odagi.

## Ek bulgu (canli akis olu gorunuyordu)
- WayVNCForward kalici agentd portunu (28787) RFB saniyordu; RFB agentd protokolune carpip
  TimeoutError veriyordu. Ayrica start() kendi SSH tunelini hic acamiyordu (olusmez kod).
- Duzeltme: WayVNCForward artik bos portta ozel -L tuneli acar (reuse_persistent_port=False);
  agentd yolu kalici tuneli paylasmaya devam eder.
- frame_png RGBX->RGB donusumu eklendi (PIL PNG yazamiyordu).
- Kanit: vnc_live_bridge watch ile CONNECTED ServerInit 1280x720 WayVNC + 4 LIVE kare,
  /tmp/vds_live_proof.png kaydedildi ve goruntulendi (Sway terminali, ajan olay alani).
- Tauri debug ikilisi yeniden derlendi (vnc_watch dahil); kullanici ./desktop-launch ile acmali.
