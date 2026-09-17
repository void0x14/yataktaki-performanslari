import { invoke } from '@tauri-apps/api/core';
import { listen } from '@tauri-apps/api/event';
import { createElement, Search, Plus, SlidersHorizontal, Command, Monitor, Terminal, Folder, Globe, Cpu, MousePointer2, Hand, Crosshair, CookingPot, Keyboard, Maximize2, Eye, RotateCcw, GitBranch, Pause, Square, Camera, MousePointerClick, Send, ChevronLeft, ChevronRight, Radio, AlertTriangle, CircleDot } from 'lucide';
import './styles.css';
import './observability.css';
import { checkedResponse, eventCursor, mergeEvents, mergeEventsChunked, evidenceImageRef } from './observability';

type Agent = Record<string, any>;
type EventRow = Record<string, any>;

const icons: Record<string, any> = { Search, Plus, SlidersHorizontal, Command, Monitor, Terminal, Folder, Globe, Cpu, MousePointer2, Hand, Crosshair, CookingPot, Keyboard, Maximize2, Eye, RotateCcw, GitBranch, Pause, Square, Camera, MousePointerClick, Send, ChevronLeft, ChevronRight, Radio, AlertTriangle, CircleDot };
const state = {
  agents: [] as Agent[], selected: '', events: [] as EventRow[], owner: 'agent', tool: 'cursor',
  connected: false, liveState: '', frameCount: 0, inspectIndex: -1, inspectDataUrl: '', frameCache: new Map<string, string>(),
  filter: 'all', eventFilter: 'all', activeTab: 'activity', pending: new Set<string>(),
  hasLiveImage: false, lastFrameAt: 0, liveFps: 0, liveResolution: '',
  zoom: 1, zoomX: 0, zoomY: 0, panning: false, panStartX: 0, panStartY: 0,
  harvestProxies: [] as Agent[],
  harvestStats: { open_ports: 0, total_live: 0, v6_count: 0, rotate_count: 0 },
};
let liveFrameQueued: {state?:string;detail?:string;width?:number;height?:number;image?:string;seq?:number;fps?:number;ts?:number} | null = null;
let lastMouseSend = 0;
let refreshing = false;
let replaying = false;

const esc = (v: unknown) => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]!));
const icon = (name: string, size=15) => `<i data-lucide="${name}" style="width:${size}px;height:${size}px"></i>`;
const time = (v: unknown) => { const s=String(v||''); return s.length >= 19 ? s.slice(11,19) : '—'; };
const category = (e: EventRow) => {
  const t=String(e.event_type||'');
  if(t.includes('error')||t.includes('unavailable')) return 'error';
  if(t.includes('frame')||t.includes('screenshot')||t.includes('video')) return 'evidence';
  if(t.includes('mouse')) return 'mouse'; if(t.includes('key')) return 'keyboard';
  if(t.includes('navigation')||t.includes('page')) return 'navigation';
  if(t.includes('intervention')||t.includes('directive')) return 'intervention';
  if(t.includes('tool')) return 'tool'; return 'thinking';
};
const selected = () => state.agents.find(a => a.agent_id === state.selected);
const humanControl = () => state.owner === 'human' && state.liveState === 'LIVE';

async function call(command: string, payload: Record<string, unknown> = {}, quiet=false) {
  // Tıklama anında tepki ver: düğme hemen basılmış görünür, sonuç sonra gelir.
  if(!quiet)setStatus(`${command} · gönderildi`);
  const timer = window.setTimeout(()=>{if(!quiet)setStatus(`${command} · VDS yanıtı bekleniyor (uzun sürerse pencere kilitlenmez)`);}, 1500);
  try {
    const result = checkedResponse(await invoke<any>('agentd', { command, payload }));
    if(!quiet)setStatus(`${command} · tamamlandı`);
    return result;
  } catch (error) {
    setStatus(`Bağlantı hatası · ${String(error)}`, true);
    throw error;
  } finally {
    window.clearTimeout(timer);
  }
}

