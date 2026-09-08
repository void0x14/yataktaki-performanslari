# VDS Ajan Gözetmeni ve Operasyon Konsolu Uygulama Planı

> For agentic workers: REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

Goal: VDS üzerinde kalıcı gerçek ajan prosesleri, canlı olay akışı ve gerçek sert müdahale sağlayan paidproxy-agentd gözetmenini kurmak ve native masaüstünü bu gözetmenin istemcisi yapmak.

Architecture: VDS operasyonun tek sahibidir. paidproxy-agentd loopback üzerinde kalıcı iş/proses/event durumunu tutar; PySide6 masaüstü SSH port-forward üzerinden JSONL komut ve olay akışına bağlanır. Ajan worker'ı gerçek child process olarak çalışır ve sonraki AI araç döngüsüne, ekran/video kaydına ve proxy kanıt zincirine bağlanacak açık sözleşmeleri üretir.

Tech Stack: Python 3.12+, stdlib asyncio/socket/subprocess/signal, mevcut paidproxy Python çekirdeği, PySide6, SSH port-forward, systemd, VDS üzerindeki SQLite ve append-only JSONL kayıtları.

## Global Constraints

- Yerel makine tarama, L7 doğrulama, AI çalışma döngüsü veya operasyon worker'ı çalıştırmaz.
- VDS operasyon, iş, event, kanıt, ekran ve video kayıtlarının sahibidir.
- Supervisor yalnız VDS loopback üzerinde dinler; masaüstü SSH port-forward kullanır.
- Ajanlar gerçek PID ve process-group kimliğiyle çalışır; yerel status değişikliği süreç kontrolü sayılmaz.
- hard_kill gerçek uzak process-group'u bitirir, PID yokluğunu doğrular ve otomatik restart yapmaz.
- Her uzak ajan oluşturulurken VDS'de kalıcı pet kimliği atanır.
- Gerçek araç olayı olmadan sahte heartbeat veya sahte ilerleme üretilmez.
- 8080, 3128 ve 1080 sabit port akışı değildir; sonraki AI araç döngüsü dinamik yüksek-port kararını taşır.
- L4 açık sonucu proxy sonucu değildir; protokol handshake ve gerçek hedef isteği olmadan teslim yapılmaz.
- Ajan çalışma notu, hipotez, karşı hipotez, kanıt ve sonraki adım event akışında görünür olur.
- Birim testleri kabul kriteri değildir; canlı VDS prosesleri, event akışı, müdahale ve gerçek sonuç kanıtı kabul kriteridir.
- Parola, token, anahtar veya hassas model bilgisi repo, event, video veya log dosyasına yazılmaz.
- Kullanıcı birim test istemediği için pytest veya mock tabanlı doğrulama çalıştırılmayacak.

---

## Dosya ve sorumluluk haritası

Oluşturulacak VDS gözetmeni dosyaları:

- services/agentd/__init__.py: paket sınırı.
- services/agentd/protocol.py: JSONL komut/event sözleşmesi, şema doğrulama ve redaksiyon.
- services/agentd/state.py: VDS kalıcı ajan/job/event state store.
- services/agentd/supervisor.py: loopback sunucusu, komut yönlendirme, gerçek child process yaşam döngüsü.
- services/agentd/worker.py: tek uzak ajanın gerçek çalışma prosesi ve worker-to-supervisor event çıkışı.
- services/agentd/__main__.py: systemd giriş noktası.
- ops/systemd/paidproxy-agentd.service: VDS kalıcı supervisor servisi.
- ops/vds/install-agentd.sh: mevcut VDS checkout'u üzerine güvenli kurulum ve servis başlatma.

Oluşturulacak masaüstü istemci dosyaları:

- desktop/app/agentd_client.py: SSH port-forward, JSONL komut gönderimi, reconnect ve event stream.
- desktop/app/remote_models.py: uzak ajan/job/event ve pet durum modelleri.
- desktop/app/remote_worker.py: Qt ana thread'ini bloklamadan istemci eventlerini UI sinyallerine taşıyan worker.
- desktop/app/viewport.py: VDS viewport frame ve geçmiş segment gösterim yüzeyi; ilk dilimde gerçek event/frame referansı gösterecek.

Değiştirilecek mevcut dosyalar:

