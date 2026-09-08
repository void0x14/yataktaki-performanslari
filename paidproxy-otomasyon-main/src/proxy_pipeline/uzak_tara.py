"""Uçta canlı tarama: yapay zekânın kararını telde koşturur, eler, kaydeder.

- Komut yapay zekânın bildirisinden gelir; hız pencerede görünür.
- Çıktı bildiriyle çözümlenir; her açık uç el sıkışmadan geçer.
- Doğrulanan bulgu envantere, ham açık uç makaraya yazılır.
- Çalıştırıcı ve doğrulayıcı dışarıdan verilebilir (sınama); verilmezse
  gerçek tel ve gerçek el sıkışma kullanılır.
"""
from __future__ import annotations
from pathlib import Path as _P

def yurut_canli(vds, cidr: str, portlar: tuple, *, hiz: int = 100,
                port_dizgesi: str | None = None,
                calistirici=None, dogrulayici=None,
                makara: _P | None = None, bulgu_dizini: _P | None = None) -> dict:
    from proxy_pipeline.queue.spool import AppendOnlySpool
    from proxy_pipeline.safety import KillSwitch, RunGate
    from proxy_pipeline.scanners.adapter import MasscanAdapter
    from proxy_pipeline.scanners.runner import MasscanRunner, operator_manifest, write_events
    from proxy_pipeline.validators.protocols import ValidationResult, ValidatorPool
    from proxy_pipeline.yuruyus import kaydet
    from proxy_pipeline.feedback import save_bulgu

    from proxy_pipeline.tarama_plani import hiz_karari
    hiz, hiz_uyarisi = hiz_karari({"hiz": hiz})
    if hiz_uyarisi:
        kaydet("hiz-uyarisi", str(cidr), hiz_uyarisi)
    KillSwitch().check()
    bildiri = operator_manifest(str(cidr), tuple(int(x) for x in portlar), port_dizgesi=port_dizgesi)
    kosucu = MasscanRunner(MasscanAdapter(RunGate()))
    komut = kosucu.command(bildiri, rate=int(hiz))
    uzak_komut = "sudo " + " ".join(komut)
    kaydet("canli-tarama", f"{cidr} {portlar}", " ".join(komut))
    if calistirici is None:
        from cockpit.bridge.vds import run_remote
        cevap = run_remote(vds, uzak_komut, timeout=300)
        cikti = (cevap.stdout or "") + (cevap.stderr or "")
    else:
        cikti = calistirici(uzak_komut)
    satirlar = [s for s in str(cikti).splitlines()
                if s.strip() and not s.strip().startswith("#") and s.strip().startswith("open ")]
    oluler = AppendOnlySpool("var/spool/olu-satirlar.txt")
    olaylar = MasscanAdapter(RunGate(), dead_letter=oluler).parse_stdout(
        bildiri, [s for s in str(cikti).splitlines() if s.strip() and not s.strip().startswith("#")])
    write_events(makara or _P("var/spool/l4-open.txt"), olaylar)
    havuz = dogrulayici or ValidatorPool()
    acik, dogrulanan = [], []
    for o in olaylar:
        acik.append({"ip": o.target_ip, "port": o.port})
        try:
            sonuclar = havuz.validate(o.target_ip, o.port, ("http_connect", "socks5"))
        except Exception:
            continue
        for s in sonuclar or []:
            if getattr(s, "result", None) is ValidationResult.VALIDATED:
                dogrulanan.append({"ip": o.target_ip, "port": o.port,
                                   "protokol": getattr(s, "protocol", "")})
                if bulgu_dizini is None:
                    save_bulgu(o.target_ip, o.port, protokol=getattr(s, "protocol", ""),
                               kaynak=f"uç-canlı:{cidr}")
                else:
                    save_bulgu(o.target_ip, o.port, protokol=getattr(s, "protocol", ""),
                               kaynak=f"uç-canlı:{cidr}", bulgu_dir=bulgu_dizini)
                break
    kaydet("canli-eleme", str(cidr), f"{len(acik)} açık, {len(dogrulanan)} doğrulandı")
    return {"tamam": True, "komut": komut, "acik": acik, "dogrulanan": dogrulanan}