function appShell() {
  document.querySelector<HTMLDivElement>('#app')!.innerHTML = `
  <main class="app-shell">
    <header class="topbar">
      <div class="brand"><span class="brand-mark">P</span><div><b>PAIDPROXY</b><span>OPERASYON KOKPİTİ</span></div></div>
      <div class="agent-glance"><span class="presence"></span><div><b id="glance-name">Ajan seçilmedi</b><small id="glance-action">Canlı durum bekleniyor</small></div></div>
      <div class="top-actions"><span class="connection" id="connection">${icon('Radio')} VDS BAĞLANIYOR</span><button data-action="create" class="primary">${icon('Plus')} Yeni ajan</button></div>
    </header>
    <section class="cockpit">
      <aside class="agent-rail">
        <div class="rail-head"><b>AJANLAR</b><span id="agent-count">0</span></div>
        <label class="search">${icon('Search')}<input id="agent-search" placeholder="Ajan ara..."/></label>
        <div class="filters"><button class="active" data-filter="all">Tümü</button><button data-filter="running">Çalışıyor</button><button data-filter="paused">Bekleyen</button><button data-filter="failed">Hata</button></div>
        <div class="agent-list" id="agent-list"><div class="empty-list">VDS ajanları bekleniyor</div></div>
        <nav class="rail-tools"><small>ARAÇLAR</small><button data-action="palette">${icon('Command')} Komut Paleti <kbd>Ctrl K</kbd></button><button data-tab="evidence">${icon('Folder')} Dosyalar</button></nav>
      </aside>
      <section class="main-column">
        <div class="view-tabs"><button class="active" data-tab="live">${icon('Monitor')} Canlı VDS</button><button data-tab="evidence">${icon('Folder')} Kanıtlar</button><span id="display-state">● HAZIR</span></div>
        <div class="viewport" id="viewport" tabindex="0">
          <div class="browser-chrome"><span></span><span></span><span></span><div id="target-url">VDS görüntüsü bekleniyor</div></div>
          <div class="screen" id="screen"><img id="live-frame" alt="" hidden/><div class="screen-loader" id="screen-loader" hidden><i></i><span>Canlı VDS akışı kuruluyor…</span></div><div class="screen-empty" id="screen-empty"><b>CANLI VDS</b><span id="screen-note">Gerçek WayVNC görüntüsü bekleniyor</span></div><div class="agent-cursor" id="agent-cursor">◆<em>AJAN</em></div><div class="human-cursor" id="human-cursor">↖<em>SİZ</em></div><div class="bonk" id="bonk">BONK!</div></div>
          <div class="floating-tools">
            <button class="active" data-tool="cursor" title="Cursor">${icon('MousePointer2',16)}</button><button data-tool="pan" title="Pan">${icon('Hand',16)}</button><button data-tool="target" title="Hedef göster">${icon('Crosshair',16)}</button><button data-tool="tencere" class="tencere" title="Tencere">${icon('CookingPot',16)}</button><button data-tool="keyboard" title="Klavye">${icon('Keyboard',16)}</button><button data-action="fullscreen" title="Tam ekran">${icon('Maximize2',16)}</button>
          </div>
          <div class="viewport-foot"><span id="live-pill"><i></i> Canlı</span><span id="stream-latency">gecikme —</span><span id="stream-fps">— fps</span><b id="resolution">—</b></div>
        </div>
        <section class="replay"><div class="replay-head"><b>FRAME / REPLAY</b><span id="replay-position">Kayıt yok</span><div><button data-action="prev">${icon('ChevronLeft')}</button><button data-action="next">${icon('ChevronRight')}</button><button data-action="live" class="live-button">● Canlıya dön</button></div></div><div class="frame-strip" id="frame-strip"><div class="empty-frame">Gerçek frame event'i bekleniyor</div></div><div class="scrubber" id="scrubber" role="slider" aria-label="Zaman çizelgesi" tabindex="0"><div class="scrubber-track" id="scrubber-track"><div class="scrubber-fill" id="scrubber-fill"></div><div class="scrubber-thumb" id="scrubber-thumb"></div></div><input id="scrub" type="range" min="0" max="0" value="0" tabindex="-1"/></div></section>
        <section class="workspace">
          <div class="workspace-tabs"><button class="active" data-tab="activity">Ajan Aktiviteleri</button><button data-tab="proxies">Canlı Proxyler (<span id="tab-proxy-count">0</span>)</button><button data-tab="evidence">Kanıtlar</button><button data-tab="logs">Loglar</button></div>
          <div class="workspace-body"><div class="activity-pane"><div class="event-filters"><button class="active" data-event-filter="all">Tümü</button><button data-event-filter="thinking">Düşünce</button><button data-event-filter="intervention">Eylem</button><button data-event-filter="tool">Araç</button><button data-event-filter="error">Hata</button></div><div id="event-list" class="event-list"><div class="empty-event">Bir ajan seçildiğinde gerçek olay akışı burada görünür.</div></div></div><aside class="inspector"><div class="inspector-tabs"><b>Görüntü</b><span>Ham Veri</span><span>Analiz</span></div><div class="preview" id="preview" title="Büyütmek için tıkla"><img id="preview-img" alt="" hidden/><span id="preview-text">FRAME ÖNİZLEMESİ</span><span class="preview-hint" id="preview-hint" hidden>Büyüt ⤢</span></div><dl id="metadata"><div><dt>Zaman</dt><dd>—</dd></div><div><dt>Eylem</dt><dd>—</dd></div><div><dt>Ajan</dt><dd>—</dd></div><div><dt>Dosya</dt><dd>—</dd></div></dl></aside></div>
        </section>
      </section>
      <aside class="control-panel">
        <div class="control-head"><div class="avatar">✦</div><div><small>SEÇİLİ AJAN</small><h2 id="detail-name">Ajan seçilmedi</h2><p id="detail-id">—</p></div><span class="state-pill" id="detail-state">OFFLINE</span></div>
        <section class="goal"><header><span>HEDEF</span><b id="progress">—</b></header><p id="goal">Ajan hedefi bekleniyor.</p><div class="progress"><i id="progress-bar"></i></div></section>
        <section class="facts"><label>ŞU AN NEREDE</label><p id="where-looking">Henüz gerçek hedef/kaynak seçilmedi.</p><label>NEDEN / İLK DİŞ</label><p id="why-first-bite">Henüz koku veya ilk diş kanıtı yok.</p><label>KAN / LİSTEDE</label><p id="blood-list">Henüz L7 + gerçek çıkış kanıtı yok; doğrulanmış liste boş.</p><label>MEVCUT ADIM</label><p id="current-step">—</p><label>SON EYLEM</label><p id="last-action">—</p><label>ENGEL / SEBEP</label><p class="blocker" id="blocker">Engel bildirilmedi</p></section>
        <section class="actions"><label>AKSİYONLAR</label><div class="action-grid"><button data-action="watch">${icon('Eye')} Gözlemle</button><button data-command="start">${icon('Radio')} Başlat</button><button data-command="resume">${icon('RotateCcw')} Devam Et</button><button data-action="retry">${icon('RotateCcw')} Yeniden Dene</button><button data-action="redirect">${icon('GitBranch')} Yönlendir</button><button data-action="take" class="take">${icon('MousePointerClick')} Kontrolü Al</button><button data-command="pause">${icon('Pause')} Duraklat</button><button data-command="hard_kill" class="danger">${icon('Square')} Durdur</button><button data-command="destroy" class="danger">${icon('Square')} Yok Et</button></div></section>
        <section class="proxy-results"><header><label>DOĞRULANMIŞ ÇIKIŞLAR</label><b id="proxy-count">0</b></header><div id="proxy-list" class="proxy-list"><div class="empty-event">Gerçek L7 + çıkış kanıtı bekleniyor.</div></div><button id="proxy-export" data-action="proxy-export" class="proxy-export">Export doğrulanmış liste</button></section>
        <section class="quick"><label>HIZLI KOMUTLAR & MÜDAHALE</label><div><button data-instruction="BU BLOĞU GEÇ; YENİ CIDR VEYA ASN'E GEÇ.">Bloğu Geç</button><button data-instruction="ACİL DURDUR; MEVCUT TARAMAYI KES.">Acil Kes</button><button data-instruction="Sayfayı yenile ve sonucu gözlemle.">Sayfayı yenile</button><button data-instruction="İşaretli hedefe tıkla.">Tıkla</button><button data-instruction="Klavye girdisini doğrula.">Yaz</button><button data-instruction="Sayfayı kontrollü biçimde kaydır.">Kaydır</button><button data-command="viewport">${icon('Camera')} Görüntü al</button></div></section>
        <section class="composer"><label>AJANI UYAR</label><div><textarea id="instruction" placeholder="Bu ajana ne yapacağını söyle..."></textarea><button data-action="send">${icon('Send')}</button></div></section>
        <div class="owner"><span>KONTROL</span><b id="owner">AJAN</b><button data-action="return">Ajana geri ver</button></div>
      </aside>
    </section>
    <footer id="status">VDS bağlantısı kuruluyor…</footer>
  </main>
  <div class="palette-backdrop" id="palette-backdrop" hidden></div>
  <div class="palette" id="palette" role="dialog" aria-modal="true" aria-label="Komut Paleti"><div><b>KOMUT PALETİ</b><span class="modal-actions"><kbd>ESC</kbd><button class="modal-close" data-action="palette-close" aria-label="Kapat">✕</button></span></div><input id="palette-input" placeholder="Komut ara..." autofocus/><button data-action="select">Ajan seç</button><button data-command="viewport">Observe</button><button data-command="pause">Pause</button><button data-command="hard_kill">Stop</button><button data-action="retry">Retry</button><button data-action="take">Kontrolü al</button><button data-action="return">Ajana geri ver</button><button data-command="replay">Replay aç</button><button data-tab="evidence">Evidence aç</button><button data-action="focus-command">Komut gönder</button></div>
  <div class="modal-backdrop" id="create-backdrop" hidden></div>
  <div class="modal" id="create-modal" role="dialog" aria-modal="true" aria-labelledby="create-title" hidden>
    <div class="modal-head"><b id="create-title">YENİ AJAN</b><button class="modal-close" data-action="create-close" aria-label="Kapat">✕</button></div>
    <label class="field"><span>Ajan adı</span><input id="create-name" placeholder="Örn. Kor-4536" autocomplete="off"/></label>
    <label class="field"><span>Yetenek</span>
      <div class="chip-group" id="create-kind">
        <button type="button" class="chip active" data-kind="gezinme">Gezinme</button>
        <button type="button" class="chip" data-kind="tarama">Tarama</button>
        <button type="button" class="chip" data-kind="l7">L7 Doğrulama</button>
        <button type="button" class="chip" data-kind="gorev">Görev</button>
      </div>
    </label>
    <label class="field"><span>İlk talimat <small>(isteğe bağlı)</small></span><textarea id="create-input" placeholder="Bu ajan ne yapsın?"></textarea></label>
    <p class="modal-error" id="create-error" hidden></p>
    <div class="modal-foot"><button class="ghost" data-action="create-close">Vazgeç</button><button class="primary" data-action="create-submit">Oluştur</button></div>
  </div>
  <div class="lightbox" id="lightbox" role="dialog" aria-modal="true" aria-label="Frame önizlemesi" hidden>
    <div class="lightbox-backdrop" data-action="lightbox-close"></div>
    <div class="lightbox-frame">
      <div class="lightbox-head"><div><b id="lightbox-title">FRAME</b><small id="lightbox-sub">—</small></div><div class="lightbox-tools"><button data-action="lb-zoom-out" title="Uzaklaştır">−</button><button data-action="lb-zoom-reset" title="Sıfırla" id="lb-zoom-label">100%</button><button data-action="lb-zoom-in" title="Yakınlaştır">+</button><button class="modal-close" data-action="lightbox-close" aria-label="Kapat">✕</button></div></div>
      <div class="lightbox-stage" id="lightbox-stage"><img id="lightbox-img" alt="" draggable="false"/></div>
      <div class="lightbox-meta"><pre id="lightbox-ocr"></pre><dl id="lightbox-info"></dl></div>
    </div>
  </div>`;
  const inspector=document.querySelector<HTMLElement>('.inspector')!;
  inspector.querySelector('.inspector-tabs')!.innerHTML='<b>Görüntü</b>';
  inspector.insertAdjacentHTML('beforeend','<details class="event-details"><summary>Seçili olayın ham verisi</summary><pre id="raw-event" class="raw-event">Olay seçilmedi.</pre></details>');
  text('display-state','● GÖRÜNTÜ BEKLENİYOR');
  document.querySelector('#live-pill')!.innerHTML='<i></i> Görüntü bekleniyor';
  updateStreamStatus();
  document.querySelector<HTMLElement>('#agent-cursor')!.hidden=true;
  bind(); refreshIcons();
}

function refreshIcons(){ document.querySelectorAll('i[data-lucide]').forEach(i => { const def = (icons as any)[i.getAttribute('data-lucide')!]; if (def) i.replaceWith(createElement(def)); }); }

