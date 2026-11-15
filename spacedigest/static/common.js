/* ============================================================
   common.js — общие элементы интерфейса всех страниц:
   тосты, «История», аналитика, меню форматов, пароль на настройки,
   мост к окну приложения (сохранение файлов, выбор папок), Ctrl+, / ⌘,.
   ============================================================ */

function escHtml(s){
  return String(s==null?'':s)
    .replace(/&/g,'&amp;').replace(/</g,'&lt;')
    .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

/* ── Тосты ─────────────────────────────────────────────────── */
function _toastBox(){
  let b = document.getElementById('toast-box');
  if(!b){ b = document.createElement('div'); b.id='toast-box'; document.body.appendChild(b); }
  return b;
}
function toast(msg, type='info', ms=3400){
  const el = document.createElement('div');
  el.className = 'toast '+type;
  const icon = type==='success'?'✓':type==='error'?'✕':type==='warn'?'!':'i';
  el.innerHTML = `<span class="toast-ic">${icon}</span><span>${escHtml(msg)}</span>`;
  _toastBox().appendChild(el);
  requestAnimationFrame(()=>el.classList.add('show'));
  setTimeout(()=>{ el.classList.remove('show'); setTimeout(()=>el.remove(),250); }, ms);
}

/* ── Выпадающее меню (закрытие по клику вне) ───────────────── */
function toggleMenu(id, ev){
  if(ev) ev.stopPropagation();
  const m = document.getElementById(id);
  const open = m.classList.toggle('open');
  if(open){
    const close = (e)=>{ if(!m.contains(e.target)){ m.classList.remove('open'); document.removeEventListener('click',close);} };
    setTimeout(()=>document.addEventListener('click',close),0);
  }
}

/* ── Аналитическая полоса ──────────────────────────────────── */
const Analytics = {
  render(containerId, articles, opts={}){
    const el = document.getElementById(containerId);
    if(!el) return;
    if(!articles || !articles.length){ el.style.display='none'; el.innerHTML=''; return; }
    el.style.display='grid';

    // по источникам (топ-6)
    const bySrc = {};
    articles.forEach(a=>{ const s=a.source_name||'—'; bySrc[s]=(bySrc[s]||0)+1; });
    const srcRows = Object.entries(bySrc).sort((a,b)=>b[1]-a[1]).slice(0,6);
    const srcMax = srcRows.length?srcRows[0][1]:1;

    // по дням
    const byDay = {};
    articles.forEach(a=>{ const d=(a.published_at||'').slice(0,10); if(d) byDay[d]=(byDay[d]||0)+1; });
    let days = Object.entries(byDay).sort((a,b)=>a[0]<b[0]?-1:1);
    if(days.length>21) days = days.slice(-21);
    const dayMax = days.reduce((m,[,c])=>Math.max(m,c),1);

    const srcHtml = srcRows.map(([s,c])=>`
      <div class="an-row">
        <span class="an-lbl" title="${escHtml(s)}">${escHtml(s)}</span>
        <span class="an-track"><span class="an-fill" style="width:${Math.round(c/srcMax*100)}%"></span></span>
        <span class="an-num">${c}</span>
      </div>`).join('') || '<div class="an-empty">нет данных</div>';

    const dayHtml = days.length ? `<div class="an-days">${
        days.map(([d,c])=>`<span class="an-bar" title="${d}: ${c}"><span style="height:${Math.round(c/dayMax*100)}%"></span></span>`).join('')
      }</div><div class="an-days-cap"><span>${days[0][0].slice(5)}</span><span>${days[days.length-1][0].slice(5)}</span></div>`
      : '<div class="an-empty">даты не указаны</div>';

    let dupPanel = '';
    if(opts.showDuplicates){
      const rem = opts.removedCount||0, total = (articles.length+rem)||1;
      const pct = Math.round(rem/total*100);
      dupPanel = `
      <div class="an-panel an-dup">
        <div class="an-title">Дубликаты</div>
        <div class="an-bignum">${rem}</div>
        <div class="an-sub">убрано из ${total} · ${pct}%</div>
      </div>`;
    }

    el.innerHTML = `
      <div class="an-panel">
        <div class="an-title">Топ источников</div>
        <div class="an-bars">${srcHtml}</div>
      </div>
      <div class="an-panel">
        <div class="an-title">По дням${days.length?' ('+days.length+')':''}</div>
        ${dayHtml}
      </div>
      ${dupPanel}`;
  }
};

/* ── Панель «История» ──────────────────────────────────────── */
const History = {
  page: 'parser',
  handlers: {},
  init(page, handlers){
    this.page = page; this.handlers = handlers || {};
    if(!document.getElementById('history-drawer')){
      const wrap = document.createElement('div');
      wrap.innerHTML = `
        <div id="history-overlay" onclick="History.toggle(false)"></div>
        <aside id="history-drawer">
          <div class="hd-head">
            <span>История</span>
            <button class="hd-x" onclick="History.toggle(false)" title="Закрыть">✕</button>
          </div>
          <div class="hd-list" id="history-list"></div>
        </aside>`;
      document.body.appendChild(wrap);
    }
  },
  toggle(force){
    const d=document.getElementById('history-drawer'), o=document.getElementById('history-overlay');
    const open = force===undefined ? !d.classList.contains('open') : force;
    d.classList.toggle('open', open); o.classList.toggle('open', open);
    if(open) this.refresh();
  },
  async refresh(){
    const list = document.getElementById('history-list');
    list.innerHTML = '<div class="hd-empty">Загрузка…</div>';
    try{
      const items = await (await fetch('/api/history')).json();
      if(!items.length){ list.innerHTML='<div class="hd-empty">История пуста.<br>Запустите парсер или дедупликатор.</div>'; return; }
      list.innerHTML = items.map(it=>{
        const isDedup = it.kind==='dedup';
        const isTg    = it.kind==='tg';
        const tag   = isDedup ? 'ДЕДУП' : isTg ? 'TG' : 'ПАРСЕР';
        const meta  = isDedup ? `${it.count} оставлено / ${it.removed||0} убрано`
                    : isTg    ? `${it.count} постов`
                    :           `${it.count} новостей`;
        return `
        <div class="hd-item ${it.kind}">
          <div class="hd-main" onclick="History.open('${it.kind}','${it.id}')">
            <div class="hd-name">
              <span class="hd-tag ${it.kind}">${tag}</span>
              <span class="hd-title">${escHtml(it.name)}</span>
              ${it.translated?'<span class="hd-ru">RU</span>':''}
            </div>
            <div class="hd-meta">${escHtml(it.finished_at)} · ${meta}</div>
          </div>
          <div class="hd-actions">
            <button title="Переименовать" onclick="History.rename('${it.kind}','${it.id}','${escHtml(it.name).replace(/'/g,"&#39;")}')">✎</button>
            <button title="Удалить" onclick="History.del('${it.kind}','${it.id}')">🗑</button>
          </div>
        </div>`;
      }).join('');
    }catch(e){ list.innerHTML='<div class="hd-empty">Не удалось загрузить историю.</div>'; }
  },
  open(kind, id){
    if(this.page===kind && this.handlers[kind]){ this.handlers[kind](id); this.toggle(false); }
    else{
      const url = kind==='dedup' ? ('/dedup?open_dedup='+id)
                : kind==='tg'    ? ('/tg?open_tg='+id)
                :                  ('/?open_job='+id);
      window.location.href = url;
    }
  },
  async rename(kind, id, cur){
    const name = prompt('Новое название:', cur);
    if(name===null) return;
    try{
      await fetch('/api/history/rename',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({kind,id,name})});
      toast('Переименовано','success'); this.refresh();
    }catch(e){ toast('Не удалось переименовать','error'); }
  },
  async del(kind, id){
    if(!confirm('Удалить этот элемент истории безвозвратно?')) return;
    try{
      await fetch('/api/history/delete',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({kind,id})});
      toast('Удалено','success'); this.refresh();
    }catch(e){ toast('Не удалось удалить','error'); }
  }
};

