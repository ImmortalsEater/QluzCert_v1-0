// ==================== STATE ====================
const DB = {
  get(k){try{return JSON.parse(localStorage.getItem('crt_'+k)||'null')}catch{return null}},
  set(k,v){localStorage.setItem('crt_'+k,JSON.stringify(v))},
};
const storedClientes = DB.get('clientes');
const storedParceiros = DB.get('parceiros');
let clientes = (Array.isArray(storedClientes) && storedClientes.length)
  ? storedClientes
  : ((typeof window !== 'undefined' && Array.isArray(window.INITIAL_CLIENTES) && window.INITIAL_CLIENTES.length>0)
      ? window.INITIAL_CLIENTES.slice()
      : []);
let parceiros = ((typeof window !== 'undefined' && Array.isArray(window.INITIAL_PARCEIROS) && window.INITIAL_PARCEIROS.length>0)
      ? window.INITIAL_PARCEIROS.slice()
      : (Array.isArray(storedParceiros) ? storedParceiros : []));
let precos = DB.get('precos')||[
  {id:1,tipo:'e-CPF A1',validade:'1 ano',preco:150},
  {id:2,tipo:'e-CPF A3',validade:'3 anos',preco:280},
  {id:3,tipo:'e-CNPJ A1',validade:'1 ano',preco:200},
  {id:4,tipo:'e-CNPJ A3',validade:'3 anos',preco:350},
  {id:5,tipo:'NF-e',validade:'1 ano',preco:120},
];
let editingId = null;
let triagemStep = 0;
let triagemData = {};

const STATUS_LIST = ['Novo Lead','Documentação Pendente','Aguardando Pagamento','Agendado para Vídeo','Emitido'];
const STATUS_CLASSES = ['badge-novo','badge-doc','badge-pag','badge-video','badge-emitido'];
const STATUS_COLORS = ['info','warn','purple','teal','success'];
const KANBAN_COLORS = ['var(--info)','var(--warn)','var(--purple)','var(--teal)','var(--success)'];

function save(){DB.set('clientes',clientes);DB.set('parceiros',parceiros);DB.set('precos',precos);updateBadges()}

function saveLocalOnly(){DB.set('clientes',clientes);DB.set('parceiros',parceiros);DB.set('precos',precos);updateBadges();setStatus('Salvo localmente'); showToast('Salvo localmente','success')}

async function saveServerState(){
  saveLocalOnly();
  try {
    const response = await fetch('/app_state/', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({clientes, parceiros, precos})
    });
    if (!response.ok) throw new Error('Falha ao salvar no servidor');
    const data = await response.json();
    if (data.saved) { setStatus('Salvo no servidor'); showToast('Salvo no servidor','success'); }
    else { setStatus('Falha ao salvar no servidor'); showToast('Falha ao salvar no servidor','error'); }
  } catch (err) {
    console.error(err);
    setStatus('Erro ao salvar no servidor');
    showToast('Erro ao salvar no servidor','error');
  }
}

async function saveCloudState(){
  saveLocalOnly();
  try {
    const response = await fetch('/app_state_drive/', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({clientes, parceiros, precos})
    });
    if (!response.ok) throw new Error('Falha ao salvar na nuvem');
    const data = await response.json();
    if (data.saved && data.drive) { setStatus('Salvo na nuvem'); showToast('Salvo na nuvem','success'); }
    else if (data.saved) { setStatus('Salvo no servidor, falha na nuvem'); showToast('Salvo no servidor, falha na nuvem','info'); }
    else { setStatus('Falha ao salvar na nuvem'); showToast('Falha ao salvar na nuvem','error'); }
  } catch (err) {
    console.error(err);
    setStatus('Erro ao salvar na nuvem');
    showToast('Erro ao salvar na nuvem','error');
  }
}

function setStatus(message){
  const status = document.getElementById('save-status');
  if(status){ status.textContent = message; }
}

// Toast visual
function _ensureToastContainer(){
  let c = document.querySelector('.toast-container');
  if(!c){ c = document.createElement('div'); c.className='toast-container'; document.body.appendChild(c); }
  return c;
}
function showToast(message, type='info', timeout=3500){
  try{
    const container = _ensureToastContainer();
    const t = document.createElement('div');
    t.className = 'toast '+(type||'info');
    t.textContent = message;
    container.appendChild(t);
    setTimeout(()=>{t.style.opacity='0';t.style.transform='translateY(6px)';}, timeout-400);
    setTimeout(()=>{try{container.removeChild(t)}catch(e){}}, timeout);
  }catch(e){console.warn('Toast failed',e)}
}

// Inicializa o menu de salvar (botão único com opções)
function initSaveMenu(){
  const mainBtn = document.getElementById('save-main-btn');
  const menu = document.getElementById('save-menu');
  const btnLocal = document.getElementById('save-local-btn');
  const btnCloud = document.getElementById('save-cloud-btn');
  if(!mainBtn || !menu) return;
  mainBtn.addEventListener('click', function(e){ e.stopPropagation(); menu.style.display = (menu.style.display==='block'?'none':'block'); });
  // fechar ao clicar fora
  document.addEventListener('click', function(){ if(menu) menu.style.display='none' });
  if(btnLocal) btnLocal.addEventListener('click', function(e){ e.stopPropagation(); menu.style.display='none'; saveLocalOnly(); });
  if(btnCloud) btnCloud.addEventListener('click', function(e){ e.stopPropagation(); menu.style.display='none'; saveCloudState(); });
  const btnExport = document.getElementById('export-btn');
  if(btnExport) btnExport.addEventListener('click', function(e){ e.stopPropagation(); menu.style.display='none'; exportState(); });
  // data source bindings
  const srcSelect = document.getElementById('data-source-select');
  const syncBtn = document.getElementById('sync-server-btn');
  if(srcSelect){ srcSelect.value = getDataSource(); srcSelect.addEventListener('change', function(){ setDataSource(this.value); }); }
  if(syncBtn){ syncBtn.addEventListener('click', function(){ syncBtn.disabled=true; fetchServerState(true).finally(()=>{ syncBtn.disabled=false; }); }); }
  renderDataSourceIndicator();
}