function renderAgents() {
  const list=document.querySelector('#agent-list')!; const query=(document.querySelector<HTMLInputElement>('#agent-search')?.value||'').toLowerCase();
  const agents=state.agents.filter(a => {
    const matchesQuery = `${a.pet?.name||''} ${a.label||''} ${a.agent_id}`.toLowerCase().includes(query);
    const matchesFilter = state.filter === 'all'
      || (state.filter === 'running' && ['running','working','active'].includes(String(a.state).toLowerCase()))
      || (state.filter === 'paused' && ['paused','waiting','pending'].includes(String(a.state).toLowerCase()))
      || (state.filter === 'failed' && ['failed','error','blocked'].includes(String(a.state).toLowerCase()));
    return matchesQuery && matchesFilter;
  });
  document.querySelector('#agent-count')!.textContent=String(state.agents.length);
  list.innerHTML=agents.length ? agents.map(a => { const blocked=Boolean(a.blocker); const cls=blocked?'blocked':a.state==='failed'?'error':a.state==='paused'?'manual':a.state; return `<button class="agent ${cls} ${a.agent_id===state.selected?'selected':''}" data-agent="${esc(a.agent_id)}"><span class="agent-avatar">${blocked?'!':'✦'}</span><span><b>${esc(a.pet?.name||a.label||a.agent_id)}</b><small>${esc(a.working_note||a.current_tool||'Görev bekleniyor')}</small></span><em>${esc(a.state||'unknown')}</em></button>`; }).join('') : '<div class="empty-list">VDS ajanları bekleniyor</div>';
  list.querySelectorAll<HTMLElement>('[data-agent]').forEach(el=>el.onclick=()=>selectAgent(el.dataset.agent!));
}

function renderDetail() {
  renderProxies();
  const a=selected(); if(!a) return;
  const name=a.pet?.name||a.label||a.agent_id; const current=Number(a.progress?.current||a.progress_current||0), total=Number(a.progress?.total||a.progress_total||0);
  text('glance-name',name); text('glance-action',a.working_note||a.current_event_type||'İzleniyor'); text('detail-name',name); text('detail-id',`…${String(a.agent_id).slice(-10)} · ${a.kind||'VDS'}`); text('detail-state',String(a.state||'unknown').toUpperCase()); text('goal',a.current_target||a.label||'Hedef bildirilmedi'); text('progress',total?`${current}/${total}`:'—'); text('current-step',a.next_action||a.working_note||'—'); text('last-action',`${a.current_event_type||a.current_tool||'—'} · ${time(a.last_event_timestamp)}`); text('blocker',a.blocker||'Engel bildirilmedi'); text('target-url',a.current_target||'VDS görüntüsü bekleniyor'); renderHuntFacts(a);
  (document.querySelector('#progress-bar') as HTMLElement).style.width=total?`${Math.min(100,current/total*100)}%`:'0%'; renderEvents(); refreshIcons();
}
function summaryText(value: unknown): string {
  if (typeof value === 'string') return value.trim();
  if (!value || typeof value !== 'object') return '';
  const row=value as Record<string, unknown>;
  for (const key of ['working_note','summary','message','result']) {
    if (typeof row[key] === 'string' && row[key]) return String(row[key]);
  }
  return '';
}
function firstBite(a: Agent): string {
  const decision=(a.last_decision&&typeof a.last_decision==='object')?a.last_decision as Record<string,unknown>:{};
  const tools=Array.isArray(decision.requested_tools)?decision.requested_tools.map(String):[];
  const targets=Array.isArray(decision.targets)?decision.targets as Record<string,unknown>[]:[];
  const first=targets[0]||{};
  const ports=Array.isArray(first.ports)?first.ports.map(Number).filter(Boolean):[];
  if(tools.includes('browse_public_source')) return 'İlk diş: public-source koku taraması.';
  if(tools.includes('masscan_liveness')) return ports.length?`İlk diş: L4 tek port ${ports[0]}.`:'İlk diş: L4 tek ilk port; port kanıtı bekleniyor.';
  if(tools.includes('expand_live_ip')) return 'İlk diş: canlı IP üzerinde doğrudan socket dikeyi.';
  if(tools.includes('validate_proxy')) return 'İlk diş: L7 CONNECT/SOCKS ve gerçek çıkış doğrulaması.';
  return 'İlk diş henüz seçilmedi.';
}
function renderHuntFacts(a: Agent) {
  const last=state.events[state.events.length-1]||{};
  const where=String(a.current_target||last.target||'').trim();
  const hypothesis=String(a.hypothesis||'').trim();
  const result=summaryText(a.last_result_summary);
  const published=Array.isArray(a.published_proxies)?a.published_proxies.length:0;
  text('where-looking',where||'Henüz gerçek hedef/kaynak seçilmedi.');
  text('why-first-bite',[hypothesis,firstBite(a)].filter(Boolean).join(' · ')||'Henüz koku veya ilk diş kanıtı yok.');
  text('blood-list',published?`Kan var: ${published} doğrulanmış çıkış listede.`:result?`Son gerçek sonuç: ${result} · listede doğrulanmış çıkış yok.`:'Henüz L7 + gerçek çıkış kanıtı yok; doğrulanmış liste boş.');
}
function publishedProxies(): Agent[] {
  const seen = new Set<string>();
  const out: Agent[] = [];
  for (const proxy of state.harvestProxies) {
    const host = String(proxy.host || '');
    const port = Number(proxy.port || 0);
    if (!host || !port) continue;
    const identity = `${host}:${port}`;
    if (seen.has(identity)) continue;
    seen.add(identity);
    out.push(proxy);
  }
  for (const agent of state.agents) {
    for (const proxy of (Array.isArray(agent.published_proxies) ? agent.published_proxies : [])) {
      const host = String(proxy?.host || '');
      const port = Number(proxy?.port || 0);
      const protocol = String(proxy?.protocol || '');
      const validationRef = String(proxy?.validation_ref || '');
      if (!host || !port || !protocol || !validationRef) continue;
      const identity = `${host}:${port}:${protocol}:${validationRef}`;
      if (seen.has(identity)) continue;
      seen.add(identity);
      out.push({...proxy, agent_id: proxy.agent_id || agent.agent_id});
    }
  }
  return out;
}

function proxyLine(proxy: Agent): string {
  return `${proxy.host}:${proxy.port}`;
}

function renderProxies() {
  const list = document.querySelector('#proxy-list');
  const count = document.querySelector('#proxy-count');
  const tabCount = document.querySelector('#tab-proxy-count');
  const proxies = publishedProxies();
  if (count) count.textContent = String(proxies.length);
  if (tabCount) tabCount.textContent = String(proxies.length);
  if (!list) return;
  list.innerHTML = proxies.length ? proxies.slice(0, 100).map(proxy => {
    const line = proxyLine(proxy);
    return `<article class="proxy-row"><code>${esc(`${proxy.host}:${proxy.port}`)}</code><span>${esc(proxy.protocol)}</span><small>${esc(proxy.quality_label || 'doğrulandı')} · ${esc(proxy.validation_ref)}</small><button class="proxy-copy" data-proxy-copy="${esc(encodeURIComponent(line))}">Kopyala</button></article>`;
  }).join('') : '<div class="empty-event">Gerçek L7 + çıkış kanıtı bekleniyor.</div>';
  list.querySelectorAll<HTMLElement>('[data-proxy-copy]').forEach(button => button.onclick = async () => {
    const value = decodeURIComponent(button.dataset.proxyCopy || '');
    try {
      await navigator.clipboard.writeText(value);
      setStatus('Proxy panoya kopyalandı');
    } catch (error) {
      setStatus(`Kopyalama başarısız · ${String(error)}`, true);
    }
  });
}

function exportProxies() {
  const proxies = publishedProxies();
  if (!proxies.length) return setStatus('Export için doğrulanmış proxy yok', true);
  const blob = new Blob([proxies.map(p => `${p.host}:${p.port}`).join('\n') + '\n'], {type:'text/plain;charset=utf-8'});
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = `proxies-${new Date().toISOString().slice(0,10)}.txt`;
  anchor.click();
  URL.revokeObjectURL(url);
  setStatus(`${proxies.length} doğrulanmış proxy export edildi`);
}

async function loadHarvestData(force = false) {
  try {
    const res = await call('get_harvest_data', { force }, true);
    if (res && Array.isArray(res.proxies) && res.proxies.length) {
      state.harvestProxies = res.proxies.map((p: any) => {
        const parts = String(p.endpoint || '').split(':');
        const host = parts[0] || '';
        const port = Number(parts[1] || 0);
        return {
          host,
          port,
          protocol: p.protocol || 'HTTP',
          quality_label: `${p.version || ''} ${p.rotation || ''} ${p.type || ''}`.trim(),
          validation_ref: p.egress || 'egress-ok',
          agent_id: 'harvest',
        };
      });
      state.harvestStats = {
        open_ports: Number(res.open_ports || 0),
        total_live: Number(res.total_live || 0),
        v6_count: Number(res.v6_count || 0),
        rotate_count: Number(res.rotate_count || 0),
      };
      renderProxies();
      if (state.activeTab === 'proxies') renderEvents();
    }
  } catch {}
}