/* ─── Пароль на изменение настроек ─────────────────────────────────────────────
   Токен разблокировки живёт в sessionStorage (до закрытия вкладки).
   adminFetch(url, opts) — как fetch, но добавляет X-Admin-Token; если сервер
   ответил 403 (нужен пароль), показывает модалку, после ввода повторяет запрос. */
const Admin = {
  KEY: 'admin_token',
  get token(){ return sessionStorage.getItem(this.KEY) || ''; },
  set token(v){ v ? sessionStorage.setItem(this.KEY, v) : sessionStorage.removeItem(this.KEY); },

  async status(){
    try{
      return await (await fetch('/api/admin/status', {headers: this.token ? {'X-Admin-Token': this.token} : {}})).json();
    }catch(e){ return {protected:false, unlocked:false}; }
  },

  ask(){                     // показать модалку; резолвится токеном или null (отмена)
    return new Promise(resolve=>{
      document.getElementById('admin-modal')?.remove();
      const ov = document.createElement('div');
      ov.className='modal-ov'; ov.id='admin-modal';
      ov.innerHTML = `
        <div class="modal">
          <div class="modal-t">Изменение настроек</div>
          <div class="modal-sub">Введите пароль администратора (меняется в <b>Настройки → Пароль</b>).</div>
          <input type="password" class="modal-in" id="admin-pw" placeholder="Пароль" autocomplete="current-password">
          <div class="modal-err" id="admin-err"></div>
          <div class="modal-row">
            <button class="mini-btn" id="admin-cancel">Отмена</button>
            <button class="primary" id="admin-ok">Разблокировать</button>
          </div>
        </div>`;
      document.body.appendChild(ov);
      const inp = ov.querySelector('#admin-pw'); inp.focus();
      const done = t => { ov.remove(); resolve(t); };
      ov.addEventListener('click', e=>{ if(e.target===ov) done(null); });
      ov.querySelector('#admin-cancel').onclick = ()=>done(null);
      const submit = async ()=>{
        const pw = inp.value;
        if(!pw){ inp.focus(); return; }
        try{
          const r = await fetch('/api/admin/unlock',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({password:pw})});
          const d = await r.json();
          if(d.ok){ this.token = d.token || ''; Admin.paintLock(); toast('Настройки разблокированы','success'); done(this.token); }
          else{ ov.querySelector('#admin-err').textContent = d.error || 'Неверный пароль'; inp.select(); }
        }catch(e){ ov.querySelector('#admin-err').textContent = 'Сервер недоступен'; }
      };
      ov.querySelector('#admin-ok').onclick = submit;
      inp.addEventListener('keydown', e=>{ if(e.key==='Enter') submit(); if(e.key==='Escape') done(null); });
    });
  },

  async fetch(url, opts={}){  // fetch с токеном и авто-модалкой на 403
    const withTok = t => {
      const o = Object.assign({}, opts);
      o.headers = Object.assign({}, opts.headers||{});
      if(t) o.headers['X-Admin-Token'] = t;
      return fetch(url, o);
    };
    let res = await withTok(this.token);
    if(res.status===403){
      let d=null; try{ d = await res.clone().json(); }catch(e){}
      if(d && d.admin_required){
        const t = await this.ask();
        if(t===null) return res;      // отмена — отдаем исходный 403
        res = await withTok(t);
      }
    }
    return res;
  },

  async lockNow(){
    if(this.token){
      try{ await fetch('/api/admin/lock',{method:'POST',headers:{'X-Admin-Token':this.token}}); }catch(e){}
      this.token=''; Admin.paintLock(); toast('Настройки снова под паролем','info');
    }else{
      await this.ask();
    }
  },

  async paintLock(){
    const btn = document.getElementById('lock-btn');
    const st = await this.status();
    // Класс на body: пока настройки под замком, элементы .admin-gated неактивны.
    document.body.classList.toggle('admin-locked', !!st.protected && !st.unlocked);
    if(!btn) return;
    if(!st.protected){ btn.style.display='none'; return; }
    btn.style.display='';
    const unlocked = st.unlocked;
    btn.textContent = unlocked ? '🔓' : '🔒';
    btn.classList.toggle('unlocked', unlocked);
    btn.title = unlocked
      ? 'Настройки разблокированы — нажмите, чтобы снова закрыть'
      : 'Изменение настроек защищено паролем — нажмите, чтобы разблокировать';
  },
};
function adminFetch(url, opts){ return Admin.fetch(url, opts); }

