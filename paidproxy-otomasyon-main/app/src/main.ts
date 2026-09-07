import { invoke } from '@tauri-apps/api/core';
import { listen } from '@tauri-apps/api/event';
import { createElement, Search, Plus, SlidersHorizontal, Command, Monitor, Terminal, Folder, Globe, Cpu, MousePointer2, Hand, Crosshair, CookingPot, Keyboard, Maximize2, Eye, RotateCcw, GitBranch, Pause, Square, Camera, MousePointerClick, Send, ChevronLeft, ChevronRight, Radio, AlertTriangle, CircleDot } from 'lucide';
import './styles.css';

type Agent = Record<string, any>;
type EventRow = Record<string, any>;

const icons: Record<string, any> = { Search, Plus, SlidersHorizontal, Command, Monitor, Terminal, Folder, Globe, Cpu, MousePointer2, Hand, Crosshair, CookingPot, Keyboard, Maximize2, Eye, RotateCcw, GitBranch, Pause, Square, Camera, MousePointerClick, Send, ChevronLeft, ChevronRight, Radio, AlertTriangle, CircleDot };
const state = {
  agents: [] as Agent[], selected: '', events: [] as EventRow[], owner: 'agent', tool: 'cursor',
  connected: false, liveState: '', frameCount: 0, inspectIndex: -1, inspectDataUrl: '', frameCache: new Map<string, string>(),
};
let liveFrameQueued: {state?:string;detail?:string;width?:number;height?:number;image?:string;seq?:number} | null = null;
let lastMouseSend = 0;
let refreshing = false;

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