function renderEvents(){
  const list=document.querySelector('#event-list')!;
  if(state.activeTab==='proxies') {
    const proxies=publishedProxies();
    list.innerHTML=`
      <div style="padding:6px;display:flex;flex-direction:column;gap:5px;height:100%">
        <div style="display:flex;align-items:center;justify-content:space-between;padding-bottom:5px;border-bottom:1px solid #202c36">
          <b style="color:#55dfeb;font-size:11px">CANLI DOĞRULANMIŞ HAVUZ (${proxies.length.toLocaleString()})</b>
          <button class="proxy-export" data-action="proxy-export" style="width:auto;padding:3px 8px;font-size:9px">Listeyi İndir (.txt)</button>
        </div>
        <div style="flex:1;overflow:auto;display:flex;flex-direction:column;gap:3px">
          ${proxies.slice(0, 200).map(p => `
            <div style="display:flex;align-items:center;justify-content:space-between;padding:4px 7px;background:#101a22;border:1px solid #24343f;border-radius:4px;font-size:10px;font-family:monospace">
              <span style="color:#9bf1fa;font-weight:700">${esc(`${p.host}:${p.port}`)}</span>
              <span style="color:#d4b66e">${esc(p.protocol)}</span>
              <span style="color:#718491;max-width:220px;overflow:hidden;text-overflow:ellipsis">${esc(p.quality_label || '')}</span>
              <button class="proxy-copy" data-proxy-copy="${esc(encodeURIComponent(`${p.host}:${p.port}`))}" style="padding:2px 5px">Kopyala</button>
            </div>
          `).join('')}
        </div>
      </div>
    `;
    list.querySelectorAll<HTMLElement>('[data-proxy-copy]').forEach(b => {
      b.onclick = async () => {
        const v = decodeURIComponent(b.dataset.proxyCopy || '');
        await navigator.clipboard.writeText(v);
        setStatus('Kopyalandı: ' + v);
      };
    });
    list.querySelectorAll<HTMLElement>('[data-action="proxy-export"]').forEach(b => {
      b.onclick = () => exportProxies();
    });
    return;
  }
  if(state.activeTab==='logs') {
    list.innerHTML=`<pre class="raw-event">${esc(state.events.map(e=>JSON.stringify(e,null,2)).join('\n\n'))}</pre>`;
    renderFrames();
    return;
  }
  const rows=state.events.slice(-250).filter(e=>(state.activeTab!=='evidence'||Boolean(e.frame_ref||e.video_ref||e.output_ref||e.evidence_refs?.length))&&(state.eventFilter==='all'||category(e)===state.eventFilter));
  list.innerHTML=rows.length?rows.slice().reverse().map(e=>{const idx=state.events.indexOf(e); return `<button class="event ${category(e)}" data-event="${idx}"><i></i><span><b>${esc(e.event_type||'event')}</b><small>${esc(e.working_note||e.tool||e.target||'Olay kaydı')}</small></span><time>${time(e.timestamp)}</time></button>`;}).join(''):'<div class="empty-event">Bu filtrede olay yok.</div>';
  list.querySelectorAll<HTMLElement>('[data-event]').forEach(el=>el.onclick=()=>inspect(Number(el.dataset.event))); renderFrames();
}
function frameEvents(){ return state.events.filter(e=>Boolean(evidenceImageRef(e))); }
function renderFrames(){
  const frames=frameEvents(); const strip=document.querySelector('#frame-strip')!;
  strip.innerHTML=frames.length?frames.slice(-8).map(e=>{ const idx=state.events.indexOf(e); return `<button class="frame ${category(e)} ${idx===state.inspectIndex?'selected':''}" data-frame="${idx}"><img data-thumb="${esc(evidenceImageRef(e))}" alt=""/><b>#${esc(e.seq)}</b><small>${time(e.timestamp)}</small></button>`; }).join(''):'<div class="empty-frame">Gerçek frame veya Kahin OCR görsel kanıtı bekleniyor</div>';
  text('replay-position',frames.length?`${frames.length} gerçek kayıt`:'Kayıt yok');
  const scrub=document.querySelector<HTMLInputElement>('#scrub')!; scrub.max=String(Math.max(0,state.events.length-1)); scrub.value=String(Math.max(0,state.inspectIndex<0?state.events.length-1:state.inspectIndex));
  syncScrubberUI();
  strip.querySelectorAll<HTMLElement>('[data-frame]').forEach(el=>el.onclick=()=>inspect(Number(el.dataset.frame)));
  strip.querySelectorAll<HTMLImageElement>('[data-thumb]').forEach(img=>loadFrameRef(img.dataset.thumb!,'thumb'));
  refreshIcons();
}
function scrubRatio():number{
  const max=Math.max(0,state.events.length-1);
  const value=state.inspectIndex<0?max:state.inspectIndex;
  return max?Math.max(0,Math.min(1,value/max)):0;
}
function syncScrubberUI(){
  const ratio=scrubRatio();
  const fill=document.querySelector<HTMLElement>('#scrubber-fill');
  const thumb=document.querySelector<HTMLElement>('#scrubber-thumb');
  if(fill) fill.style.width=`${ratio*100}%`;
  if(thumb) thumb.style.left=`${ratio*100}%`;
}
let scrubFrame=0;
function requestScrub(index:number){
  if(scrubFrame) return;
  scrubFrame=requestAnimationFrame(()=>{
    scrubFrame=0;
    const clamped=Math.max(0,Math.min(state.events.length-1,index));
    if(state.events[clamped]) inspect(clamped);
  });
}
function bindScrubber(){
  const scrubber=document.querySelector<HTMLElement>('#scrubber')!;
  const track=document.querySelector<HTMLElement>('#scrubber-track')!;
  const indexFromClientX=(clientX:number)=>{
    const rect=track.getBoundingClientRect();
    const ratio=rect.width?Math.max(0,Math.min(1,(clientX-rect.left)/rect.width)):0;
    return Math.round(ratio*Math.max(0,state.events.length-1));
  };
  let scrubbing=false;
  const onPointerMove=(e:PointerEvent)=>requestScrub(indexFromClientX(e.clientX));
  track.addEventListener('pointerdown',e=>{ scrubbing=true; track.setPointerCapture(e.pointerId); onPointerMove(e); });
  track.addEventListener('pointermove',e=>{ if(scrubbing) onPointerMove(e); });
  const endScrub=(e:PointerEvent)=>{ if(!scrubbing) return; scrubbing=false; try{track.releasePointerCapture(e.pointerId);}catch{} };
  track.addEventListener('pointerup',endScrub); track.addEventListener('pointercancel',endScrub);
  // Trackpad: iki parmak yatay (deltaX) veya Shift+deltaY ile ilerle/geri sar.
  scrubber.addEventListener('wheel',e=>{
    e.preventDefault();
    const delta=Math.abs(e.deltaX)>Math.abs(e.deltaY)?e.deltaX:(e.shiftKey?e.deltaY:0);
    if(!delta) return;
    const step=delta>0?1:-1;
    const current=state.inspectIndex<0?state.events.length-1:state.inspectIndex;
    requestScrub(current+step);
  },{passive:false});
  // Klavye erişilebilirliği.
  scrubber.addEventListener('keydown',e=>{
    const current=state.inspectIndex<0?state.events.length-1:state.inspectIndex;
    if(e.key==='ArrowLeft'){e.preventDefault();requestScrub(current-1);}
    if(e.key==='ArrowRight'){e.preventDefault();requestScrub(current+1);}
    if(e.key==='Home'){e.preventDefault();requestScrub(0);}
    if(e.key==='End'){e.preventDefault();requestScrub(state.events.length-1);}
  });
}
async function frameDataUrl(frameRef:string,agentId:string):Promise<string|undefined>{
  const key=`${agentId}|${frameRef}`; const cached=state.frameCache.get(key); if(cached) return cached;
  const r=await invoke<any>('fetch_frame',{agentId,frameRef});
  if(r?.data_url){ if(state.frameCache.size>40){ const firstKey=state.frameCache.keys().next().value as string|undefined; if(firstKey!==undefined) state.frameCache.delete(firstKey); } state.frameCache.set(key,String(r.data_url)); return String(r.data_url); }
  return undefined;
}
let thumbInflight = 0;
const thumbQueue: Array<()=>void> = [];
function pumpThumbs(){
  while(thumbInflight < 2 && thumbQueue.length){
    const job = thumbQueue.shift()!;
    thumbInflight++;
    job();
  }
}
async function loadFrameRef(frameRef:string,purpose:'thumb'|'preview'){
  if(!frameRef||!state.selected) return;
  const agentId=state.selected;
  if(purpose==='thumb'){
    if(state.frameCache.has(`${agentId}|${frameRef}`)){ await loadFrameRefInner(frameRef,'thumb',agentId); return; }
    await new Promise<void>(resolve=>{
      thumbQueue.push(()=>{
        void (async()=>{
          try{ await loadFrameRefInner(frameRef,'thumb',agentId); }
          finally{ thumbInflight--; pumpThumbs(); resolve(); }
        })();
      });
      pumpThumbs();
    });
    return;
  }
  await loadFrameRefInner(frameRef,purpose,agentId);
}
async function loadFrameRefInner(frameRef:string,purpose:'thumb'|'preview',agentId:string){
  try{ const url=await frameDataUrl(frameRef,agentId);
    if(state.selected!==agentId) return;
    if(!url) return;
    if(purpose==='thumb'){ document.querySelectorAll<HTMLImageElement>(`[data-thumb="${CSS.escape(frameRef)}"]`).forEach(img=>{img.src=url;}); }
    else if(state.inspectDataUrl===frameRef){ const img=document.querySelector<HTMLImageElement>('#preview-img')!; img.src=url; img.hidden=false; const t=document.querySelector<HTMLElement>('#preview-text')!; t.hidden=true; const h=document.querySelector<HTMLElement>('#preview-hint'); if(h) h.hidden=false; const lb=document.querySelector<HTMLImageElement>('#lightbox-img'); if(lb&&!document.querySelector<HTMLElement>('#lightbox')?.hidden) lb.src=url; }
  }catch(error){ if(purpose==='preview'&&state.selected===agentId&&state.inspectDataUrl===frameRef){text('preview-text',`Görüntü alınamadı: ${String(error)}`);document.querySelector<HTMLElement>('#preview-text')!.hidden=false;} }
}
function inspect(index:number){
  const e=state.events[index]; if(!e) return;
  const imageRef=evidenceImageRef(e);
  state.inspectIndex=index; state.inspectDataUrl=imageRef;
  text('raw-event',JSON.stringify(e,null,2));
  text('preview-text',imageRef?(e.frame_ref?'GERÇEK FRAME':'KAHİN · MYIP.MS · GOOGLE VISION OCR KANITI'):'Bu event için görsel kanıt yok');
  const img=document.querySelector<HTMLImageElement>('#preview-img')!;
  if(imageRef){ img.hidden=true; loadFrameRef(imageRef,'preview'); } else { img.hidden=true; }
  const t=document.querySelector<HTMLElement>('#preview-text')!; t.hidden=false;
  const h=document.querySelector<HTMLElement>('#preview-hint'); if(h) h.hidden=!imageRef;
  if(!imageRef) closeLightbox();
  document.querySelector('#metadata')!.innerHTML=`<div><dt>Zaman</dt><dd>${esc(time(e.timestamp))}</dd></div><div><dt>Eylem</dt><dd>${esc(e.event_type)}</dd></div><div><dt>Ajan</dt><dd>${esc(e.agent_id)}</dd></div><div><dt>Dosya</dt><dd>${esc(imageRef||e.video_ref||'—')}</dd></div>`;
  renderFrames();
}
function lightboxApplyZoom(){
  const img=document.querySelector<HTMLImageElement>('#lightbox-img');
  if(img) img.style.transform=`translate(${state.zoomX}px,${state.zoomY}px) scale(${state.zoom})`;
  const label=document.querySelector('#lb-zoom-label');
  if(label) label.textContent=`${Math.round(state.zoom*100)}%`;
}
function openLightbox(){
  const event=state.events[state.inspectIndex];
  const ref=state.inspectDataUrl||(event?evidenceImageRef(event):'');
  if(!ref) return setStatus('Bu olay için görsel kanıt yok',true);
  state.zoom=1; state.zoomX=0; state.zoomY=0;
  const box=document.querySelector<HTMLElement>('#lightbox')!;
  const img=document.querySelector<HTMLImageElement>('#lightbox-img')!;
  const cached=state.frameCache.get(`${state.selected}|${ref}`);
  img.src=cached||'';
  if(!cached){ loadFrameRef(ref,'preview'); }
  const title=document.querySelector('#lightbox-title');
  const sub=document.querySelector('#lightbox-sub');
  if(title) title.textContent=event?.frame_ref?'GERÇEK FRAME':'KAHİN · OCR KANITI';
  if(sub) sub.textContent=ref;
  const ocr=document.querySelector('#lightbox-ocr');
  if(ocr) ocr.textContent=evidenceOcrText(event);
  const info=document.querySelector('#lightbox-info');
  if(info) info.innerHTML=`<div><dt>Zaman</dt><dd>${esc(time(event?.timestamp))}</dd></div><div><dt>Eylem</dt><dd>${esc(event?.event_type||'—')}</dd></div><div><dt>Ajan</dt><dd>${esc(event?.agent_id||'—')}</dd></div><div><dt>Dosya</dt><dd>${esc(ref)}</dd></div>`;
  box.hidden=false;
  lightboxApplyZoom();
  refreshIcons();
}
function evidenceOcrText(event:EventRow|undefined):string{
  if(!event) return 'Kanıt metni yok.';
  const candidates=[event.ocr_text,event.ocr,event.text,event.output_ref,summaryText(event.last_result_summary)];
  const found=candidates.find(v=>typeof v==='string'&&v.trim());
  return found?String(found):'Bu kare için OCR/kanıt metni kayıtlı değil.';
}
function closeLightbox(){ const box=document.querySelector<HTMLElement>('#lightbox'); if(box) box.hidden=true; }
function lbZoom(delta:number){
  state.zoom=Math.max(0.25,Math.min(6,state.zoom+delta));
  if(state.zoom===1){ state.zoomX=0; state.zoomY=0; }
  lightboxApplyZoom();
}
function bindLightbox(){
  const stage=document.querySelector<HTMLElement>('#lightbox-stage')!;
  stage.addEventListener('wheel',e=>{
    e.preventDefault();
    if(state.zoom<=1&&!e.ctrlKey) return;
    const rect=stage.getBoundingClientRect();
    const cx=e.clientX-rect.left-rect.width/2;
    const cy=e.clientY-rect.top-rect.height/2;
    const step=e.deltaY<0?1.12:1/1.12;
    state.zoom=Math.max(0.25,Math.min(6,state.zoom*step));
    state.zoomX-=cx*(step-1); state.zoomY-=cy*(step-1);
    lightboxApplyZoom();
  },{passive:false});
  stage.addEventListener('pointerdown',e=>{ if(state.zoom<=1) return; state.panning=true; state.panStartX=e.clientX-state.zoomX; state.panStartY=e.clientY-state.zoomY; stage.setPointerCapture(e.pointerId); stage.classList.add('grabbing'); });
  stage.addEventListener('pointermove',e=>{ if(!state.panning) return; state.zoomX=e.clientX-state.panStartX; state.zoomY=e.clientY-state.panStartY; lightboxApplyZoom(); });
  const stopPan=(e:PointerEvent)=>{ if(!state.panning) return; state.panning=false; try{stage.releasePointerCapture(e.pointerId);}catch{} stage.classList.remove('grabbing'); };
  stage.addEventListener('pointerup',stopPan); stage.addEventListener('pointercancel',stopPan);
  const img=document.querySelector<HTMLImageElement>('#lightbox-img')!;
  img.addEventListener('load',latelightboxLoad);
  img.addEventListener('error',()=>{ const ocr=document.querySelector('#lightbox-ocr'); if(ocr) ocr.textContent='Görüntü yüklenemedi.'; });
}
function latelightboxLoad(){ const e=state.events[state.inspectIndex]; const ref=state.inspectDataUrl||(e?evidenceImageRef(e):''); const url=state.frameCache.get(`${state.selected}|${ref}`); const img=document.querySelector<HTMLImageElement>('#lightbox-img'); if(img&&url&&img.src!==url) img.src=url; }
function detailSkeleton(){
  document.querySelector('#control-panel-loading')?.remove();
  const panel=document.querySelector('.control-panel')!;
  panel.classList.add('loading');
  const note=document.createElement('div');
  note.id='control-panel-loading'; note.className='panel-loading';
  note.innerHTML='<i></i><span>Ajan verisi yükleniyor…</span>';
  panel.insertBefore(note, panel.firstChild);
}
function detailLoaded(){
  document.querySelector('.control-panel')?.classList.remove('loading');
  document.querySelector('#control-panel-loading')?.remove();
}
async function selectAgent(id:string){
  // Optimistic UI: tıklama anında aktif/selected ve panel yükleniyor durumuna geçer.
  state.selected=id; state.events=[]; state.inspectIndex=-1; state.inspectDataUrl='';
  state.hasLiveImage=false; state.lastFrameAt=0; state.liveFps=0;
  text('raw-event','Olay seçilmedi.');
  document.querySelector<HTMLImageElement>('#preview-img')!.hidden=true;
  const hint=document.querySelector<HTMLElement>('#preview-hint'); if(hint) hint.hidden=true;
  showScreenLoader(true);
  renderAgents(); renderDetail(); detailSkeleton();
  void showLastFrameFallback();
  setStatus('Ajan seçildi · veriler paralel yükleniyor');
  // Tüm uzak işler izole async görevlerde: hiçbiri arayüzü bekletmez.
  const tasks:Promise<unknown>[] = [
    invoke('set_display_target',{agentId:id}).catch(()=>{}),
    // Decoupled live stream: live video connects on-demand when operator clicks "Gözlemle" or "Kontrolü Al"
    (async()=>{
      try{
        const r=checkedResponse(await invoke<any>('agentd',{command:'replay',payload:{agent_id:id,after_seq:0,limit:50}}));
        if(state.selected!==id) return;
        state.events=await mergeEventsChunked(state.events,Array.isArray(r.events)?r.events:[],id);
        if(state.selected!==id) return;
        renderDetail(); setStatus('Olaylar yüklendi');
        void showLastFrameFallback();
      }catch(err){ if(state.selected===id)setStatus(`Olaylar alınamadı · ${String(err)}`,true); }
      finally{ if(state.selected===id) detailLoaded(); }
    })(),
  ];
  await Promise.allSettled(tasks);
}
async function sendInstruction(instruction:string, context:Record<string,unknown>={}){ if(!state.selected||!instruction.trim()) return; const r=await call('intervene',{agent_id:state.selected,instruction,context}); if(r?.intervention_id) setStatus(`Yönlendirme kaydedildi · ${String(r.intervention_id).slice(0,18)}…`); }
function text(id:string,value:unknown){ const el=document.getElementById(id); if(el) el.textContent=String(value??''); }
function setStatus(message:string,error=false){ const el=document.querySelector('#status')!; el.textContent=message; el.classList.toggle('error',error); }
function showPalette(show=true){
  const palette=document.querySelector<HTMLElement>('#palette')!;
  const backdrop=document.querySelector<HTMLElement>('#palette-backdrop')!;
  palette.classList.toggle('open',show);
  backdrop.hidden=!show;
  if(show){ const input=document.querySelector<HTMLInputElement>('#palette-input'); input?.focus(); }
}
let createKind='gezinme';
function showCreateModal(show=true){
  const modal=document.querySelector<HTMLElement>('#create-modal')!;
  const backdrop=document.querySelector<HTMLElement>('#create-backdrop')!;
  modal.hidden=!show; backdrop.hidden=!show;
  const error=document.querySelector<HTMLElement>('#create-error'); if(error) error.hidden=true;
  if(show){
    const name=document.querySelector<HTMLInputElement>('#create-name'); if(name){ name.value=''; name.focus(); }
    const input=document.querySelector<HTMLTextAreaElement>('#create-input'); if(input) input.value='';
    createKind='gezinme';
    document.querySelectorAll('#create-kind .chip').forEach(c=>c.classList.toggle('active',(c as HTMLElement).dataset.kind==='gezinme'));
  }
}
function setTab(name:string){
  state.activeTab=name;
  document.querySelectorAll('[data-tab]').forEach(x=>x.classList.toggle('active',(x as HTMLElement).dataset.tab===name));
  document.querySelectorAll<HTMLElement>('[data-panel]').forEach(x=>x.hidden=x.dataset.panel!==name);
  if(name === 'live') document.querySelector<HTMLElement>('#viewport')?.removeAttribute('hidden');
  renderEvents();
  setStatus(`${name} görünümü açıldı`);
}
function setFilter(filter:string){
  state.filter=filter;
  document.querySelectorAll<HTMLElement>('[data-filter]').forEach(x=>x.classList.toggle('active',x.dataset.filter===filter));
  renderAgents();
}
async function createAgent(){
  const name=document.querySelector<HTMLInputElement>('#create-name');
  const input=document.querySelector<HTMLTextAreaElement>('#create-input');
  const error=document.querySelector<HTMLElement>('#create-error');
  const label=(name?.value||'').trim();
  if(!label){ if(error){error.textContent='Ajan adı gerekli';error.hidden=false;} name?.focus(); return; }
  try{
    const result=await call('create',{agent_kind:createKind,label,initial_input:(input?.value||'').trim()});
    showCreateModal(false);
    await refresh();
    const id=String(result?.agent_id||result?.agent?.agent_id||'');
    if(id) await selectAgent(id);
  }catch(err){
    if(error){ error.textContent=`Ajan oluşturulamadı · ${String(err)}`; error.hidden=false; }
    else setStatus(`Ajan oluşturulamadı · ${String(err)}`,true);
  }
}
function setOwner(owner:'agent'|'human', note:string){
  state.owner=owner; text('owner',owner==='human'?'İNSAN':'AJAN');
  document.querySelector('#viewport')!.classList.toggle('human-control',owner==='human');
  setStatus(note);
}