async function exportState(){
  // envia estado atual para o servidor e força download do arquivo gerado
  const payload = {clientes, parceiros, precos};
  try{
    const resp = await fetch('/app_state_download/', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify(payload)
    });
    // show overlay while generating
    showExportOverlay();
    if(!resp.ok){
      const txt = await resp.text();
      showToast('Erro ao exportar: '+txt,'error');
      return;
    }
    const blob = await resp.blob();
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'estado_clientes_parceiros.xlsx';
    document.body.appendChild(a);
    a.click();
    a.remove();
    window.URL.revokeObjectURL(url);
    showToast('Arquivo preparado para download','success');
  }catch(err){
    console.error(err);
    showToast('Erro ao exportar','error');
  }
  finally{
    hideExportOverlay();
  }
}

function showExportOverlay(){
  const ov = document.getElementById('export-overlay');
  if(ov) ov.style.display='flex';
}
function hideExportOverlay(){
  const ov = document.getElementById('export-overlay');
  if(ov) ov.style.display='none';
}

function renderTo(id, html){const el=document.getElementById(id); if(el) el.innerHTML=html}
function statusIndex(status){return STATUS_LIST.indexOf(status)>=0?STATUS_LIST.indexOf(status):0}
function statusBadge(status){const i=statusIndex(status); return `<span class="badge ${STATUS_CLASSES[i]}">${status||'Novo Lead'}</span>`}
function parceiroBadge(id){const p=parceiros.find(x=>x.id===id); return p?`<span class="parceiro-tag">${p.nome}</span>`:'—'}
function formatVencimento(c){const d=c.dataVencimento?daysUntil(c.dataVencimento):null; return d!==null&&d<=60?`<span class="badge badge-vencendo">${d<0?'Vencido':d+' dias'}</span>`:(c.dataVencimento?`<span style="font-size:12px;color:var(--muted)">${fmtDate(c.dataVencimento)}</span>`:'—')}
function tableRows(rows){return rows.join('')}
function uid(){return Date.now()+Math.random().toString(36).slice(2)}
function fmtDate(d){if(!d)return'—';const dt=new Date(d);return dt.toLocaleDateString('pt-BR')}
function fmtMoney(v){return'R$ '+Number(v).toFixed(2).replace('.',',').replace(/\B(?=(\d{3})+(?!\d))/g,'.')}
function fmtPercent(v){return Number(v).toFixed(2).replace(/\.?0+$/,'').replace('.',',')+'%'}
function daysUntil(d){if(!d)return 9999;return Math.ceil((new Date(d)-new Date())/(1000*86400))}
function addDays(d,n){const dt=new Date(d);dt.setDate(dt.getDate()+n);return dt.toISOString().split('T')[0]}

const PAGE_CONFIG = {
  dashboard:{title:'Dashboard', render:renderDashboard},
  clientes:{title:'Clientes', render:renderClientes},
  funil:{title:'Funil de Atendimento', render:renderKanban},
  renovacoes:{title:'Alertas de Renovação', render:renderRenovacoes},
  triagem:{title:'Triagem de Validação', render:startTriagem},
  parceiros:{title:'Parceiros Comerciais', render:renderParceiros},
  tabela:{title:'Tabela de Preços', render:renderTabela},
}

// ==================== NAVIGATION ====================
function nav(page){
  document.querySelectorAll('.nav-item').forEach(el=>{
    el.classList.toggle('active', el.getAttribute('onclick')===`nav('${page}')`);
  });
  document.querySelectorAll('.view').forEach(v=>v.classList.remove('active'));
  document.getElementById('view-'+page).classList.add('active');
  const config=PAGE_CONFIG[page]||{title:page,render:()=>{}};
  document.getElementById('page-title').textContent=config.title;
  renderTo('topbar-actions','');
  config.render();
  // renderiza os controles de salvar novamente e re-bind dos eventos
  try{ renderSaveActions(); initSaveMenu(); }catch(e){}
}

function renderSaveActions(){
  const html = `
    <div style="display:flex;align-items:center;gap:10px">
      <div style="display:flex;align-items:center;gap:8px">
        <label style="font-size:12px;color:var(--muted)">Fonte:</label>
        <select id="data-source-select" style="padding:6px;border-radius:6px;border:1px solid var(--border);background:var(--surface)">
          <option value="server">Servidor</option>
          <option value="local">Local</option>
        </select>
        <button class="btn" id="sync-server-btn" style="padding:6px 10px">Sincronizar</button>
        <span id="data-source-indicator" style="font-size:12px;color:var(--muted)"></span>
      </div>
      <div class="save-dropdown" style="position:relative;display:inline-block">
        <button class="btn btn-sm" id="save-main-btn"><i class="ti ti-device-floppy"></i> Salvar <i class="ti ti-chevron-down" style="margin-left:6px;font-size:12px"></i></button>
        <div id="save-menu" style="position:absolute;right:0;top:36px;background:var(--surface);border:1px solid var(--border);border-radius:6px;box-shadow:0 6px 18px rgba(0,0,0,0.06);display:none;min-width:180px;padding:8px;z-index:60">
          <button class="btn" style="display:block;width:100%;text-align:left;padding:8px;border-radius:6px" id="save-local-btn">Salvar localmente</button>
          <button class="btn" style="display:block;width:100%;text-align:left;padding:8px;border-radius:6px;margin-top:6px" id="save-cloud-btn">Salvar na nuvem</button>
          <button class="btn" style="display:block;width:100%;text-align:left;padding:8px;border-radius:6px;margin-top:6px" id="export-btn">Exportar (.xlsx)</button>
        </div>
      </div>
    </div>
    <span id="save-status" style="margin-left:12px;font-size:13px;color:var(--muted)"></span>
  `;
  const ta = document.getElementById('topbar-actions');
  if(ta) ta.innerHTML = html;
}

function getDataSource(){
  const cached = DB.get('data_source');
  if(cached) return cached;
  if(typeof window !== 'undefined' && Array.isArray(window.INITIAL_CLIENTES) && window.INITIAL_CLIENTES.length>0) return 'server';
  return 'local';
}