document.addEventListener('DOMContentLoaded', ()=>{
  const btn = document.getElementById('lock-btn');
  if(btn) btn.onclick = ()=>Admin.lockNow();
  Admin.paintLock();
});

/* ─── Мост к окну приложения ───────────────────────────────────────────────────
   В окне приложения доступен window.pywebview.api (диалоги «Сохранить как»,
   выбор папки/файла). В обычном браузере — привычные загрузки. */
const Native = {
  _ready: null,
  ready(){
    if(this._ready) return this._ready;
    this._ready = new Promise(res=>{
      if(window.pywebview && window.pywebview.api) return res(true);
      let done=false;
      window.addEventListener('pywebviewready', ()=>{ if(!done){done=true;res(true);} });
      setTimeout(()=>{ if(!done){done=true;res(!!(window.pywebview&&window.pywebview.api));} }, 1500);
    });
    return this._ready;
  },
  async available(){ return await this.ready(); },
  async pickFolder(){ return (await this.ready()) ? await window.pywebview.api.pick_folder() : null; },
  async pickFile(kind){ return (await this.ready()) ? await window.pywebview.api.pick_file(kind||'any') : null; },
};

/* Скачать файл: в окне — системный диалог «Сохранить как», в браузере — загрузка. */
async function downloadUrl(url, label){
  if(await Native.available()){
    toast('Готовлю '+(label||'файл')+'…','info',1800);
    const r = await window.pywebview.api.save_url(url);
    if(r && r.ok){
      const el = toastAction('Сохранено: '+r.path, 'Показать в папке', ()=>window.pywebview.api.reveal(r.path));
    }else if(r && r.error){ toast('Не удалось сохранить: '+r.error,'error',6000); }
    return;
  }
  window.location.href = url;
  toast('Готовлю '+(label||'файл')+'…','success');
}