function showScreenLoader(show:boolean){
  const loader=document.querySelector<HTMLElement>('#screen-loader');
  if(!loader) return;
  loader.hidden=!show;
}
/// RFB akışı kurulana kadar en son bilinen frame'i canlı ekrana yedek olarak koy:
/// kullanıcı hiçbir zaman siyah boş ekranla karşılaşmaz.
async function showLastFrameFallback(){
  if(state.hasLiveImage||state.liveState==='LIVE') return;
  const agentId=state.selected;
  const curAgent=selected();
  const frameRef=String(curAgent?.last_frame_ref||'').trim() || (()=>{
    const latest=[...state.events].reverse().find(e=>evidenceImageRef(e));
    return latest?evidenceImageRef(latest):'';
  })();
  if(!frameRef) return;
  try{
    const url=await frameDataUrl(frameRef,agentId);
    if(!url||state.selected!==agentId||state.hasLiveImage) return;
    const img=document.querySelector<HTMLImageElement>('#live-frame')!;
    img.src=url; img.hidden=false;
    state.hasLiveImage=true;
    const empty=document.querySelector<HTMLElement>('#screen-empty'); if(empty) empty.hidden=true;
    text('screen-note','VDS son karesi gösteriliyor');
    showScreenLoader(false);
  }catch{/* yedek yoksa loader kalır */}
}
function updateStreamStatus(){
  const fpsEl=document.querySelector('#stream-fps');
  const latEl=document.querySelector('#stream-latency');
  if(fpsEl) fpsEl.textContent=state.liveFps?`${state.liveFps.toFixed(1)} fps`:'— fps';
  if(latEl){
    if(!state.lastFrameAt){ latEl.textContent='gecikme —'; }
    else { const age=Math.round((Date.now()-state.lastFrameAt)/1000); latEl.textContent=age<=1?'gecikme ~canlı':`son kare ${age}s önce`; }
  }
}
function applyLive(payload:{state?:string;detail?:string;width?:number;height?:number;image?:string;seq?:number;fps?:number;ts?:number}){
  const next=String(payload.state||'');
  if(next) state.liveState=next;
  const pill=document.querySelector('#display-state')!;
  pill.textContent=`● ${state.liveState||'HAZIR'}`;
  pill.classList.toggle('live',state.liveState==='LIVE');
  const img=document.querySelector<HTMLImageElement>('#live-frame')!;
  const empty=document.querySelector<HTMLElement>('#screen-empty')!;
  const lp=document.querySelector('#live-pill')!;
  if(payload.image){
    if(liveFrameQueued){ liveFrameQueued=payload; return; }
    liveFrameQueued=payload;
    requestAnimationFrame(()=>{
      const frame=liveFrameQueued; liveFrameQueued=null;
      if(!frame?.image) return;
      img.src=`data:image/png;base64,${frame.image}`; img.hidden=false; empty.hidden=true;
      state.hasLiveImage=true;
      const isLive=state.liveState==='LIVE';
      if(isLive) state.lastFrameAt=Date.now();
      if(frame.fps) state.liveFps=Number(frame.fps);
      state.frameCount=Number(frame.seq||state.frameCount+1);
      if(frame.width&&frame.height) state.liveResolution=`${frame.width}×${frame.height}`;
      text('resolution',state.liveResolution||'—');
      showScreenLoader(false);
      lp.classList.toggle('on',isLive);
      lp.innerHTML=isLive?'<i></i> Canlı görüntü':'<i></i> Son kare (yeniden bağlanıyor)';
      updateStreamStatus();
    });
    return;
  }
  if(payload.state){
    const note=document.querySelector('#screen-note')!; note.textContent=String(payload.detail||'');
    state.liveState=next||state.liveState;
    if(state.liveState!=='LIVE'&&state.liveState!=='STALE'){
      if(state.hasLiveImage){ img.hidden=false; empty.hidden=true; }
      else { img.hidden=true; empty.hidden=false; showScreenLoader(true); }
      lp.classList.remove('on'); lp.innerHTML='<i></i> Görüntü bağlantısı yok';
      if(pill){ pill.textContent=`● ${state.liveState||'GÖRÜNTÜ BEKLENİYOR'}`; pill.classList.remove('live'); }
    }
    updateStreamStatus();
  }
}