function setDataSource(src){
  DB.set('data_source', src);
  renderDataSourceIndicator();
  if(src==='server') fetchServerState(true);
}

function renderDataSourceIndicator(){
  const el = document.getElementById('data-source-indicator');
  if(!el) return;
  const src = getDataSource();
  el.textContent = src==='server' ? 'Usando: servidor' : 'Usando: local';
}

async function fetchServerState(apply){
  try{
    const r = await fetch('/app_state/');
    if(!r.ok) throw new Error('Falha ao obter estado do servidor');
    const data = await r.json();
    if(apply){
      if (Array.isArray(data.clientes) && data.clientes.length) {
        clientes = data.clientes;
      }
      if (Array.isArray(data.parceiros) && data.parceiros.length) {
        parceiros = data.parceiros;
      }
      if (Array.isArray(data.precos) && data.precos.length) {
        precos = data.precos;
      }
      save();
      renderClientes(); renderParceiros(); renderTabela(); renderDashboard();
      showToast('Estado do servidor aplicado','success');
    }
    return data;
  }catch(e){ showToast('Erro ao obter estado do servidor','error'); console.error(e); return null }
}

function updateBadges(){
  const alerts=clientes.filter(c=>c.status!=='Emitido'&&c.dataVencimento&&daysUntil(c.dataVencimento)<60);
  const b=document.getElementById('alert-badge');
  if(b){b.style.display=alerts.length?'':'none';b.textContent=alerts.length}
  const rb=document.getElementById('ren-badge');
  if(rb)rb.textContent=alerts.length;
  const totalCount=document.getElementById('total-count');
  if(totalCount) totalCount.textContent=clientes.length;
}

// ==================== DASHBOARD ====================
function renderDashboard(){
  const total=clientes.length;
  const emitidos=clientes.filter(c=>c.status==='Emitido').length;
  const leads=clientes.filter(c=>c.status==='Novo Lead').length;
  const vencendo=clientes.filter(c=>c.dataVencimento&&daysUntil(c.dataVencimento)<=60).length;
  const faturamento=clientes.filter(c=>c.pago).reduce((s,c)=>s+(parseFloat(c.valorCobrado)||0),0);
  document.getElementById('dashboard-metrics').innerHTML=`
    <div class="metric-card accent"><div class="metric-label">Total de Clientes</div><div class="metric-val">${total}</div><div class="metric-sub">${leads} novos leads</div></div>
    <div class="metric-card success"><div class="metric-label">Emitidos</div><div class="metric-val">${emitidos}</div><div class="metric-sub">${Math.round(total?emitidos/total*100:0)}% do total</div></div>
    <div class="metric-card warn"><div class="metric-label">Renovações ≤60 dias</div><div class="metric-val">${vencendo}</div><div class="metric-sub">requerem contato</div></div>
    <div class="metric-card"><div class="metric-label">Faturamento Recebido</div><div class="metric-val" style="font-size:18px">${fmtMoney(faturamento)}</div><div class="metric-sub">pagamentos confirmados</div></div>
  `;
  const urgentes=clientes.filter(c=>c.dataVencimento&&daysUntil(c.dataVencimento)<=60).sort((a,b)=>daysUntil(a.dataVencimento)-daysUntil(b.dataVencimento)).slice(0,5);
  const al=document.getElementById('dashboard-alerts');
  if(!urgentes.length){al.innerHTML='<p style="font-size:13px;color:var(--muted);text-align:center;padding:20px">Nenhum alerta no momento ✓</p>';return}
  al.innerHTML=urgentes.map(c=>{
    const d=daysUntil(c.dataVencimento);
    const cls=d<0?'red':'yellow';
    const txt=d<0?`Vencido há ${Math.abs(d)} dias`:`Vence em ${d} dias`;
    return`<div class="alert-item ${cls}" onclick="openDetail('${c.id}')" style="cursor:pointer;margin-bottom:8px">
      <div class="alert-icon ${cls}"><i class="ti ti-certificate"></i></div>
      <div class="alert-info"><div class="alert-name">${c.nome}</div><div class="alert-detail">${txt} · ${c.tipoCert||'—'}</div></div>
      <button class="btn btn-sm" onclick="event.stopPropagation();openModal('contato','${c.id}')"><i class="ti ti-phone"></i></button>
    </div>`;
  }).join('');
  const recent=clientes.slice().sort((a,b)=>new Date(b.criadoEm||0)-new Date(a.criadoEm||0)).slice(0,6);
  document.getElementById('dashboard-recent').innerHTML=`<table style="width:100%;border-collapse:collapse">${recent.map(c=>`
    <tr onclick="openDetail('${c.id}')" style="cursor:pointer;border-bottom:1px solid var(--border)">
      <td style="padding:10px 16px;font-size:13px">${c.nome}</td>
      <td style="padding:10px 16px"><span class="badge ${STATUS_CLASSES[STATUS_LIST.indexOf(c.status)]||'badge-novo'}">${c.status||'Novo Lead'}</span></td>
      <td style="padding:10px 16px;color:var(--muted);font-size:12px">${fmtDate(c.criadoEm)}</td>
    </tr>`).join('')}</table>`;
}

// ==================== CLIENTES ====================
function renderClientes(){
  const q=(document.getElementById('search-cliente')?.value||'').toLowerCase();
  const sf=document.getElementById('filter-status')?.value||'';
  let list=clientes.filter(c=>{
    const match=!q||(c.nome||'').toLowerCase().includes(q)||(c.cpfCnpj||'').includes(q);
    const sm=!sf||c.status===sf;
    return match&&sm;
  });
  const tbody=document.getElementById('clientes-tbody');
  const empty=document.getElementById('clientes-empty');
  if(!list.length){tbody.innerHTML='';empty.style.display='';return}
  empty.style.display='none';
  const rows=list.map(c=>{
    const vBadge=formatVencimento(c);
    return`<tr>
      <td><strong style="cursor:pointer;color:var(--accent)" onclick="openDetail('${c.id}')">${c.nome}</strong></td>
      <td style="font-family:monospace;font-size:12px">${c.cpfCnpj||'—'}</td>
      <td><span class="tipo-cert">${c.tipoCert||'—'}</span></td>
      <td>${statusBadge(c.status)}</td>
      <td>${parceiroBadge(c.parceiroId)}</td>
      <td>${vBadge}</td>
      <td><button class="btn btn-sm" onclick="openDetail('${c.id}')"><i class="ti ti-eye"></i></button> <button class="btn btn-sm" onclick="editCliente('${c.id}')"><i class="ti ti-edit"></i></button> <button class="btn btn-sm" onclick="deleteCliente('${c.id}')" style="color:var(--danger)"><i class="ti ti-trash"></i></button></td>
    </tr>`;
  });
  tbody.innerHTML=tableRows(rows);
}

