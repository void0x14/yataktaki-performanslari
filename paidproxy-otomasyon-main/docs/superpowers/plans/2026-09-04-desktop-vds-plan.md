# [Desktop VDS] Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** PC'de gerçek Qt masaüstü + VDS'de deterministik worker ile otonom keşfi görünür kılmak.

**Architecture:** PySide6 ProcessStore + Recall + VDS SSH-key; WanderAgent Aşama 1'de; karar manifesti taramadan önce görünür.

**Tech Stack:** Python 3.12+, PySide6, mss/Pillow, ffmpeg, masscan (VDS), SQLite.

**Spec:** docs/superpowers/specs/2026-09-04-desktop-vds-design.md

## Global Constraints

- VDS şifresi repo/kod/log'a giremez.
- Masscan yalnızca açıkça oluşturulmuş manifest hedeflerini çalıştırır.
- myip.ms otomatik kazınmaz.
- Sert müdahale otomatik restart yapmaz.
- Her süreç ve uzak komut UI/log'da görünür.

---

### Task 1: Desktop süreç defteri

**Files:**
- Test: `tests/unit/test_desktop_store.py`
- Modify: `desktop/app/store.py`

**Interfaces:**
- Consumes: `desktop/app/models.py` AgentProcess/Pet
- Produces: `ProcessStore.create/pause/resume/hard_kill/destroy/list`

- [ ] **Step 1: Test yazıldı ve koşuyor** (`pytest tests/unit/test_desktop_store.py -q`)
- [ ] **Step 2: hard_kill kanıt koruyor, restart yok** (kodda `öldürüldü` + beat)
- [ ] **Step 3: Commit**

### Task 2: Gezgin ajan

**Files:**
- Test: `tests/unit/test_wander.py`
- Create: `src/proxy_pipeline/agents/wander.py`

**Interfaces:**
- Consumes: DecisionContext(snapshot)
- Produces: DecisionOutput dict (research|sample, items, evidence)

- [ ] **Step 1: Kanıtsız research testi PASS**
- [ ] **Step 2: CIDR'li sample testi PASS**
- [ ] **Step 3: Journal dosyası yazılıyor**
- [ ] **Step 4: Commit**

### Task 3: Recall iz

**Files:**
- Test: `tests/unit/test_recall_trace.py`
- Create: `src/proxy_pipeline/recall/trace.py`, `desktop/app/recall.py`

- [ ] **Step 1: trace.jsonl append testi PASS**
- [ ] **Step 2: Kare/klip yoksa None (sahte başarı yok)**
- [ ] **Step 3: Commit**

### Task 4: VDS bootstrap

**Files:**
- Create: `ops/vds/bootstrap-trixie-arm64.sh`, `ops/vds/key-setup.sh`, `ops/vds/inventory-check.sh`

- [ ] **Step 1: Scriptler executable, şifre içermiyor**
- [ ] **Step 2: inventory read-only (tarama/yazma yok)**
- [ ] **Step 3: Commit**

### Task 5: Desktop smoke

**Files:**
- Modify: `desktop/app/main.py`

- [ ] **Step 1: `QT_QPA_PLATFORM=offscreen python3 -c "import desktop.app.main"` PASS**
- [ ] **Step 2: `./pipeline --help` ve `pytest tests/unit/test_desktop_store.py tests/unit/test_wander.py tests/unit/test_recall_trace.py -q` PASS**
- [ ] **Step 3: Commit**