async function rfbInput(kind:string,extra:Record<string,unknown>){
  if(!humanControl()) return false;
  try{ await invoke('vnc_input',{kind,...extra}); }catch(err){ setStatus(`Girdi hatası · ${String(err)}`,true); }
  return true;
}
function remotePoint(el:HTMLElement,e:MouseEvent){
  const img=document.querySelector<HTMLImageElement>('#live-frame')!;
  const iw=img.naturalWidth||1280, ih=img.naturalHeight||720;
  const rect=el.getBoundingClientRect();
  const scale=Math.min(rect.width/iw,rect.height/ih);
  const ox=(rect.width-iw*scale)/2, oy=(rect.height-ih*scale)/2;
  const x=Math.round((e.clientX-rect.left-ox)/scale), y=Math.round((e.clientY-rect.top-oy)/scale);
  return { x:Math.max(0,Math.min(iw-1,x)), y:Math.max(0,Math.min(ih-1,y)), inside:e.clientX-rect.left>=ox&&e.clientX-rect.left<=ox+iw*scale&&e.clientY-rect.top>=oy&&e.clientY-rect.top<=oy+ih*scale };
}
const DISPLAY_SELECT_COMMAND = 'display_select';
const DISPLAY_RELEASE_COMMAND = 'display_release';