function editCliente(id){editingId=id;openModal('cliente')}
function deleteCliente(id){if(confirm('Remover este cliente?')){clientes=clientes.filter(c=>c.id!==id);save();renderClientes();renderDashboard()}}

// ==================== KANBAN ====================
function renderKanban(){
  const board=document.getElementById('kanban-board');
  board.innerHTML=STATUS_LIST.map((s,i)=>{
    const cards=clientes.filter(c=>c.status===s);
    return`<div class="kanban-col">
      <div class="kanban-col-head" style="color:${KANBAN_COLORS[i]}">${s} <span style="background:${KANBAN_COLORS[i]}22;color:${KANBAN_COLORS[i]};padding:1px 7px;border-radius:10px;font-size:11px">${cards.length}</span></div>
      ${cards.map(c=>`<div class="kanban-card" onclick="openDetail('${c.id}')">
        <div class="kanban-card-name">${c.nome}</div>
        <div class="kanban-card-sub">${c.tipoCert||'Tipo não definido'}</div>
        <div class="kanban-card-footer">
          <span style="font-size:11px;color:var(--muted)">${fmtDate(c.criadoEm)}</span>
          ${c.parceiroId?`<span class="parceiro-tag" style="font-size:10px">${(parceiros.find(p=>p.id===c.parceiroId)||{}).nome||''}</span>`:''}
        </div>
      </div>`).join('')}
    </div>`;
  }).join('');
}

// ==================== RENOVAÇÕES ====================
function renderRenovacoes(){
  const urgentes=clientes.filter(c=>c.dataVencimento&&daysUntil(c.dataVencimento)<=30).sort((a,b)=>daysUntil(a.dataVencimento)-daysUntil(b.dataVencimento));
  const normais=clientes.filter(c=>c.dataVencimento&&daysUntil(c.dataVencimento)>30&&daysUntil(c.dataVencimento)<=90).sort((a,b)=>daysUntil(a.dataVencimento)-daysUntil(b.dataVencimento));
  const renderAlert=(c,cls)=>{
    const d=daysUntil(c.dataVencimento);
    const txt=d<0?`Vencido há ${Math.abs(d)} dias`:`Vence em ${d} dias`;
    return`<div class="alert-item ${cls}" style="cursor:pointer" onclick="openDetail('${c.id}')">
      <div class="alert-icon ${cls}"><i class="ti ti-certificate"></i></div>
      <div class="alert-info">
        <div class="alert-name">${c.nome}</div>
        <div class="alert-detail">${txt} · ${c.tipoCert||'—'} · ${c.telefone||'Sem telefone'}</div>
      </div>
      <button class="btn btn-sm btn-primary" onclick="event.stopPropagation();openModal('contato','${c.id}')">Registrar Contato</button>
    </div>`;
  };
  document.getElementById('ren-urgente').innerHTML=urgentes.length?urgentes.map(c=>renderAlert(c,'red')).join(''):'<p style="font-size:13px;color:var(--muted)">Nenhum vencimento urgente ✓</p>';
  document.getElementById('ren-normal').innerHTML=normais.length?normais.map(c=>renderAlert(c,'yellow')).join(''):'<p style="font-size:13px;color:var(--muted)">Nenhum no período ✓</p>';
}

// ==================== TRIAGEM ====================
function startTriagem(){
  triagemStep=0;triagemData={};renderTriagem();
}
const triagem=[
  {q:'O cliente possui CNH (Carteira Nacional de Habilitação)?',opts:['Sim, possui CNH','Não possui CNH']},
  {q:'O cliente já teve certificado digital anteriormente?',opts:['Sim, já teve certificado','Não, é a primeira vez']},
  {q:'Verificar no Portal Soluti: existe biometria cadastrada para este cliente?',opts:['Sim, biometria encontrada','Não encontrada']},
];
function renderTriagem(){
  const el=document.getElementById('triagem-content');
  let html='<div style="margin-bottom:14px;font-size:11px;color:var(--muted);font-weight:700;text-transform:uppercase;letter-spacing:.5px">Triagem de Validação</div>';
  if(triagemStep===0){
    html+=`<div class="triagem-q">${triagem[0].q}</div><div class="triagem-opts">${triagem[0].opts.map((o,i)=>`<div class="triagem-opt" onclick="triagemAnswer(0,${i})">${o}</div>`).join('')}</div>`;
  } else if(triagemStep===1){
    if(triagemData[0]===0){html+=`<div class="triagem-result"><i class="ti ti-video" style="margin-right:6px"></i>Validação por Videoconferência — cliente possui CNH.</div>`;html+=`<button class="btn" style="margin-top:12px" onclick="startTriagem()"><i class="ti ti-refresh"></i> Nova triagem</button>`;
    } else {html+=`<div class="triagem-q">${triagem[1].q}</div><div class="triagem-opts">${triagem[1].opts.map((o,i)=>`<div class="triagem-opt" onclick="triagemAnswer(1,${i})">${o}</div>`).join('')}</div>`;}
  } else if(triagemStep===2){
    if(triagemData[1]===1){html+=`<div class="triagem-result warn"><i class="ti ti-map-pin" style="margin-right:6px"></i>Validação Presencial obrigatória — sem CNH e sem certificado anterior.</div>`;html+=`<button class="btn" style="margin-top:12px" onclick="startTriagem()"><i class="ti ti-refresh"></i> Nova triagem</button>`;
    } else {html+=`<div class="triagem-q">${triagem[2].q}</div><div class="triagem-opts">${triagem[2].opts.map((o,i)=>`<div class="triagem-opt" onclick="triagemAnswer(2,${i})">${o}</div>`).join('')}</div>`;}
  } else if(triagemStep===3){
    if(triagemData[2]===0){html+=`<div class="triagem-result"><i class="ti ti-video" style="margin-right:6px"></i>Validação por Videoconferência — biometria encontrada no Portal Soluti.</div>`;}
    else{html+=`<div class="triagem-result warn"><i class="ti ti-map-pin" style="margin-right:6px"></i>Validação Presencial obrigatória — sem biometria cadastrada.</div>`;}
    html+=`<button class="btn" style="margin-top:12px" onclick="startTriagem()"><i class="ti ti-refresh"></i> Nova triagem</button>`;
  }
  el.innerHTML=html;
}
function triagemAnswer(q,ans){triagemData[q]=ans;triagemStep++;renderTriagem()}