async function call(command: string, payload: Record<string, unknown> = {}) {
  // Tıklama anında tepki ver: düğme hemen basılmış görünür, sonuç sonra gelir.
  setStatus(`${command} · gönderildi`);
  const timer = window.setTimeout(()=>setStatus(`${command} · VDS yanıtı bekleniyor (uzun sürerse pencere kilitlenmez)`), 1500);
  try {
    const result = await invoke<any>('agentd', { command, payload });
    setStatus(`${command} · tamamlandı`);
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
        <nav class="rail-tools"><small>ARAÇLAR</small><button data-action="palette">${icon('Command')} Komut Paleti <kbd>Ctrl K</kbd></button><button data-tab="terminal">${icon('Terminal')} Terminal</button><button data-tab="evidence">${icon('Folder')} Dosyalar</button></nav>
      </aside>
      <section class="main-column">
        <div class="view-tabs"><button class="active">${icon('Monitor')} Canlı VDS</button><button data-tab="terminal">${icon('Terminal')} Terminal</button><button data-tab="evidence">${icon('Folder')} Dosyalar</button><button>${icon('Globe')} Tarayıcı</button><button>${icon('Cpu')} Sistem</button><span id="display-state">● HAZIR</span></div>
        <div class="viewport" id="viewport" tabindex="0">
          <div class="browser-chrome"><span></span><span></span><span></span><div id="target-url">VDS görüntüsü bekleniyor</div></div>
          <div class="screen" id="screen"><img id="live-frame" alt="" hidden/><div class="screen-empty" id="screen-empty"><b>CANLI VDS</b><span id="screen-note">Gerçek WayVNC görüntüsü bekleniyor</span></div><div class="agent-cursor" id="agent-cursor">◆<em>AJAN</em></div><div class="human-cursor" id="human-cursor">↖<em>SİZ</em></div><div class="bonk" id="bonk">BONK!</div></div>
          <div class="floating-tools">
            <button class="active" data-tool="cursor" title="Cursor">${icon('MousePointer2',16)}</button><button data-tool="pan" title="Pan">${icon('Hand',16)}</button><button data-tool="target" title="Hedef göster">${icon('Crosshair',16)}</button><button data-tool="tencere" class="tencere" title="Tencere">${icon('CookingPot',16)}</button><button data-tool="keyboard" title="Klavye">${icon('Keyboard',16)}</button><button data-action="fullscreen" title="Tam ekran">${icon('Maximize2',16)}</button>
          </div>
          <div class="viewport-foot"><span id="live-pill"><i></i> Canlı</span><span>Otomatik kaydet</span><span>HD</span><b id="resolution">—</b></div>
        </div>
        <section class="replay"><div class="replay-head"><b>FRAME / REPLAY</b><span id="replay-position">Kayıt yok</span><div><button data-action="prev">${icon('ChevronLeft')}</button><button data-action="next">${icon('ChevronRight')}</button><button data-action="live" class="live-button">● Canlıya dön</button></div></div><div class="frame-strip" id="frame-strip"><div class="empty-frame">Gerçek frame event'i bekleniyor</div></div><input id="scrub" type="range" min="0" max="0" value="0"/></section>
        <section class="workspace">
          <div class="workspace-tabs"><button class="active" data-tab="activity">Ajan Aktiviteleri</button><button data-tab="evidence">Kanıtlar</button><button data-tab="logs">Loglar</button><button data-tab="terminal">Terminal</button><button data-tab="notes">Notlar</button></div>
          <div class="workspace-body"><div class="activity-pane"><div class="event-filters"><button class="active">Tümü</button><button>Düşünce</button><button>Eylem</button><button>Araç</button><button>Hata</button></div><div id="event-list" class="event-list"><div class="empty-event">Bir ajan seçildiğinde gerçek olay akışı burada görünür.</div></div></div><aside class="inspector"><div class="inspector-tabs"><b>Görüntü</b><span>Ham Veri</span><span>Analiz</span></div><div class="preview" id="preview"><img id="preview-img" alt="" hidden/><span id="preview-text">FRAME ÖNİZLEMESİ</span></div><dl id="metadata"><div><dt>Zaman</dt><dd>—</dd></div><div><dt>Eylem</dt><dd>—</dd></div><div><dt>Ajan</dt><dd>—</dd></div><div><dt>Dosya</dt><dd>—</dd></div></dl></aside></div>
        </section>
      </section>
      <aside class="control-panel">
        <div class="control-head"><div class="avatar">✦</div><div><small>SEÇİLİ AJAN</small><h2 id="detail-name">Ajan seçilmedi</h2><p id="detail-id">—</p></div><span class="state-pill" id="detail-state">OFFLINE</span></div>
        <section class="goal"><header><span>HEDEF</span><b id="progress">—</b></header><p id="goal">Ajan hedefi bekleniyor.</p><div class="progress"><i id="progress-bar"></i></div></section>
        <section class="facts"><label>MEVCUT ADIM</label><p id="current-step">—</p><label>SON EYLEM</label><p id="last-action">—</p><label>ENGEL / SEBEP</label><p class="blocker" id="blocker">Engel bildirilmedi</p></section>
        <section class="actions"><label>AKSİYONLAR</label><div class="action-grid"><button data-command="viewport">${icon('Eye')} Gözlemle</button><button data-action="retry">${icon('RotateCcw')} Yeniden Dene</button><button data-action="plan">${icon('GitBranch')} Planı Değiştir</button><button data-action="take" class="take">${icon('MousePointerClick')} Kontrolü Al</button><button data-command="hard_kill" class="danger">${icon('Square')} Durdur</button><button data-command="pause">${icon('Pause')} Duraklat</button></div></section>
        <section class="quick"><label>HIZLI KOMUTLAR</label><div><button data-instruction="Sayfayı yenile ve sonucu gözlemle.">Sayfayı yenile</button><button data-instruction="İşaretli hedefe tıkla.">Tıkla</button><button data-instruction="Klavye girdisini doğrula.">Yaz</button><button data-instruction="Sayfayı kontrollü biçimde kaydır.">Kaydır</button><button data-command="viewport">${icon('Camera')} Görüntü al</button></div></section>
        <section class="composer"><label>AJANI UYAR</label><div><textarea id="instruction" placeholder="Bu ajana ne yapacağını söyle..."></textarea><button data-action="send">${icon('Send')}</button></div></section>
        <div class="owner"><span>KONTROL</span><b id="owner">AJAN</b><button data-action="return">Ajana geri ver</button></div>
      </aside>
    </section>
    <footer id="status">VDS bağlantısı kuruluyor…</footer>
  </main>
  <div class="palette" id="palette"><div><b>KOMUT PALETİ</b><kbd>ESC</kbd></div><input placeholder="Komut ara..." autofocus/><button data-action="select">Ajan seç</button><button data-command="viewport">Observe</button><button data-command="pause">Pause</button><button data-command="hard_kill">Stop</button><button data-action="retry">Retry</button><button data-action="take">Kontrolü al</button><button data-action="return">Ajana geri ver</button><button data-command="replay">Replay aç</button><button data-tab="evidence">Evidence aç</button><button data-action="focus-command">Komut gönder</button></div>`;
  bind(); refreshIcons();
}

function refreshIcons(){ document.querySelectorAll('i[data-lucide]').forEach(i => { const def = (icons as any)[i.getAttribute('data-lucide')!]; if (def) i.replaceWith(createElement(def)); }); }

function renderAgents() {
  const list=document.querySelector('#agent-list')!; const query=(document.querySelector<HTMLInputElement>('#agent-search')?.value||'').toLowerCase();
  const agents=state.agents.filter(a => `${a.pet?.name||''} ${a.label||''} ${a.agent_id}`.toLowerCase().includes(query));
  document.querySelector('#agent-count')!.textContent=String(state.agents.length);
  list.innerHTML=agents.length ? agents.map(a => { const blocked=Boolean(a.blocker); const cls=blocked?'blocked':a.state==='failed'?'error':a.state==='paused'?'manual':a.state; return `<button class="agent ${cls} ${a.agent_id===state.selected?'selected':''}" data-agent="${esc(a.agent_id)}"><span class="agent-avatar">${blocked?'!':'✦'}</span><span><b>${esc(a.pet?.name||a.label||a.agent_id)}</b><small>${esc(a.working_note||a.current_tool||'Görev bekleniyor')}</small></span><em>${esc(a.state||'unknown')}</em></button>`; }).join('') : '<div class="empty-list">VDS ajanları bekleniyor</div>';
  list.querySelectorAll<HTMLElement>('[data-agent]').forEach(el=>el.onclick=()=>selectAgent(el.dataset.agent!));
}

function renderDetail() {
  const a=selected(); if(!a) return;
  const name=a.pet?.name||a.label||a.agent_id; const current=Number(a.progress?.current||a.progress_current||0), total=Number(a.progress?.total||a.progress_total||0);
  text('glance-name',name); text('glance-action',a.working_note||a.current_event_type||'İzleniyor'); text('detail-name',name); text('detail-id',`…${String(a.agent_id).slice(-10)} · ${a.kind||'VDS'}`); text('detail-state',String(a.state||'unknown').toUpperCase()); text('goal',a.current_target||a.label||'Hedef bildirilmedi'); text('progress',total?`${current}/${total}`:'—'); text('current-step',a.next_action||a.working_note||'—'); text('last-action',`${a.current_event_type||a.current_tool||'—'} · ${time(a.last_event_timestamp)}`); text('blocker',a.blocker||'Engel bildirilmedi'); text('target-url',a.current_target||'VDS görüntüsü bekleniyor');
  (document.querySelector('#progress-bar') as HTMLElement).style.width=total?`${Math.min(100,current/total*100)}%`:'0%'; renderEvents(); refreshIcons();
}
function renderEvents(){ const list=document.querySelector('#event-list')!; const rows=state.events.slice(-250); list.innerHTML=rows.length?rows.slice().reverse().map((e,i)=>`<button class="event ${category(e)}" data-event="${state.events.length-1-i}"><i></i><span><b>${esc(e.event_type||'event')}</b><small>${esc(e.working_note||e.tool||e.target||'Olay kaydı')}</small></span><time>${time(e.timestamp)}</time></button>`).join(''):'<div class="empty-event">Bu ajan için olay kaydı yok.</div>'; list.querySelectorAll<HTMLElement>('[data-event]').forEach(el=>el.onclick=()=>inspect(Number(el.dataset.event))); renderFrames(); }
function frameEvents(){ return state.events.filter(e=>e.frame_ref); }
function renderFrames(){
  const frames=frameEvents(); const strip=document.querySelector('#frame-strip')!;
  strip.innerHTML=frames.length?frames.slice(-8).map(e=>{ const idx=state.events.indexOf(e); return `<button class="frame ${category(e)} ${idx===state.inspectIndex?'selected':''}" data-frame="${idx}"><img data-thumb="${esc(e.frame_ref)}" alt=""/><b>#${esc(e.seq)}</b><small>${time(e.timestamp)}</small></button>`; }).join(''):'<div class="empty-frame">Gerçek frame event\u2019i bekleniyor</div>';
  text('replay-position',frames.length?`${frames.length} gerçek kayıt`:'Kayıt yok');
  const scrub=document.querySelector<HTMLInputElement>('#scrub')!; scrub.max=String(Math.max(0,state.events.length-1)); scrub.value=String(Math.max(0,state.inspectIndex<0?state.events.length-1:state.inspectIndex));
  strip.querySelectorAll<HTMLElement>('[data-frame]').forEach(el=>el.onclick=()=>inspect(Number(el.dataset.frame)));
  strip.querySelectorAll<HTMLImageElement>('[data-thumb]').forEach(img=>loadFrameRef(img.dataset.thumb!,'thumb'));
  refreshIcons();
}
async function frameDataUrl(frameRef:string,agentId:string):Promise<string|undefined>{
  const key=`${agentId}|${frameRef}`; const cached=state.frameCache.get(key); if(cached) return cached;
  const r=await invoke<any>('fetch_frame',{agentId,frameRef});
  if(r?.data_url){ if(state.frameCache.size>40){ const firstKey=state.frameCache.keys().next().value as string|undefined; if(firstKey!==undefined) state.frameCache.delete(firstKey); } state.frameCache.set(key,String(r.data_url)); return String(r.data_url); }
  return undefined;
}
async function loadFrameRef(frameRef:string,purpose:'thumb'|'preview'){
  if(!frameRef||!state.selected) return;
  try{ const url=await frameDataUrl(frameRef,state.selected);
    if(!url) return;
    if(purpose==='thumb'){ document.querySelectorAll<HTMLImageElement>(`[data-thumb="${CSS.escape(frameRef)}"]`).forEach(img=>{img.src=url;}); }
    else if(state.inspectDataUrl===frameRef||purpose==='preview'){ const img=document.querySelector<HTMLImageElement>('#preview-img')!; img.src=url; img.hidden=false; const t=document.querySelector<HTMLElement>('#preview-text')!; t.hidden=true; }
  }catch{ /* artifact alınamadıysa metin önizleme kalır */ }
}
function inspect(index:number){
  const e=state.events[index]; if(!e) return;
  state.inspectIndex=index; state.inspectDataUrl=String(e.frame_ref||'');
  text('preview-text',e.frame_ref?'GERÇEK FRAME':'Bu event için frame yok');
  const img=document.querySelector<HTMLImageElement>('#preview-img')!;
  if(e.frame_ref){ img.hidden=true; loadFrameRef(String(e.frame_ref),'preview'); } else { img.hidden=true; }
  const t=document.querySelector<HTMLElement>('#preview-text')!; t.hidden=Boolean(e.frame_ref);
  document.querySelector('#metadata')!.innerHTML=`<div><dt>Zaman</dt><dd>${esc(time(e.timestamp))}</dd></div><div><dt>Eylem</dt><dd>${esc(e.event_type)}</dd></div><div><dt>Ajan</dt><dd>${esc(e.agent_id)}</dd></div><div><dt>Dosya</dt><dd>${esc(e.frame_ref||e.video_ref||'—')}</dd></div>`;
  renderFrames();
}
async function selectAgent(id:string){
  state.selected=id; state.events=[]; state.inspectIndex=-1; state.inspectDataUrl='';
  renderAgents(); renderDetail();
  setStatus('Ajan seçildi · olaylar yükleniyor');
  try{ await invoke('set_display_target',{agentId:id}); }catch{}
  try{ const r=await call('replay',{agent_id:id,after_seq:0}); state.events=Array.isArray(r.events)?r.events:[]; renderDetail(); }catch{}
}
async function sendInstruction(instruction:string, context:Record<string,unknown>={}){ if(!state.selected||!instruction.trim()) return; const r=await call('intervene',{agent_id:state.selected,instruction,context}); if(r?.intervention_id) setStatus(`Yönlendirme kaydedildi · ${String(r.intervention_id).slice(0,18)}…`); }
function text(id:string,value:unknown){ const el=document.getElementById(id); if(el) el.textContent=String(value??''); }
function setStatus(message:string,error=false){ const el=document.querySelector('#status')!; el.textContent=message; el.classList.toggle('error',error); }
function showPalette(show=true){ document.querySelector('#palette')!.classList.toggle('open',show); }
function setTab(name:string){ document.querySelectorAll('[data-tab]').forEach(x=>x.classList.toggle('active',(x as HTMLElement).dataset.tab===name)); }
function setOwner(owner:'agent'|'human', note:string){
  state.owner=owner; text('owner',owner==='human'?'İNSAN':'AJAN');
  document.querySelector('#viewport')!.classList.toggle('human-control',owner==='human');
  setStatus(note);
}

function applyLive(payload:{state?:string;detail?:string;width?:number;height?:number;image?:string;seq?:number}){
  const next=String(payload.state||'');
  if(next) state.liveState=next;
  const pill=document.querySelector('#display-state')!;
  pill.textContent=`● ${state.liveState||'HAZIR'}`;
  pill.classList.toggle('live',state.liveState==='LIVE');
  const img=document.querySelector<HTMLImageElement>('#live-frame')!;
  const empty=document.querySelector<HTMLElement>('#screen-empty')!;
  if(payload.image){
    if(liveFrameQueued){ liveFrameQueued=payload; return; }
    liveFrameQueued=payload;
    requestAnimationFrame(()=>{
      const frame=liveFrameQueued; liveFrameQueued=null;
      if(!frame?.image) return;
      img.src=`data:image/png;base64,${frame.image}`; img.hidden=false; empty.hidden=true;
      state.frameCount=Number(frame.seq||state.frameCount+1);
      text('resolution',`${frame.width||'?'}×${frame.height||'?'}`);
      const lp=document.querySelector('#live-pill')!; lp.classList.add('on');
    });
  } else if(payload.state){
    const note=document.querySelector('#screen-note')!; note.textContent=String(payload.detail||'');
    if(state.liveState!=='LIVE'){ empty.hidden=false; }
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
async function takeControl(){
  if(!state.selected) return setStatus('Önce ajan seçin',true);
  try{ await call('display_select',{agent_id:state.selected}); await invoke('vnc_take'); setOwner('human','Kontrol sizde · canlı VDS yüzeyi ve girdiler açık'); }
  catch(err){ setStatus(`Kontrol alınamadı · ${String(err)}`,true); }
}
async function releaseControl(){
  try{ await invoke('vnc_release'); await call('display_release',{}); setOwner('agent','Kontrol ajana geri verildi · canlı yüzey bırakıldı'); }
  catch(err){ setStatus(`Bırakma hatası · ${String(err)}`,true); }
}
async function tencereStrike(e:MouseEvent){
  const rect=(e.currentTarget as HTMLElement).getBoundingClientRect();
  const p=remotePoint((e.currentTarget as HTMLElement),e);
  const bonk=document.querySelector<HTMLElement>('#bonk')!;
  bonk.style.left=`${e.clientX-rect.left}px`; bonk.style.top=`${e.clientY-rect.top}px`;
  bonk.classList.remove('show'); void bonk.offsetWidth; bonk.classList.add('show');
  const instruction='Buraya dikkat et; bu noktadaki hatalı adımı düzelt.';
  await sendInstruction(instruction,{mode:'tencere',coordinate:{x:p.x,y:p.y},current_frame:selected()?.last_frame_ref||null,target_region:{x:Math.max(0,p.x-48),y:Math.max(0,p.y-48),width:96,height:96},operator_instruction:instruction});
  await rfbInput('pointer',{x:p.x,y:p.y,mask:1});
  await rfbInput('pointer',{x:p.x,y:p.y,mask:0});
}

function bind(){
  document.querySelector<HTMLInputElement>('#agent-search')!.oninput=renderAgents;
  document.addEventListener('keydown',e=>{ if(e.ctrlKey&&e.key.toLowerCase()==='k'){e.preventDefault();showPalette(!document.querySelector('#palette')!.classList.contains('open'));} if(e.key==='Escape')showPalette(false); });
  document.querySelectorAll<HTMLElement>('[data-tool]').forEach(el=>el.onclick=()=>{state.tool=el.dataset.tool!;document.querySelectorAll('[data-tool]').forEach(x=>x.classList.toggle('active',x===el));document.querySelector('#screen')!.className=`screen tool-${state.tool}`; setStatus(`Araç: ${state.tool}`);});
  document.querySelectorAll<HTMLElement>('[data-command]').forEach(el=>el.onclick=async()=>{ el.classList.add('active'); window.setTimeout(()=>el.classList.remove('active'),300); if(!state.selected)return setStatus('Önce ajan seçin',true); const cmd=el.dataset.command!; setStatus(`${cmd} · gönderildi`); await call(cmd,{agent_id:state.selected,reason:'tauri-cockpit'}); if(cmd==='replay') await selectAgent(state.selected); showPalette(false); });
  document.querySelectorAll<HTMLElement>('[data-instruction]').forEach(el=>el.onclick=()=>sendInstruction(el.dataset.instruction!));
  document.querySelectorAll<HTMLElement>('[data-tab]').forEach(el=>el.onclick=()=>setTab(el.dataset.tab!));
  document.querySelectorAll<HTMLElement>('[data-action]').forEach(el=>el.onclick=async(e:MouseEvent)=>{
    const action=el.dataset.action!;
    if(action==='palette') return showPalette(); if(action==='select'){showPalette(false);return document.querySelector<HTMLInputElement>('#agent-search')!.focus();}
    if(action==='take') return takeControl();
    if(action==='return') return releaseControl();
    if(action==='retry') return sendInstruction('AI kararını yeniden değerlendir ve bir sonraki gerçek adımı tekrar dene.');
    if(action==='plan') return sendInstruction('Mevcut planı yeniden değerlendir; hatalı veya eksik adımı düzelterek devam et.');
    if(action==='send'||action==='focus-command'){const input=document.querySelector<HTMLTextAreaElement>('#instruction')!; if(action==='focus-command'){showPalette(false);input.focus();}else{await sendInstruction(input.value);input.value='';} return;}
    if(action==='fullscreen') document.fullscreenElement?document.exitFullscreen():document.querySelector('#viewport')?.requestFullscreen();
    if(action==='prev'||action==='next'){ if(!state.events.length) return; const cur=state.inspectIndex<0?state.events.length-1:state.inspectIndex; const nxt=action==='prev'?Math.max(0,cur-1):Math.min(state.events.length-1,cur+1); inspect(nxt); return; }
    if(action==='live'){ state.inspectIndex=-1; state.inspectDataUrl=''; renderFrames(); const t=document.querySelector<HTMLElement>('#preview-text')!; t.hidden=false; text('preview-text','CANLI · gerçek RFB akışı'); document.querySelector<HTMLImageElement>('#preview-img')!.hidden=true; setStatus('Canlı görünüme dönüldü'); return; }
    void e;
  });
  const scrub=document.querySelector<HTMLInputElement>('#scrub')!;
  scrub.oninput=()=>{ const idx=Number(scrub.value); if(state.events[idx]) inspect(idx); };
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
  void listen<{state?:string;detail?:string;width?:number;height?:number;image?:string;seq?:number}>('show_base',e=>applyLive(e.payload||{})).catch(()=>{});
  void listen<Record<string,unknown>>('display_state',e=>{ const dc=(e.payload||{}) as Record<string,unknown>; const cur=String(dc.operator_selected_agent||''); if(cur&&cur!==state.selected&&state.owner!=='human') setStatus(`VDS yüzey seçimi: ${cur.slice(0,24)}…`); }).catch(()=>{});
}
async function refresh(){
  if(refreshing) return;
  refreshing=true;
  try{
    const r=await call('status');
    state.agents=Array.isArray(r.agents)?r.agents:[];
    state.connected=true;
    const c=document.querySelector('#connection')!; c.textContent='● VDS BAĞLI'; c.classList.add('online');
    const dc=(r.display_control||{}) as Record<string,unknown>;
    const opSel=String(dc.operator_selected_agent||'');
    if(opSel&&opSel!==state.selected){ /* başka yüzey seçim yapmış olabilir; bilgi ver */ setStatus(`VDS yüzey seçimi: ${opSel.slice(0,24)}…`); }
    if(!state.selected&&state.agents[0]) await selectAgent(state.agents[0].agent_id);
    renderAgents(); renderDetail();
  }catch{ renderAgents(); }
  finally{ refreshing=false; }
}
appShell(); refresh(); setInterval(refresh,15000);