- desktop/app/store.py: yerel bellek sahibi olmaktan çıkıp uzak store/cache adapter'ı olacak; geçici bağlantı yokluğunda komutları sessizce başarılı saymayacak.
- desktop/app/vds.py: SSH port-forward prosesini ve port tahsisini yöneterek tek komut çalıştırıcısı rolünden bağlantı taşıyıcısı rolüne geçecek.
- desktop/app/main.py: yarat/duraklat/devam/sert öldür/yok et işlemlerini uzak komutlara bağlayacak; canlı düşünce, pet ve durum yalnız remote eventlerden güncellenecek.
- desktop/app/yoldas.py: pet görünümü remote agent event durumlarını alacak.
- context/PROJECT.md ve context/ARCHITECTURE.md: dört sabit yerel aşama yerine VDS supervisor + AI tool loop + kanıt/viewport akışını tarif edecek.
- backlog/BACKLOG.md: gerçek VDS servis ve masaüstü bağlantı durumunu yansıtacak.

---

### Task 1: Olay ve komut sözleşmesi

Files:
- Create: services/agentd/protocol.py
- Create: desktop/app/remote_models.py

Interfaces:
- Produces: Command, EventEnvelope, AgentSnapshot, JobSnapshot, PetSnapshot ve encode/decode fonksiyonları.
- Consumes: yalnız stdlib json, uuid ve datetime.

EventEnvelope alanları:

    {
      "seq": 1,
      "event_id": "uuid",
      "timestamp": "ISO-8601 UTC",
      "agent_id": "ajan-...",
      "job_id": "is-...",
      "pid": 1234,
      "process_group": 1234,
      "state": "running",
      "event_type": "tool_started",
      "tool": "owner_lookup",
      "target": "198.51.100.10",
      "working_note": "ASN ve owner sinyalini karşılaştırıyorum",
      "hypothesis": "...",
      "counter_hypothesis": "...",
      "evidence_refs": [],
      "decision": null,
      "next_action": "...",
      "output_ref": null,
      "frame_ref": null,
      "video_ref": null,
      "operator_action": null,
      "error": null
    }

- [ ] Step 1: Komut adlarını ve terminal durumlarını tek Enum/tuple tanımıyla yaz.
- [ ] Step 2: JSONL encoder her komutu tek satır, UTF-8 ve newline ile üretmeli.
- [ ] Step 3: Decoder bozuk JSON, eksik request_id ve bilinmeyen command için görünür hata event'i üretmeli; sessizce düşmemeli.
- [ ] Step 4: Event redactor token, Authorization header, SSH key path ve model credential değerlerini event payload'ından çıkarmalı.
- [ ] Step 5: remote_models.py, eventten pet durumunu üretmek için event_type/state alanlarını saklamalı; pet ruhu yalnız gerçek eventle değişmeli.

Live check:

    python3 -m services.agentd.protocol

Expected: örnek command/event JSONL stdout'a yazılır, credential veya yerel makine yolu içermez, süreç exit code 0 ile biter.

---

### Task 2: VDS kalıcı state store

Files:
- Create: services/agentd/state.py

Interfaces:
- StateStore(root: Path)
- StateStore.create_agent(kind: str, label: str, pet_name: str | None) -> AgentSnapshot
- StateStore.update_agent(agent_id: str, **fields) -> AgentSnapshot
- StateStore.append_event(event: EventEnvelope) -> EventEnvelope
- StateStore.list_agents() -> list[AgentSnapshot]
- StateStore.events_after(seq: int, agent_id: str | None = None) -> list[EventEnvelope]
- StateStore.remove_agent(agent_id: str) -> None

Persistence layout:

    var/agentd/agents.json
    var/agentd/events.jsonl
    var/agentd/agents/<agent-id>/frames/
    var/agentd/agents/<agent-id>/video/
    var/agentd/agents/<agent-id>/manifest.json

- [ ] Step 1: root ve agent alt dizinlerini mkdir ile oluştur; izinleri owner-only yap.
- [ ] Step 2: agents.json yazımını temporary file + os.replace ile atomik yap.
- [ ] Step 3: events.jsonl append işlemini flush + fsync ile tamamla; seq değerini tek writer altında monotonik tut.
- [ ] Step 4: başlatma sırasında bozuk son JSONL satırını silmeden corruption event'i üret ve önceki geçerli seq'den devam et.
- [ ] Step 5: supervisor yeniden başladıktan sonra running kayıtlarını unknown/recovering yap; killed, destroyed ve completed kayıtlarını yeniden başlatma.
- [ ] Step 6: state store, event payload'ına secret yazılmasını protocol.redact ile zorunlu hale getirsin.