// ==================== PARCEIROS ====================
function renderParceiros(){
  const tbody=document.getElementById('parceiros-tbody');
  const empty=document.getElementById('parceiros-empty');
  if(!parceiros.length){tbody.innerHTML='';empty.style.display='';return}
  empty.style.display='none';
  tbody.innerHTML=parceiros.map(p=>{
    const count=clientes.filter(c=>c.parceiroId===p.id).length;
    return`<tr><td><strong>${p.nome}</strong></td><td>${p.tipo||'—'}</td><td>${p.comissao!=null?fmtPercent(p.comissao):'—'}</td><td>${p.contato||'—'}</td><td><span style="font-size:13px;font-weight:700;color:var(--accent)">${count}</span></td>
    <td><button class="btn btn-sm" onclick="editParceiro('${p.id}')"><i class="ti ti-edit"></i></button> <button class="btn btn-sm" onclick="deleteParceiro('${p.id}')" style="color:var(--danger)"><i class="ti ti-trash"></i></button></td></tr>`;
  }).join('');
}
function editParceiro(id){editingId=id;openModal('parceiro')}
function deleteParceiro(id){if(confirm('Remover parceiro?')){parceiros=parceiros.filter(p=>p.id!==id);save();renderParceiros()}}

// ==================== TABELA PREÇOS ====================
function renderTabela(){
  document.getElementById('tabela-tbody').innerHTML=precos.map(p=>`<tr>
    <td><strong>${p.tipo}</strong></td><td>${p.validade}</td><td style="font-weight:700;color:var(--success)">${fmtMoney(p.preco)}</td>
    <td><button class="btn btn-sm" onclick="editPreco('${p.id}')"><i class="ti ti-edit"></i></button> <button class="btn btn-sm" onclick="deletePreco('${p.id}')" style="color:var(--danger)"><i class="ti ti-trash"></i></button></td>
  </tr>`).join('');
}
function editPreco(id){editingId=id;openModal('preco')}
function deletePreco(id){if(confirm('Remover?')){precos=precos.filter(p=>p.id!==id);save();renderTabela()}}

// ==================== MODAIS ====================
function openModal(type, extraId){
  editingId=editingId||extraId||null;
  const overlay=document.getElementById('modal-overlay');
  const box=document.getElementById('modal-box');
  overlay.classList.add('open');
  if(type==='cliente')renderClienteModal(box);
  if(type==='parceiro')renderParceiroModal(box);
  if(type==='preco')renderPrecoModal(box);
  if(type==='contato')renderContatoModal(box,extraId||editingId);
}
function closeModal(e){if(e.target===document.getElementById('modal-overlay')||e===true){document.getElementById('modal-overlay').classList.remove('open');editingId=null}}