async function takeControl(){
  if(!state.selected) return setStatus('Önce ajan seçin',true);
  try{ await invoke('vnc_take'); setOwner('human',`${DISPLAY_SELECT_COMMAND} · kontrol sizde · canlı VDS yüzeyi ve girdiler açık`); }
  catch(err){ setStatus(`${DISPLAY_SELECT_COMMAND} başarısız · ${String(err)}`,true); }
}
async function watchLive(quiet=false){
  if(!state.selected){ if(!quiet) setStatus('Önce ajan seçin',true); return; }
  try{
    await invoke('vnc_watch');
    if(state.owner!=='human') setOwner('agent','Canlı VDS akışı açık · salt-okunur izleme · girdi için Kontrolü Al');
    else setStatus('Canlı VDS akışı açık');
  }catch(err){ if(!quiet) setStatus(`Canlı izleme başarısız · ${String(err)}`,true); }
}
async function releaseControl(){
  try{ await invoke('vnc_release'); setOwner('agent',`${DISPLAY_RELEASE_COMMAND} · kontrol ajana geri verildi · canlı yüzey bırakıldı`); }
  catch(err){ setStatus(`${DISPLAY_RELEASE_COMMAND} başarısız · ${String(err)}`,true); }
}
async function tencereStrike(e:MouseEvent){
  const rect=(e.currentTarget as HTMLElement).getBoundingClientRect();
  const p=remotePoint((e.currentTarget as HTMLElement),e);
  const bonk=document.querySelector<HTMLElement>('#bonk')!;
  bonk.style.left=`${e.clientX-rect.left}px`; bonk.style.top=`${e.clientY-rect.top}px`;
  bonk.classList.remove('show'); void bonk.offsetWidth; bonk.classList.add('show');
  window.setTimeout(()=>bonk.classList.remove('show'),450);
  const instruction='Buraya dikkat et; bu noktadaki hatalı adımı düzelt.';
  await sendInstruction(instruction,{mode:'tencere',coordinate:{x:p.x,y:p.y},current_frame:selected()?.last_frame_ref||null,target_region:{x:Math.max(0,p.x-48),y:Math.max(0,p.y-48),width:96,height:96},operator_instruction:instruction});
  await rfbInput('pointer',{x:p.x,y:p.y,mask:1});
  await rfbInput('pointer',{x:p.x,y:p.y,mask:0});
}