/* Тост с кнопкой действия */
function toastAction(msg, btnText, onClick, ms=7000){
  const el = document.createElement('div');
  el.className = 'toast success';
  el.innerHTML = `<span class="toast-ic">✓</span><span style="flex:1;word-break:break-all">${escHtml(msg)}</span>`;
  const b = document.createElement('button');
  b.className='toast-btn'; b.textContent=btnText; b.onclick=()=>{ onClick(); };
  el.appendChild(b);
  _toastBox().appendChild(el);
  requestAnimationFrame(()=>el.classList.add('show'));
  setTimeout(()=>{ el.classList.remove('show'); setTimeout(()=>el.remove(),250); }, ms);
  return el;
}

/* Публичные настройки (без секретов) — для значений по умолчанию на страницах */
const Prefs = {
  _p: null,
  async get(){ if(!this._p) this._p = fetch('/api/settings/public').then(r=>r.json()).catch(()=>({})); return this._p; },
};

/* Ctrl+, / ⌘, — открыть настройки (как в обычных программах) */
document.addEventListener('keydown', e=>{
  if((e.ctrlKey||e.metaKey) && e.key===','){ e.preventDefault(); if(location.pathname!=='/settings') location.href='/settings'; }
});

/* Часы в шапке */
(function(){
  const t=()=>{ const c=document.getElementById('clock'); if(c) c.textContent=new Date().toLocaleString('ru-RU',{hour12:false}); };
  document.addEventListener('DOMContentLoaded', ()=>{ t(); setInterval(t,1000); });
})();