Live check:

    python3 -m services.agentd.state

Expected: VDS var/agentd altında kalıcı state ve event dosyaları oluşur; aynı store ikinci açılışta seq ve agent kimliklerini korur.

---

### Task 3: Gerçek uzak worker

Files:
- Create: services/agentd/worker.py

Interfaces:
- run_worker(agent_id: str, job_id: str, kind: str, root: str) -> int
- emit_worker_event(event_type: str, working_note: str, **fields) -> None
- worker stop signal handlers for SIGTERM and SIGINT.

Worker davranışı:

- Başlarken agent_started event'i stdout'a JSONL verir.
- Supervisor'ın verdiği event pipe/socket adresine gerçek eventleri gönderir.
- Her bekleme döngüsünde sahte nabız yazmaz; yalnız bir araç gözlemi, karar, hata veya operator komutu için event üretir.
- kind=gezinme ise mevcut AI tool registry entegrasyonuna girecek açık çalışma notu üretir; sabit CIDR/port if-else seçimi yapmaz.
- kind=keşif ise boş girdiyi geçerli başlangıç kabul eder; hedefi AI tool loop belirlemeden scanner başlatmaz.
- SIGTERM alındığında stopping ve stopped event'i üretir; SIGKILL için supervisor sonlandırma kanıtını kendisi ekler.
- Worker kendi başına yeniden doğmaz veya başka worker spawn etmez.

- [ ] Step 1: Worker stdout event formatını protocol ile aynı yap.
- [ ] Step 2: Parent PID, own PID ve process-group bilgilerini başlangıç eventine ekle.
- [ ] Step 3: Signal handler'ı idempotent yap; ikinci sinyalde event yazmayı beklemeden çık.
- [ ] Step 4: Çalışma notunu gerçek yapılan eylemden üret; timer tabanlı araştırıyor döngüsü ekleme.
- [ ] Step 5: Parent pipe kapanınca worker stale durum event'i üretip güvenli şekilde sonlansın.

Live check:

    python3 -m services.agentd.worker --agent-id canlı-deneme --job-id iş-deneme --kind gezinme --root var/agentd

Expected: gerçek worker PID'i görünür, JSONL eventleri akar, Ctrl-C sonrası stopped event'i gelir ve child süreç kalmaz.

---

### Task 4: Supervisor ve gerçek proses yaşam döngüsü

Files:
- Create: services/agentd/supervisor.py
- Create: services/agentd/__main__.py

Interfaces:
- Supervisor(root: Path, host: str = "127.0.0.1", port: int = 8787)
- Supervisor.handle(command: dict) -> dict
- Supervisor.start() -> None
- Supervisor.stop() -> None

Komut sonuçları:

- status: agents, last_seq, supervisor_pid, uptime.
- create: agent_id, job_id, pet, state=created.
- start: gerçek worker PID ve process_group ile state=running.
- pause: uzak process group'a SIGSTOP ve state=paused.
- resume: SIGCONT ve state=running.
- hard_kill: SIGTERM, grace window, kalan gruba SIGKILL, PID yokluk doğrulaması, state=killed.
- destroy: yalnız terminal/paused state için aktif kaydı kaldır; events ve kanıt manifestini bırak.
- subscribe: last_seq sonrasındaki eventleri ve ardından canlı eventleri JSONL stream olarak gönder.
- replay: agent_id ve seq/time aralığına göre event + frame/video referanslarını döndür.

- [ ] Step 1: TCP loopback sunucusunu asyncio.start_server ile kur; her bağlantı command başına bir JSON satırı okusun.
- [ ] Step 2: Her client connection için request_id eşleştirmesi ve görünür command_received/command_completed eventleri yaz.
- [ ] Step 3: create/start sırasında subprocess.Popen([...], start_new_session=True, stdout=PIPE, stderr=PIPE, text=True) kullan; pid ve process_group'u state'e yaz.
- [ ] Step 4: stdout/stderr okuyucularını ayrı daemon thread veya asyncio task ile supervisor event bus'a aktar; stderr'i kaybetme.
- [ ] Step 5: hard_kill için os.killpg kullan; grace sonrası group_exists kontrolü yap; state'i yalnız gerçekten sonlandıktan sonra killed yap.
- [ ] Step 6: supervisor kapanırken running workerları sessizce bırakma; shutdown event'i üret ve recovery state'i kalıcılaştır.
- [ ] Step 7: destroy komutu event/video/kanıt dosyalarını silmesin; yalnız aktif liste görünümünden düşürsün.
- [ ] Step 8: client disconnect supervisor işini durdurmasın; event store'a yazmaya devam etsin.