function renderClienteModal(box){
  const c=editingId?clientes.find(x=>x.id===editingId):{};
  const pOpts=parceiros.map(p=>`<option value="${p.id}"${c.parceiroId===p.id?' selected':''}>${p.nome}</option>`).join('');
  const tOpts=precos.map(p=>`<option value="${p.tipo}"${c.tipoCert===p.tipo?' selected':''}>${p.tipo} — ${fmtMoney(p.preco)}</option>`).join('');
  box.innerHTML=`
  <div class="modal-head"><h2>${editingId?'Editar Cliente':'Novo Cliente'}</h2><button class="btn btn-sm" onclick="closeModal(true)"><i class="ti ti-x"></i></button></div>
  <div class="modal-body">
    <div class="tabs">
      <div class="tab active" onclick="switchTab(this,'tab-dados')">Dados Pessoais</div>
      <div class="tab" onclick="switchTab(this,'tab-cert')">Certificado & Pagamento</div>
      <div class="tab" onclick="switchTab(this,'tab-soluti')">Kit Soluti</div>
    </div>
    <div id="tab-dados" class="tab-pane">
      <div class="form-grid">
        <div class="field form-full"><label>Nome Completo *</label><input id="f-nome" value="${c.nome||''}" placeholder="Nome do cliente"></div>
        <div class="field"><label>CPF / CNPJ</label><input id="f-cpfcnpj" value="${c.cpfCnpj||''}" placeholder="000.000.000-00"></div>
        <div class="field"><label>Data de Nascimento</label><input id="f-nasc" type="date" value="${c.dataNasc||''}"></div>
        <div class="field"><label>Telefone / WhatsApp</label><input id="f-tel" value="${c.telefone||''}" placeholder="(00) 00000-0000"></div>
        <div class="field"><label>E-mail</label><input id="f-email" value="${c.email||''}" placeholder="email@exemplo.com"></div>
        <div class="field form-full"><label>Parceiro / Indicação</label><select id="f-parceiro"><option value="">Nenhum (direto)</option>${pOpts}</select></div>
        <div class="field"><label>Origem do Lead</label><select id="f-origem"><option${c.origem==='Indicação'?' selected':''}>Indicação</option><option${c.origem==='Google Ads'?' selected':''}>Google Ads</option><option${c.origem==='Instagram'?' selected':''}>Instagram</option><option${c.origem==='Site'?' selected':''}>Site</option><option${c.origem==='Direto'?' selected':''}>Direto</option></select></div>
        <div class="field"><label>Status do Atendimento</label><select id="f-status">${STATUS_LIST.map(s=>`<option${c.status===s?' selected':''}>${s}</option>`).join('')}</select></div>
        <div class="field form-full"><label>Observações</label><textarea id="f-obs">${c.obs||''}</textarea></div>
      </div>
    </div>
    <div id="tab-cert" class="tab-pane" style="display:none">
      <div class="form-grid">
        <div class="field"><label>Tipo de Certificado</label><select id="f-tipo">${tOpts}</select></div>
        <div class="field"><label>Data de Emissão</label><input id="f-emissao" type="date" value="${c.dataEmissao||''}"></div>
        <div class="field"><label>Data de Vencimento</label><input id="f-venc" type="date" value="${c.dataVencimento||''}"></div>
        <div class="field"><label>Valor Cobrado (R$)</label><input id="f-valor" type="number" step="0.01" value="${c.valorCobrado||''}" placeholder="0,00"></div>
        <div class="field"><label>Forma de Pagamento</label><select id="f-pagform"><option${c.formaPag==='Pix'?' selected':''}>Pix</option><option${c.formaPag==='Boleto'?' selected':''}>Boleto</option><option${c.formaPag==='Cartão'?' selected':''}>Cartão</option><option${c.formaPag==='Dinheiro'?' selected':''}>Dinheiro</option></select></div>
        <div class="field"><label>Pagamento Confirmado?</label><select id="f-pago"><option value="false"${!c.pago?' selected':''}>Não confirmado</option><option value="true"${c.pago?' selected':''}>✓ Pago / Confirmado</option></select></div>
        <div class="field"><label>Tipo de Validação</label><select id="f-valid"><option${c.tipoValidacao==='Videoconferência'?' selected':''}>Videoconferência</option><option${c.tipoValidacao==='Presencial'?' selected':''}>Presencial</option></select></div>
        <div class="field"><label>Data da Videoconferência</label><input id="f-videodata" type="datetime-local" value="${c.dataVideo||''}"></div>
      </div>
    </div>
    <div id="tab-soluti" class="tab-pane" style="display:none">
      <p style="font-size:12px;color:var(--muted);margin-bottom:14px">Dados gerados após a videoconferência no Portal Soluti.</p>
      <div class="form-grid">
        <div class="field form-full"><label>Link de Instalação Soluti</label><input id="f-link" value="${c.solutiLink||''}" placeholder="https://..."></div>
        <div class="field form-full"><label>Chave de Acesso</label><input id="f-chave" value="${c.solutiChave||''}" placeholder="XXXX-XXXX-XXXX-XXXX"></div>
        <div class="field form-full"><label>Destinatário do Kit (contador, cliente, etc.)</label><input id="f-dest" value="${c.kitDestinatario||''}" placeholder="Nome ou e-mail do destinatário"></div>
        <div class="field form-full"><label>Kit Enviado?</label><select id="f-kitenviado"><option value="false"${!c.kitEnviado?' selected':''}>Não enviado</option><option value="true"${c.kitEnviado?' selected':''}>✓ Enviado</option></select></div>
      </div>
    </div>
  </div>
  <div class="modal-foot">
    <button class="btn" onclick="closeModal(true)">Cancelar</button>
    <button class="btn btn-primary" onclick="saveCliente()"><i class="ti ti-device-floppy"></i> Salvar Cliente</button>
  </div>`;
  // Auto-fill vencimento ao escolher emissao
  document.getElementById('f-emissao').addEventListener('change',function(){
    if(this.value){document.getElementById('f-venc').value=addDays(this.value,365)}
  });
}

function switchTab(el,tabId){
  el.closest('.tabs').querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));
  el.classList.add('active');
  document.querySelectorAll('.tab-pane').forEach(p=>p.style.display='none');
  document.getElementById(tabId).style.display='';
}

function saveCliente(){
  const nome=document.getElementById('f-nome').value.trim();
  if(!nome){alert('Nome obrigatório');return}
  const c=editingId?clientes.find(x=>x.id===editingId):{id:uid(),criadoEm:new Date().toISOString().split('T')[0],historico:[]};
  c.nome=nome;
  c.cpfCnpj=document.getElementById('f-cpfcnpj').value;
  c.dataNasc=document.getElementById('f-nasc').value;
  c.telefone=document.getElementById('f-tel').value;
  c.email=document.getElementById('f-email').value;
  c.parceiroId=document.getElementById('f-parceiro').value||null;
  c.origem=document.getElementById('f-origem').value;
  c.status=document.getElementById('f-status').value;
  c.obs=document.getElementById('f-obs').value;
  c.tipoCert=document.getElementById('f-tipo').value;
  c.dataEmissao=document.getElementById('f-emissao').value;
  c.dataVencimento=document.getElementById('f-venc').value;
  c.valorCobrado=parseFloat(document.getElementById('f-valor').value)||0;
  c.formaPag=document.getElementById('f-pagform').value;
  c.pago=document.getElementById('f-pago').value==='true';
  c.tipoValidacao=document.getElementById('f-valid').value;
  c.dataVideo=document.getElementById('f-videodata').value;
  c.solutiLink=document.getElementById('f-link').value;
  c.solutiChave=document.getElementById('f-chave').value;
  c.kitDestinatario=document.getElementById('f-dest').value;
  c.kitEnviado=document.getElementById('f-kitenviado').value==='true';
  if(!editingId)clientes.unshift(c);
  save();closeModal(true);renderClientes();renderDashboard();renderKanban();
  editingId=null;
}

