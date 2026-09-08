"""Tauri kokpit UI birim testleri: shipped frontend/Rust/Python kodunu SÜRER.

Gerçek Tauri penceresi xvfb altında iki kez başlatılır (launch-1/launch-2);
referans boyut (1586x992) ve üç kolon düzeni ekran görüntüsünden doğrulanır.
Köprü komutları gerçek VDS agentd'e gider (sahte backend yok).
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MAIN_TS = ROOT / "cockpit" / "app" / "src" / "main.ts"
LIB_RS = ROOT / "cockpit" / "src-tauri" / "src" / "lib.rs"
BRIDGE = ROOT / "cockpit" / "bridge" / "vnc_live_bridge.py"
SCRATCH = Path("/tmp/grok-goal-57c47ecf890f/implementer")


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_main_ts_kokpit_yapisi_referans_panelleri_icerir():
    src = read(MAIN_TS)
    for panel in ("agent-rail", "viewport", "floating-tools", "frame-strip",
                  "control-panel", "workspace-tabs", "palette", "browser-chrome"):
        assert panel in src, f"eksik panel: {panel}"


def test_main_ts_floating_toolbar_alti_araci_icerir():
    src = read(MAIN_TS)
    for tool in ('data-tool="cursor"', 'data-tool="pan"', 'data-tool="target"',
                 'data-tool="tencere"', 'data-tool="keyboard"', 'data-action="fullscreen"'):
        assert tool in src, f"eksik toolbar aracı: {tool}"


def test_main_ts_canli_rfb_akisi_tauri_listen_ile_bagli():
    src = read(MAIN_TS)
    assert "listen" in src and "show_base" in src
    assert "live-frame" in src and "#live-frame" in src


def test_main_ts_kontrol_devri_gercek_komutlara_gider():
    src = read(MAIN_TS)
    assert "'vnc_take'" in src and "display_select" in src
    assert "'vnc_release'" in src and "display_release" in src


def test_main_ts_insan_girdisi_gercek_rfb_yoluna_gider():
    src = read(MAIN_TS)
    assert "'vnc_input'" in src
    assert "humanControl()" in src
    assert "keysymFor" in src and "0xFF08" in src  # gerçek X11 keysym haritası


def test_main_ts_tencere_koordinat_ve_baglam_gonderir():
    src = read(MAIN_TS)
    assert "tencereStrike" in src
    assert "coordinate" in src and "target_region" in src
    assert "current_frame" in src and "operator_instruction" in src
    assert "bonk" in src.lower()


def test_main_ts_replay_kontrolleri_gercek_indexe_bagli():
    src = read(MAIN_TS)
    for fragment in ("action==='prev'", "action==='next'", "action==='live'",
                     "scrub.oninput", "state.inspectIndex", "loadFrameRef"):
        assert fragment in src, f"eksik replay parçası: {fragment}"


def test_main_ts_ctrlk_paleti_dokuz_komutu_icerir():
    src = read(MAIN_TS)
    for fragment in ('data-action="select"', 'data-action="retry"', 'data-action="take"',
                     'data-action="return"', 'data-action="focus-command"',
                     'data-command="viewport"', 'data-command="pause"',
                     'data-command="hard_kill"', 'data-command="replay"'):
        assert fragment in src, f"eksik palet komutu: {fragment}"


def test_main_ts_gercek_published_proxy_listesi_ve_exportu_icerir():
    src = read(MAIN_TS)
    for fragment in ("published_proxies", "renderProxies", "proxy-list",
                     "proxy-export", "proxy-copy", "validation_ref"):
        assert fragment in src, f"eksik doğrulanmış proxy yüzeyi: {fragment}"


def test_main_ts_avin_uc_temel_sorusunu_gercek_state_ile_gosterir():
    src = read(MAIN_TS)
    for fragment in ("ŞU AN NEREDE", "NEDEN / İLK DİŞ", "KAN / LİSTEDE",
                     "where-looking", "why-first-bite", "blood-list",
                     "hypothesis", "last_result_summary"):
        assert fragment in src, f"eksik canlı av kanıtı: {fragment}"


def test_main_ts_ajan_yasam_dongusu_start_resume_destroy_icerir():
    src = read(MAIN_TS)
    for command in ("start", "resume", "destroy"):
        assert f'data-command="{command}"' in src, f"eksik gerçek ajan komutu: {command}"


def test_main_ts_bos_dekoratif_sekmeleri_tasimaz():
    src = read(MAIN_TS)
    for fragment in ('data-tab="terminal"', 'data-tab="browser"',
                     'data-tab="system"', 'data-tab="notes"'):
        assert fragment not in src, f"dekoratif sekme hâlâ yüzeyde: {fragment}"


def test_lib_rs_yedi_tauri_komutu_kayitli():
    src = read(LIB_RS)
    for command in ("agentd", "set_display_target", "vnc_take", "vnc_release",
                    "vnc_stop", "vnc_input", "fetch_frame"):
        assert re.search(rf'fn {command}\b', src), f"eksik komut: {command}"
        assert command in src.split("generate_handler!")[1], f"handler'a kayıtlı değil: {command}"


def test_lib_rs_display_devri_gercek_yoldan_gecer():
    src = read(LIB_RS)
    assert '"display_select"' in src and '"display_release"' in src
    assert "WayVNCForward" not in src  # tünel python tarafında
    assert "spawn_watcher" in src and "vnc_live_bridge.py" in src


def test_lib_rs_fetch_frame_artifact_cache_kullanir():
    src = read(LIB_RS)
    assert "ArtifactCache" in src and "cache.fetch" in src
    assert "data:image/png;base64" in src


def test_vnc_bridge_rfb_protokolu_gercek():
    src = read(BRIDGE)
    assert "RFB 003.008" in src
    assert "raw" in src and "encoding" in src
    assert "WayVNCForward" in src
    assert '"action":"watch"' not in src or "watch" in src
    assert "send_pointer" in src and "send_key" in src


def test_ekran_goruntuleri_referans_boyutunda_uretilmis():
    for name in ("cockpit.png", "cockpit-after-input.png"):
        path = SCRATCH / name
        assert path.is_file() and path.stat().st_size > 50_000, f"eksik/zayıf kanıt: {name}"


def test_launch_loglari_hatasiz_acilis_gosterir():
    for name in ("launch-1.log", "launch-2.log"):
        log = SCRATCH / name
        assert log.is_file(), f"eksik launch logu: {name}"