Live check:

    python3 -m services.agentd --root /home/mani/paidproxy-otomasyon/var/agentd --port 8787

Ayrı terminalde yalnız gerçek komut istemcisiyle:

    python3 - <<'PY'
    import json, socket
    s = socket.create_connection(("127.0.0.1", 8787), timeout=5)
    def call(body):
        s.sendall((json.dumps(body) + "\n").encode())
        return s.makefile("r", encoding="utf-8").readline().strip()
    print(call({"request_id":"r1","command":"create","kind":"gezinme","label":"canli-ajan"}))
    print(call({"request_id":"r2","command":"start","agent_id":"ajan-001"}))
    PY

Expected: returned PID VDS'de pgrep ile eşleşir; status state=running; command disconnect edilse de worker çalışır; supervisor hard_kill ile PID ve process group yok olur.

---

### Task 5: VDS systemd kurulumu

Files:
- Create: ops/systemd/paidproxy-agentd.service
- Create: ops/vds/install-agentd.sh
- Modify: ops/vds/bootstrap-trixie-arm64.sh

Service contract:

    [Service]
    Type=simple
    User=mani
    WorkingDirectory=/home/mani/paidproxy-otomasyon
    ExecStart=/usr/bin/python3 -m services.agentd --root /home/mani/paidproxy-otomasyon/var/agentd --host 127.0.0.1 --port 8787
    Restart=on-failure
    NoNewPrivileges=true
    PrivateTmp=true
    ProtectSystem=strict
    ReadWritePaths=/home/mani/paidproxy-otomasyon/var/agentd
    KillMode=control-group
    TimeoutStopSec=15

- [ ] Step 1: install-agentd.sh VDS checkout yolunu doğrulasın; beklenen dosya yoksa kurulum yapmadan görünür hata dönsün.
- [ ] Step 2: systemd unit'i /etc/systemd/system/paidproxy-agentd.service içine kopyalasın ve daemon-reload yapsın.
- [ ] Step 3: enable/start sonrası systemctl is-active ve ss ile yalnız 127.0.0.1:8787 dinlediğini gösteren çıktıyı üretsin.
- [ ] Step 4: kurulum scripti hiçbir secret istemesin veya kaydetmesin.
- [ ] Step 5: bootstrap mevcut tinyproxy veya başka servislere dokunmasın; yalnız agentd kurulumunu eklesin.

Live VDS deployment:

    rsync -a --exclude .git --exclude .venv ./services ./ops ./desktop /home/mani/paidproxy-otomasyon/
    ssh mani@20.207.198.170 'cd /home/mani/paidproxy-otomasyon && sudo bash ops/vds/install-agentd.sh'

Expected: VDS'de paidproxy-agentd active, PID visible, loopback port 8787 listening, service restart sonrası terminal killed job yeniden başlamıyor.

---

### Task 6: SSH port-forward istemcisi

Files:
- Create: desktop/app/agentd_client.py
- Modify: desktop/app/vds.py

Interfaces:
- RemoteAgentClient(config: VDSConfig)
- connect() -> None
- close() -> None
- request(command: str, **payload) -> dict
- subscribe(after_seq: int = 0, agent_id: str | None = None) -> Iterator[dict]
- hard_kill(agent_id: str, reason: str) -> dict
- replay(agent_id: str, after_seq: int = 0) -> list[dict]

- [ ] Step 1: vds.py, ssh -N -L local_port:127.0.0.1:8787 mani@host prosesini Popen ile başlatsın; local portu kullanılabilir olmadan client ready dönmesin.
- [ ] Step 2: SSH stderr ve returncode event/log olarak görünür olsun; timeout sessizce yutulmasın.
- [ ] Step 3: Agent client JSONL socket bağlantısını QThread dışındaki worker thread'de kullansın.
- [ ] Step 4: reconnect, son alınan seq üzerinden subscribe yapsın; aynı event iki kere gösterilirse UI cache deduplicate etsin.
- [ ] Step 5: remote request hata dönerse yerel store status değiştirmesin.
- [ ] Step 6: SSH close sırasında yalnız kendi port-forward child process'ini kapatsın; VDS supervisor veya ajanlara sinyal göndermesin.

Live check:

    ./desktop-launch

Expected: masaüstünde VDS connected ve supervisor healthy görülür; SSH port-forward PID'i yerelde, agentd PID'i VDS'de ayrı görünür; desktop kapanınca VDS worker devam eder.