function bind(){
  document.querySelector<HTMLInputElement>('#agent-search')!.oninput=renderAgents;
  document.querySelectorAll<HTMLElement>('[data-filter]').forEach(el=>el.onclick=()=>setFilter(el.dataset.filter||'all'));
  document.querySelectorAll<HTMLElement>('[data-event-filter]').forEach(el=>el.onclick=()=>{ state.eventFilter=el.dataset.eventFilter||'all'; document.querySelectorAll<HTMLElement>('[data-event-filter]').forEach(x=>x.classList.toggle('active',x===el)); renderEvents(); });
  // ESC/palette: focus input'ta olsa bile capture aşamasında belge düzeyinde yakalanır.
  document.addEventListener('keydown',e=>{
    if(e.key==='Escape'){
      const lb=document.querySelector<HTMLElement>('#lightbox');
      if(lb&&!lb.hidden){ e.preventDefault(); closeLightbox(); return; }
      const cm=document.querySelector<HTMLElement>('#create-modal');
      if(cm&&!cm.hidden){ e.preventDefault(); showCreateModal(false); return; }
      showPalette(false);
      return;
    }
    if(e.ctrlKey&&e.key.toLowerCase()==='k'){ e.preventDefault(); showCreateModal(false); showPalette(!document.querySelector('#palette')!.classList.contains('open')); }
  },true);
  document.querySelector('#palette-backdrop')!.addEventListener('click',()=>showPalette(false));
  document.querySelector('#create-backdrop')!.addEventListener('click',()=>showCreateModal(false));
  document.querySelector<HTMLInputElement>('#create-name')!.addEventListener('keydown',e=>{ if((e as KeyboardEvent).key==='Enter'){ e.preventDefault(); void createAgent(); } });
  document.querySelectorAll<HTMLElement>('#create-kind .chip').forEach(chip=>chip.onclick=()=>{ createKind=chip.dataset.kind||'gezinme'; document.querySelectorAll('#create-kind .chip').forEach(c=>c.classList.toggle('active',c===chip)); });
  document.querySelectorAll<HTMLElement>('[data-tool]').forEach(el=>el.onclick=()=>{state.tool=el.dataset.tool!;document.querySelectorAll('[data-tool]').forEach(x=>x.classList.toggle('active',x===el));document.querySelector('#screen')!.className=`screen tool-${state.tool}`; if(state.tool==='keyboard'){document.querySelector<HTMLElement>('#viewport')?.focus(); setStatus('Klavye: viewport odakta · yazmak icin tikla, cikmak icin baska araca gec');} else setStatus(`Araç: ${state.tool}`);});
  let dragging=false;
  const panSurface=()=>document.querySelector<HTMLElement>('#screen')!;
  const panPoint=(e:MouseEvent)=>remotePoint(panSurface(),e);
  panSurface().addEventListener('mousedown',async(e:MouseEvent)=>{ if(state.tool!=='pan'||!humanControl()) return; dragging=true; const pt=panPoint(e); await rfbInput('pointer',{x:pt.x,y:pt.y,mask:1}); });
  panSurface().addEventListener('mouseup',async(e:MouseEvent)=>{ if(state.tool!=='pan'||!dragging) return; dragging=false; const pt=panPoint(e); await rfbInput('pointer',{x:pt.x,y:pt.y,mask:0}); setStatus(`Tasima birakildi · ${pt.x},${pt.y}`); });
  document.querySelectorAll<HTMLButtonElement>('[data-command]').forEach(el=>el.onclick=async()=>{
    if(!state.selected)return setStatus('Önce ajan seçin',true);
    const cmd=el.dataset.command!, agentId=state.selected, key=`${agentId}:${cmd}`;
    if(state.pending.has(key))return;
    state.pending.add(key);el.disabled=true;el.classList.add('active');
    try{await call(cmd,{agent_id:agentId,reason:'tauri-cockpit'});if(cmd==='replay'&&state.selected===agentId)await selectAgent(agentId);else await refresh();showPalette(false);}
    catch{/* call displays the actual rejection. */}
    finally{state.pending.delete(key);el.disabled=false;el.classList.remove('active');}
  });
  document.querySelectorAll<HTMLElement>('[data-instruction]').forEach(el=>el.onclick=()=>sendInstruction(el.dataset.instruction!));
  document.querySelectorAll<HTMLElement>('[data-tab]').forEach(el=>el.onclick=()=>setTab(el.dataset.tab!));
  setTab('live');
  document.querySelectorAll<HTMLElement>('[data-action]').forEach(el=>el.onclick=async(e:MouseEvent)=>{
    const action=el.dataset.action!;
    if(action==='palette') return showPalette();
    if(action==='palette-close') return showPalette(false);
    if(action==='create') return showCreateModal(true);
    if(action==='create-close') return showCreateModal(false);
    if(action==='create-submit') return void createAgent();
    if(action==='lightbox'||action==='lightbox-open') return openLightbox();
    if(action==='lightbox-close') return closeLightbox();
    if(action==='lb-zoom-in') return lbZoom(0.25);
    if(action==='lb-zoom-out') return lbZoom(-0.25);
    if(action==='lb-zoom-reset'){ state.zoom=1;state.zoomX=0;state.zoomY=0;return lightboxApplyZoom(); }
    if(action==='select'){showPalette(false);return document.querySelector<HTMLInputElement>('#agent-search')!.focus();}
    if(action==='proxy-export') return exportProxies();
    if(action==='watch') return watchLive();
    if(action==='take') return takeControl();
    if(action==='return') return releaseControl();
    if(action==='retry') return sendInstruction('AI kararını yeniden değerlendir ve bir sonraki gerçek adımı tekrar dene.');
    if(action==='redirect') return sendInstruction('Mevcut kanıta göre yönü değiştir; koku, ilk diş ve sonraki gerçek adımı açıkça kaydet.');
    if(action==='send'||action==='focus-command'){const input=document.querySelector<HTMLTextAreaElement>('#instruction')!; if(action==='focus-command'){showPalette(false);input.focus();}else{await sendInstruction(input.value);input.value='';} return;}
    if(action==='fullscreen') document.fullscreenElement?document.exitFullscreen():document.querySelector('#viewport')?.requestFullscreen();
    if(action==='prev'||action==='next'){ if(!state.events.length) return; const cur=state.inspectIndex<0?state.events.length-1:state.inspectIndex; const nxt=action==='prev'?Math.max(0,cur-1):Math.min(state.events.length-1,cur+1); inspect(nxt); return; }
    if(action==='live'){ state.inspectIndex=-1; state.inspectDataUrl=''; renderFrames(); const t=document.querySelector<HTMLElement>('#preview-text')!; t.hidden=false; text('preview-text','CANLI · gerçek RFB akışı'); document.querySelector<HTMLImageElement>('#preview-img')!.hidden=true; setStatus('Canlı görünüme dönüldü'); return; }
    void e;
  });
  const scrub=document.querySelector<HTMLInputElement>('#scrub')!;
  scrub.oninput=()=>{ const idx=Number(scrub.value); if(state.events[idx]) inspect(idx); };
  bindScrubber();
  bindLightbox();
  document.querySelector<HTMLElement>('#preview')!.addEventListener('click',()=>{ if(state.inspectDataUrl) openLightbox(); });
  const screen=document.querySelector<HTMLElement>('#screen')!;
  screen.addEventListener('click',async(e:MouseEvent)=>{
    if(state.tool==='tencere') return tencereStrike(e);
    if(state.tool==='target'){
      const p=remotePoint(screen,e);
      const instruction='Bu noktayı hedef olarak incele ve doğru sonraki adımı seç.';
      await sendInstruction(instruction,{mode:'target',coordinate:{x:p.x,y:p.y},current_frame:selected()?.last_frame_ref||null,target_region:{x:Math.max(0,p.x-48),y:Math.max(0,p.y-48),width:96,height:96},operator_instruction:instruction});
      return;
    }
    if(humanControl()){ const p=remotePoint(screen,e); await rfbInput('pointer',{x:p.x,y:p.y,mask:1}); await rfbInput('pointer',{x:p.x,y:p.y,mask:0}); }
    else setStatus('İnsan girdisi kapalı · Kontrolü Al ile devralın',true);
  });
  screen.addEventListener('dblclick',async(e:MouseEvent)=>{ if(humanControl()&&!['tencere','target'].includes(state.tool)){ const p=remotePoint(screen,e); await rfbInput('pointer',{x:p.x,y:p.y,mask:1}); await rfbInput('pointer',{x:p.x,y:p.y,mask:0}); } });
  screen.addEventListener('mousemove',e=>{ const p=remotePoint(screen,e); const hc=document.querySelector<HTMLElement>('#human-cursor')!; hc.style.transform=`translate(${p.x}px,${p.y}px)`; if(humanControl()&&['cursor','pan'].includes(state.tool)){ const now=performance.now(); if(now-lastMouseSend>50){ lastMouseSend=now; void rfbInput('pointer',{x:p.x,y:p.y,mask:0}); } } });
  screen.addEventListener('wheel',async(e:WheelEvent)=>{ if(!humanControl()) return; e.preventDefault(); const p=remotePoint(screen,e); const mask=e.deltaY<0?8:16; await rfbInput('pointer',{x:p.x,y:p.y,mask}); await rfbInput('pointer',{x:p.x,y:p.y,mask:0}); },{passive:false});
  const keysymFor=(e:KeyboardEvent):number|null=>{
    if(e.key.length===1&&e.key.charCodeAt(0)>=0x20) return e.key.charCodeAt(0);
    const named:Record<string,number>={Backspace:0xFF08,Tab:0xFF09,Enter:0xFF0D,Escape:0xFF1B,Delete:0xFFFF,Home:0xFF50,End:0xFF57,PageUp:0xFF55,PageDown:0xFF56,Insert:0xFF63,ArrowLeft:0xFF51,ArrowUp:0xFF52,ArrowRight:0xFF53,ArrowDown:0xFF54,ShiftLeft:0xFFE1,ShiftRight:0xFFE2,ControlLeft:0xFFE3,ControlRight:0xFFE4,AltLeft:0xFFE9,AltRight:0xFFEA,MetaLeft:0xFFE7,MetaRight:0xFFE8,' ':0x20,F1:0xFFBE,F2:0xFFBF,F3:0xFFC0,F4:0xFFC1,F5:0xFFC2,F6:0xFFC3,F7:0xFFC4,F8:0xFFC5,F9:0xFFC6,F10:0xFFC7,F11:0xFFC8,F12:0xFFC9};
    return named[e.key]??null;
  };
  const keyHandler=async(e:KeyboardEvent,down:boolean)=>{
    if(!humanControl()) return;
    const target=e.target as HTMLElement;
    if(target&&(target.tagName==='INPUT'||target.tagName==='TEXTAREA')) return;
    if(!document.querySelector('#viewport')!.matches(':focus-within')) return;
    const ks=keysymFor(e); if(ks===null) return;
    e.preventDefault();
    await rfbInput('key',{keysym:ks,down});
  };
  document.addEventListener('keydown',e=>void keyHandler(e,true));
  document.addEventListener('keyup',e=>void keyHandler(e,false));
  window.addEventListener('show_base',((ev:Event)=>{
    const detail=(ev as CustomEvent).detail; if(detail) applyLive(detail);
  }) as EventListener);
  void listen<{state?:string;detail?:string;width?:number;height?:number;image?:string;seq?:number;fps?:number;ts?:number}>('show_base',e=>applyLive(e.payload||{})).catch(()=>{});
  void listen<Record<string,unknown>>('display_state',e=>{ const dc=(e.payload||{}) as Record<string,unknown>; const cur=String(dc.operator_selected_agent||''); if(cur&&cur!==state.selected&&state.owner!=='human') setStatus(`VDS yüzey seçimi: ${cur.slice(0,24)}…`); }).catch(()=>{});
}
async function refresh(){
  if(refreshing) return;
  refreshing=true;
  try{
    // Ağır replay çağrısını ilk açılışta yapma: önce ajan listesi gelsin, ekran dolsun.
    const r=await call('status',{},true);
    state.agents=Array.isArray(r.agents)?r.agents:[];
    state.connected=true;
    const c=document.querySelector('#connection')!; c.textContent='● VDS BAĞLI'; c.classList.add('online');
    const dc=(r.display_control||{}) as Record<string,unknown>;
    const opSel=String(dc.operator_selected_agent||'');
    if(opSel&&opSel!==state.selected){ setStatus(`VDS yüzey seçimi: ${opSel.slice(0,24)}…`); }
    renderAgents(); renderDetail();
  }catch{ state.connected=false; const c=document.querySelector('#connection')!;c.textContent='● VDS BAĞLANTISI YOK · son alınan durum';c.classList.remove('online');renderAgents(); }
  finally{ refreshing=false; }
}
async function refreshSlow(){
  if(!state.selected||replaying) return;
  if(document.hidden) return;
  const agentId=state.selected;
  replaying=true;
  try{
    const r=checkedResponse(await invoke<any>('agentd', { command:'replay', payload:{ agent_id:agentId, after_seq:eventCursor(state.events) } }));
    if(state.selected!==agentId) return;
    if(Array.isArray(r.events)&&r.events.length){
      const inspected=state.events[state.inspectIndex]?.event_id;
      state.events=mergeEvents(state.events,r.events,agentId);
      state.inspectIndex=inspected?state.events.findIndex(e=>e.event_id===inspected):-1;
      renderDetail();
    }
  }catch(error){ if(state.selected===agentId)setStatus(`Olay akışı kesildi · ${String(error)}`,true); }
  finally{ replaying=false; }
}
appShell();
// İlk frame tamamen yerleştikten sonra uzak bağlantıyı başlat; açılış ekranı ağ gecikmesine bağlanmaz.
requestAnimationFrame(() => {
  void refresh();
  void loadHarvestData(true);
  window.setInterval(refresh,15000);
  window.setInterval(refreshSlow,2500);
  window.setInterval(loadHarvestData,3000);
  window.setInterval(updateStreamStatus,1000);
});
// Pencere boyutlanınca layout'u zorlamadan tek RAF döngüsünde senkronize et:
// klon/çift render artefaktlarını ve gereksiz reflow'ları engeller.
let resizeFrame=0;
window.addEventListener('resize',()=>{
  if(resizeFrame) return;
  resizeFrame=requestAnimationFrame(()=>{ resizeFrame=0; updateStreamStatus(); });
});