function renderParceiroModal(box){
  const p=editingId?parceiros.find(x=>x.id===editingId):{};
  box.innerHTML=`
  <div class="modal-head"><h2>${editingId?'Editar Parceiro':'Novo Parceiro'}</h2><button class="btn btn-sm" onclick="closeModal(true)"><i class="ti ti-x"></i></button></div>
  <div class="modal-body">
    <div class="form-grid">
      <div class="field form-full"><label>Nome / Escritório *</label><input id="p-nome" value="${p.nome||''}" placeholder="Ex: Escritório Contábil Silva"></div>
      <div class="field"><label>Tipo</label><select id="p-tipo"><option${p.tipo==='Contador'?' selected':''}>Contador</option><option${p.tipo==='Advogado'?' selected':''}>Advogado</option><option${p.tipo==='Escritório'?' selected':''}>Escritório</option><option${p.tipo==='Correspondente'?' selected':''}>Correspondente</option><option${p.tipo==='Outro'?' selected':''}>Outro</option></select></div>
      <div class="field"><label>Telefone</label><input id="p-tel" value="${p.telefone||''}" placeholder="(00) 00000-0000"></div>
      <div class="field"><label>E-mail</label><input id="p-email" value="${p.email||''}" placeholder="contato@escritorio.com"></div>
      <div class="field form-full"><label>Comissão (%)</label><input id="p-comissao" type="number" step="0.01" min="0" value="${p.comissao!=null?p.comissao:''}" placeholder="10"></div>
      <div class="field form-full"><label>Contato Principal</label><input id="p-contato" value="${p.contato||''}" placeholder="Nome do responsável"></div>
    </div>
  </div>
  <div class="modal-foot">
    <button class="btn" onclick="closeModal(true)">Cancelar</button>
    <button class="btn btn-primary" onclick="saveParceiro()"><i class="ti ti-device-floppy"></i> Salvar</button>
  </div>`;
}
// Inicializa comportamentos ao carregar o DOM
document.addEventListener('DOMContentLoaded', function(){
  try{ renderSaveActions(); initSaveMenu();
    // se a fonte padrão for servidor e não há clientes locais, aplica estado do servidor
    if(getDataSource()==='server' && (!clientes || clientes.length===0)){
      fetchServerState(true);
    }
  }catch(e){}
});

function saveParceiro(){
  const nome=document.getElementById('p-nome').value.trim();
  if(!nome){alert('Nome obrigatório');return}
  const p=editingId?parceiros.find(x=>x.id===editingId):{id:uid()};
  p.nome=nome;p.tipo=document.getElementById('p-tipo').value;
  p.telefone=document.getElementById('p-tel').value;p.email=document.getElementById('p-email').value;
  const comissao=parseFloat(document.getElementById('p-comissao').value);
  p.comissao=Number.isFinite(comissao)?comissao:null;
  p.contato=document.getElementById('p-contato').value;
  if(!editingId)parceiros.push(p);
  save();closeModal(true);renderParceiros();editingId=null;
}

function renderPrecoModal(box){
  const p=editingId?precos.find(x=>x.id==editingId):{};
  box.innerHTML=`
  <div class="modal-head"><h2>${editingId?'Editar Preço':'Novo Tipo de Certificado'}</h2><button class="btn btn-sm" onclick="closeModal(true)"><i class="ti ti-x"></i></button></div>
  <div class="modal-body">
    <div class="form-grid">
      <div class="field form-full"><label>Tipo de Certificado *</label><input id="pr-tipo" value="${p.tipo||''}" placeholder="Ex: e-CPF A1"></div>
      <div class="field"><label>Validade</label><input id="pr-valid" value="${p.validade||'1 ano'}" placeholder="1 ano, 3 anos..."></div>
      <div class="field"><label>Preço (R$) *</label><input id="pr-preco" type="number" step="0.01" value="${p.preco||''}" placeholder="0,00"></div>
    </div>
  </div>
  <div class="modal-foot">
    <button class="btn" onclick="closeModal(true)">Cancelar</button>
    <button class="btn btn-primary" onclick="savePreco()"><i class="ti ti-device-floppy"></i> Salvar</button>
  </div>`;
}

function savePreco(){
  const tipo=document.getElementById('pr-tipo').value.trim();
  if(!tipo){alert('Tipo obrigatório');return}
  const p=editingId?precos.find(x=>x.id==editingId):{id:uid()};
  p.tipo=tipo;p.validade=document.getElementById('pr-valid').value;
  p.preco=parseFloat(document.getElementById('pr-preco').value)||0;
  if(!editingId)precos.push(p);
  save();closeModal(true);renderTabela();editingId=null;
}

function renderContatoModal(box,cid){
  const c=clientes.find(x=>x.id===cid);
  if(!c)return;
  box.innerHTML=`
  <div class="modal-head"><h2>Registrar Contato — ${c.nome}</h2><button class="btn btn-sm" onclick="closeModal(true)"><i class="ti ti-x"></i></button></div>
  <div class="modal-body">
    <div class="form-grid">
      <div class="field"><label>Data</label><input id="ct-data" type="date" value="${new Date().toISOString().split('T')[0]}"></div>
      <div class="field"><label>Canal</label><select id="ct-canal"><option>WhatsApp</option><option>Telefone</option><option>E-mail</option><option>Presencial</option></select></div>
      <div class="field form-full"><label>Resultado / Observação</label><textarea id="ct-obs" placeholder="Ex: Cliente confirmou interesse, aguardando documentos..."></textarea></div>
      <div class="field"><label>Novo Status</label><select id="ct-status">${STATUS_LIST.map(s=>`<option${c.status===s?' selected':''}>${s}</option>`).join('')}</select></div>
    </div>
  </div>
  <div class="modal-foot">
    <button class="btn" onclick="closeModal(true)">Cancelar</button>
    <button class="btn btn-primary" onclick="saveContato('${cid}')">Registrar</button>
  </div>`;
}

function saveContato(cid){
  const c=clientes.find(x=>x.id===cid);
  if(!c)return;
  if(!c.historico)c.historico=[];
  c.historico.push({data:document.getElementById('ct-data').value,canal:document.getElementById('ct-canal').value,obs:document.getElementById('ct-obs').value,dt:new Date().toISOString()});
  c.status=document.getElementById('ct-status').value;
  save();closeModal(true);renderClientes();renderRenovacoes();renderKanban();
}