---

### Task 7: Native masaüstünü remote source-of-truth'a geçirmek

Files:
- Modify: desktop/app/store.py
- Modify: desktop/app/main.py
- Modify: desktop/app/yoldas.py
- Create: desktop/app/remote_worker.py

- [ ] Step 1: MainWindow açılışında local store.create ile sahte ajan yaratmayı kaldır; status çağrısından gerçek uzak ajanları yükle.
- [ ] Step 2: Yarat düğmesi remote create + start komutunu göndersin ve dönen agent_id/job_id/pid/pet'i listeye eklesin.
- [ ] Step 3: Pause/resume/kill/destroy düğmeleri yalnız remote sonucu geldikten sonra UI state'i güncellesin.
- [ ] Step 4: _act seçimsiz durumda QMessageBox import hatasını giderip görünür seçim uyarısı versin; remote bağlantı yoksa “VDS bağlantısı yok” yazsın.
- [ ] Step 5: tick içindeki p.nabiz() çağrısını kaldır; pet ve status yalnız event akışından beslensin.
- [ ] Step 6: canlı düşünce paneli working_note, hypothesis, evidence_refs ve next_action alanlarını gerçek eventten göstersin.
- [ ] Step 7: pet click ve tencere düğmesi aynı remote hard_kill komutunu kullansın.
- [ ] Step 8: destroy aktif listeyi temizlese bile replay erişimini ve olay manifestini korusun.
- [ ] Step 9: yerel on_otonom ve on_canli akışlarını doğrudan VDS supervisor create/start komutuna taşı; yerel proxy_pipeline.yurut çağrısı operasyon başlatmasın.

Live check:

    ./desktop-launch

UI üzerinde:

    1. Yeni ajan yarat.
    2. VDS PID ve pet görünene kadar event akışını izle.
    3. Tencere düğmesine bas.
    4. VDS'de ilgili PID/process-group yokluğunu ve UI'de killed eventini gör.
    5. Uygulamayı kapatıp aç; terminal kayıt ve pet kimliği replay ile geri gelsin.

---

### Task 8: Event replay, viewport ve video yüzeyi

Files:
- Create: desktop/app/viewport.py
- Modify: desktop/app/film.py
- Modify: desktop/app/goz.py
- Modify: desktop/app/main.py
- Modify: services/agentd/state.py
- Modify: services/agentd/supervisor.py

- [ ] Step 1: Supervisor viewport command'ı yalnız VDS agent frame/video manifestlerini döndürsün; yerel ekran görüntüsünü ajan görüntüsü saymasın.
- [ ] Step 2: VDS frame writer her kareyi agent_id ve seq ile isimlendirsin; manifest event'e frame_ref yazsın.
- [ ] Step 3: İlk canlı yüzey frame_ref yoksa “frame unavailable” gösterip sahte görüntü üretmesin.
- [ ] Step 4: FilmSeridi gerçek VDS segmentlerini ve olay zamanlarını listelesin; tıklanan event ilgili frame/video offsetine gitsin.
- [ ] Step 5: Günlük/gez paneli global dosya yerine seçili remote agent replay akışını kullansın.
- [ ] Step 6: Desktop yeniden bağlanınca last_seq'den eventleri alıp viewport timeline'ı doldursun.
- [ ] Step 7: video segmentleri VDS'de kalıcı, yerelde cache; kullanıcı isterse yerel sonuç teslimine kopyalansın.

Live check:

    VDS'de çalışan agent ile masaüstünden canlı frame/video alanını aç; frame_ref, seq ve VDS dosya yolu birlikte görünmeli. Agent eventinde frame yoksa UI boşluğu dürüstçe göstermeli.

---

### Task 9: AI-native tool loop entegrasyonu

Files:
- Create: services/agentd/tools/catalog.py
- Create: services/agentd/tools/context.py
- Create: services/agentd/tools/runner.py
- Create: services/agentd/ai_loop.py
- Modify: services/agentd/worker.py
- Modify: src/proxy_pipeline/agents/ai_havuz.py
- Modify: src/proxy_pipeline/agents/wander.py
- Modify: src/proxy_pipeline/otonom.py
- Modify: src/proxy_pipeline/uzak_tara.py

Interfaces:
- ToolCatalog.register(name: str, description: str, handler, capabilities) -> None
- ToolCatalog.describe() -> list[dict]
- ToolRunner.invoke(agent_id: str, tool_name: str, arguments: dict) -> ToolResult
- AILoop.run(context: AgentContext) -> None
- AILoop.reflect(observation: dict) -> Reflection
- AILoop.next_action(reflection: Reflection) -> ActionRequest

Tool catalog başlangıcı:

- owner_range_lookup
- asn_prefix_observe
- rdap_bgp_observe
- web_page_observe
- passive_signal_observe
- liveness_probe
- vertical_port_probe
- protocol_probe
- target_request_probe
- evidence_commit
- reflection_note

- [ ] Step 1: AI prompt, araç listesini ve mevcut kanıt/karşı kanıtı almalı; karar tek çağrı JSON'u olmayacak.
- [ ] Step 2: Her tool invocation öncesi tool_started, sonrası tool_finished/error event'i yaz.
- [ ] Step 3: Ajan bir sonraki aracı ve port/range stratejisini gözlem kanıtına göre seçsin; 8080/3128/1080 fallback'i kaldır.
- [ ] Step 4: Masscan yalnız AI'nın belirlediği liveness işinde çalışsın; canlı IP'lerde dikey port ve protokol araçları ayrı event zincirine sahip olsun.
- [ ] Step 5: HTTP forward/CONNECT, Squid, SOCKS4/4a/5 ve olası rotate/residential sinyallerini ayrı kanıt alanlarıyla sakla.
- [ ] Step 6: target_request_probe gerçek hedef isteğini ve VDS egress IP'sini saklamadan redakte edilmiş kanıtla kaydetsin.
- [ ] Step 7: AILoop reflection, hypothesis, counter_hypothesis ve next_action alanlarını doldursun; sabit WanderAgent if/else akışını kaldır.
- [ ] Step 8: boş girişte AILoop araştırma ile başlayabilsin; kullanıcı seed girmeden worker çalışsın.
- [ ] Step 9: AI route yoksa görev sahte ilerleme üretmeden açıkça blocked event'i yazsın.
- [ ] Step 10: proxy teslimi yalnız handshake + gerçek hedef + egress + zaman damgası kanıtı tamamlanınca yapılsın.

Live VDS check:

    Desktop'tan boş girdili bir ajan başlat; supervisor event stream'de gerçek araç isimleri, hedefler, port kararları, reflection ve kanıt referanslarını canlı izle. TCP açık olup L7 başarısız olan adayın teslimata girmediğini VDS envanterinden doğrula.

---

### Task 10: VDS canlı kabul koşusu ve bağımsız inceleme

Files:
- Modify: reports/2026-09-05-vds-merkezli-operasyon-arastirmasi.md
- Modify: backlog/BACKLOG.md
- Create: reports/2026-09-05-vds-agentd-live-acceptance.md

- [ ] Step 1: systemctl ile agentd active durumunu ve gerçek supervisor PID'sini kaydet.
- [ ] Step 2: Masaüstünden iki gerçek ajan yarat; her birinin remote PID, process-group ve pet kimliğini event akışında kaydet.
- [ ] Step 3: Bir ajanı pause/resume et; VDS'de process state değişimini ve UI eventini birlikte kaydet.
- [ ] Step 4: Bir ajanı tencere komutuyla sert öldür; VDS'de PID/process-group yokluğunu ve terminal event'i kaydet.
- [ ] Step 5: Desktop bağlantısını kapat; VDS ajanının devam ettiğini, yeniden açınca seq/replay ile geri geldiğini kaydet.
- [ ] Step 6: Gerçek VDS viewport/video segmenti ve olay zaman eşleşmesini kaydet.
- [ ] Step 7: Boş girdili AI ajanında gerçek araç olayları, reflection ve kanıt zincirini kaydet.
- [ ] Step 8: Yalnız tam L7 + gerçek hedef + egress kanıtı bulunan proxyleri sonuç teslim kanalından al.
- [ ] Step 9: Sonuçları requirement-by-requirement incele; kanıt yoksa tamamlandı iddiası yazma.
- [ ] Step 10: Bu koşu bitmeden goal tamamlandı olarak işaretlenmesin.

Live acceptance output:

    reports/2026-09-05-vds-agentd-live-acceptance.md

Report fields:

- VDS hostname, architecture, supervisor service and PID;
- agent/job/PID/process-group table;
- event seq range and reconnect evidence;
- pause/resume/kill evidence;
- viewport/video/frame references;
- AI tool and reflection sequence;
- delivered proxy evidence references;
- unmet requirements and next concrete action.