// ==================== DETAIL ====================
function openDetail(id){
  const c=clientes.find(x=>x.id===id);
  if(!c)return;
  const parc=parceiros.find(p=>p.id===c.parceiroId);
  const si=STATUS_LIST.indexOf(c.status);
  const steps=STATUS_LIST.map((s,i)=>`<div class="step${i<si?' done':i===si?' current':''}">${s}</div>`).join('');
  const hist=(c.historico||[]).slice().reverse().map(h=>`<div class="contact-entry"><span class="dt">${fmtDate(h.data)}<br><small>${h.canal}</small></span><span>${h.obs||'—'}</span></div>`).join('')||'<p style="font-size:12px;color:var(--muted)">Nenhum contato registrado</p>';
  const kit=c.solutiLink||c.solutiChave?`<div class="kit-box"><div class="kit-label"><i class="ti ti-key"></i> Kit de Instalação Soluti</div><div class="kit-row"><strong>Link:</strong> <a href="${c.solutiLink}" style="color:var(--accent)" target="_blank">${c.solutiLink}</a></div><div class="kit-row"><strong>Chave:</strong> <code>${c.solutiChave}</code></div><div class="kit-row"><strong>Destinatário:</strong> ${c.kitDestinatario||'—'} <span style="color:${c.kitEnviado?'var(--success)':'var(--danger)'}">${c.kitEnviado?'✓ Enviado':'Não enviado'}</span></div></div>`:'<p style="font-size:12px;color:var(--muted)">Kit Soluti ainda não registrado</p>';
  document.getElementById('detail-box').innerHTML=`
  <div class="modal-head">
    <div>
      <h2>${c.nome}</h2>
      <div style="font-size:12px;color:var(--muted);margin-top:2px">${c.cpfCnpj||'CPF/CNPJ não informado'} · Cadastrado em ${fmtDate(c.criadoEm)}</div>
    </div>
    <div style="display:flex;gap:8px">
      <button class="btn btn-sm" onclick="editCliente('${c.id}');closeDetail(true)"><i class="ti ti-edit"></i> Editar</button>
      <button class="btn btn-sm" onclick="closeDetail(true)"><i class="ti ti-x"></i></button>
    </div>
  </div>
  <div class="modal-body">
    <div class="progress-steps" style="margin-bottom:18px">${steps}</div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:20px">
      <div>
        <div class="detail-section">
          <h4>Dados Pessoais</h4>
          <div class="detail-row"><span class="lbl">Telefone</span><span class="val">${c.telefone||'—'}</span></div>
          <div class="detail-row"><span class="lbl">E-mail</span><span class="val" style="word-break:break-all">${c.email||'—'}</span></div>
          <div class="detail-row"><span class="lbl">Nascimento</span><span class="val">${fmtDate(c.dataNasc)}</span></div>
          <div class="detail-row"><span class="lbl">Origem</span><span class="val">${c.origem||'—'}</span></div>
          <div class="detail-row"><span class="lbl">Parceiro</span><span class="val">${parc?`<span class="parceiro-tag">${parc.nome}</span>`:'Sem parceiro'}</span></div>
        </div>
        <div class="detail-section">
          <h4>Certificado</h4>
          <div class="detail-row"><span class="lbl">Tipo</span><span class="val">${c.tipoCert||'—'}</span></div>
          <div class="detail-row"><span class="lbl">Emissão</span><span class="val">${fmtDate(c.dataEmissao)}</span></div>
          <div class="detail-row"><span class="lbl">Vencimento</span><span class="val">${c.dataVencimento?`<span class="badge ${daysUntil(c.dataVencimento)<60?'badge-vencendo':'badge-emitido'}">${fmtDate(c.dataVencimento)}</span>`:'—'}</span></div>
          <div class="detail-row"><span class="lbl">Validação</span><span class="val">${c.tipoValidacao||'—'}</span></div>
          <div class="detail-row"><span class="lbl">Videoconferência</span><span class="val">${c.dataVideo?fmtDate(c.dataVideo):'—'}</span></div>
        </div>
        <div class="detail-section">
          <h4>Pagamento</h4>
          <div class="detail-row"><span class="lbl">Valor</span><span class="val" style="font-weight:700;color:var(--success)">${c.valorCobrado?fmtMoney(c.valorCobrado):'—'}</span></div>
          <div class="detail-row"><span class="lbl">Forma</span><span class="val">${c.formaPag||'—'}</span></div>
          <div class="detail-row"><span class="lbl">Status pagto</span><span class="val"><span style="color:${c.pago?'var(--success)':'var(--danger)'}">${c.pago?'✓ Confirmado':'Pendente'}</span></span></div>
        </div>
      </div>
      <div>
        <div class="detail-section">
          <h4>Kit Soluti</h4>
          ${kit}
        </div>
        <div class="detail-section">
          <h4>Histórico de Contatos</h4>
          <button class="btn btn-sm" style="margin-bottom:8px" onclick="openModal('contato','${c.id}');closeDetail(true)"><i class="ti ti-plus"></i> Registrar Contato</button>
          <div class="contact-log">${hist}</div>
        </div>
        ${c.obs?`<div class="detail-section"><h4>Observações</h4><p style="font-size:13px;color:var(--muted)">${c.obs}</p></div>`:''}
      </div>
    </div>
  </div>`;
  document.getElementById('detail-overlay').classList.add('open');
}
function closeDetail(e){if(e===true||e.target===document.getElementById('detail-overlay')){document.getElementById('detail-overlay').classList.remove('open')}}

// ==================== INIT ====================
async function loadAppState(){
  try {
    const response = await fetch('/app_state/');
    if (response.ok){
      const data = await response.json();
      if (Array.isArray(data.clientes) && data.clientes.length) {
        clientes = data.clientes;
      }
      if (Array.isArray(data.parceiros) && data.parceiros.length) {
        parceiros = data.parceiros;
      } else if (!parceiros.length && typeof window !== 'undefined' && Array.isArray(window.INITIAL_PARCEIROS) && window.INITIAL_PARCEIROS.length>0) {
        parceiros = window.INITIAL_PARCEIROS.slice();
      }
      if (Array.isArray(data.precos) && data.precos.length) {
        precos = data.precos;
      }
      save();
    }
  } catch (err){
    console.warn('Não foi possível carregar estado do servidor', err);
  }
  renderDashboard();
  renderClientes();
  renderParceiros();
  renderTabela();
  updateBadges();
}

loadAppState();
