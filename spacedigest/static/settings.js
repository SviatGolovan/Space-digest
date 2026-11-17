/* ============================================================
   settings.js — окно «Настройки». Каждое изменение сохраняется сразу.
   ============================================================ */
let S = null;          // настройки (для редактора)
const SECTIONS = ['welcome','general','export','slk','filter','sources','telegram','translation','dedup','data','security','about'];
const $ = id => document.getElementById(id);
const esc = escHtml;
const CATS = ['Свои','Ежедневные новости','Отраслевые издания','Военный космос','Научпоп','Аналитика',
              'Широкопрофильные СМИ','Международные','Коммерческий космос','Космические агентства','Нишевые'];

function authHeaders(extra){ const h = Object.assign({}, extra||{}); if(Admin.token) h['X-Admin-Token']=Admin.token; return h; }
async function postJSON(url, body){
  const r = await Admin.fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body||{})});
  let d = {}; try{ d = await r.json(); }catch(e){}
  if(r.status===403) d._denied = true;
  return d;
}

/* ── разделы ─────────────────────────────────────────────── */
function currentSection(){ const h = location.hash.replace('#',''); return SECTIONS.includes(h) ? h : 'general'; }
function showSection(){
  const sec = currentSection();
  document.querySelectorAll('.set-sec').forEach(s=>s.classList.toggle('active', s.id==='sec-'+sec && !!S));
  document.querySelectorAll('#set-nav a').forEach(a=>a.classList.toggle('active', a.getAttribute('href')==='#'+sec));
  if(!S) return;
  if(sec==='telegram'){ loadTgStatus(); renderChannels(); }
  if(sec==='welcome') loadTgStatus();
  if(sec==='data'){ loadDataInfo(); loadWeeks(); }
  if(sec==='dedup') loadEngine();
  if(sec==='about') loadAbout();
  window.scrollTo(0,0);
}
window.addEventListener('hashchange', showSection);

/* ── загрузка и блокировка ──────────────────────────────── */
async function load(){
  const r = await fetch('/api/settings',{headers:authHeaders()});
  if(r.status===403){ showLock(); return; }
  S = await r.json();
  $('lock-screen').classList.remove('open');
  fill();
  showSection();
}
function showLock(){
  S = null;
  document.querySelectorAll('.set-sec').forEach(s=>s.classList.remove('active'));
  $('lock-screen').classList.add('open');
  setTimeout(()=>$('unlock-pw').focus(), 50);
}
async function unlock(){
  const pw = $('unlock-pw').value;
  if(!pw) return;
  try{
    const d = await (await fetch('/api/admin/unlock',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({password:pw})})).json();
    if(d.ok){ Admin.token = d.token||''; $('unlock-pw').value=''; $('unlock-err').textContent=''; await load(); }
    else{ $('unlock-err').textContent = 'Неверный пароль'; $('unlock-pw').select(); }
  }catch(e){ $('unlock-err').textContent = 'Программа не отвечает'; }
}

async function save(patch, msg){
  const d = await postJSON('/api/settings', patch);
  if(d.ok){ S = d.settings; toast(msg||'Сохранено','success',1400); Prefs._p = null; return true; }
  if(!d._denied) toast(d.error||'Не удалось сохранить','error');
  return false;
}

/* ── заполнение полей ───────────────────────────────────── */
function seg(id, value, onPick){
  const el = $(id);
  el.querySelectorAll('button').forEach(b=>{
    b.classList.toggle('on', b.dataset.v===value);
    b.onclick = ()=>{ el.querySelectorAll('button').forEach(x=>x.classList.toggle('on', x===b)); onPick(b.dataset.v); };
  });
}
function bindNum(id, section, key, msg){
  const el = $(id);
  el.value = S[section][key];
  el.onchange = ()=>{ if(el.value!=='') save({[section]:{[key]:+el.value}}, msg); };
}
function bindToggle(id, section, key, after){
  const el = $(id);
  el.checked = !!S[section][key];
  el.onchange = async ()=>{ await save({[section]:{[key]:el.checked}}); if(after) after(); };
}
function bindText(id, section, key, after){
  const el = $(id);
  el.value = S[section][key] || '';
  el.onchange = async ()=>{ await save({[section]:{[key]:el.value.trim()}}); if(after) after(); };
}

function fill(){
  // Общие
  seg('open_in', S.general.open_in, v=>save({general:{open_in:v}}, 'Применится при следующем запуске'));
  $('start_page').value = S.general.start_page;
  $('start_page').onchange = ()=>save({general:{start_page:$('start_page').value}});
  bindNum('fetch_timeout','fetch','timeout');
  bindNum('fetch_delay','fetch','delay');
  // Источники
  const cats = [...new Set([...CATS, ...allSources().map(s=>s.category).filter(Boolean)])];
  $('src-cat').innerHTML = '<option value="">Все категории</option>' + cats.map(c=>`<option>${esc(c)}</option>`).join('');
  $('ns-cat').innerHTML = cats.map(c=>`<option>${esc(c)}</option>`).join('');
  renderSources();
  // Telegram
  bindText('tg_api_id','telegram','api_id', loadTgStatus);
  bindText('tg_api_hash','telegram','api_hash', loadTgStatus);
  bindNum('tg_lookback','telegram','lookback_days');
  bindToggle('tg_auto','collect','telegram_auto', ()=>{ $('tg_poll').disabled = !$('tg_auto').checked; });
  bindNum('tg_poll','collect','telegram_minutes');
  $('tg_poll').disabled = !S.collect.telegram_auto;
  // Автосбор сайтов
  bindToggle('sites_auto','collect','sites_auto', ()=>{ $('sites_min').disabled = !$('sites_auto').checked; });
  bindNum('sites_min','collect','sites_minutes');
  $('sites_min').disabled = !S.collect.sites_auto;
  bindToggle('ft_on','collect','fulltext', ()=>{ $('ft_min').disabled = !$('ft_on').checked; });
  bindNum('ft_min','collect','fulltext_min', loadFulltext);
  $('ft_min').disabled = !S.collect.fulltext;
  loadFulltext();
  // Выгрузка и ChatGPT
  bindToggle('ex_dedup','export','dedup');
  bindNum('ex_ref_days','export','reference_days');
  bindText('ex_folder','export','folder');
  bindText('ex_gpt_url','export','chatgpt_url');
  seg('ex_gpt_where', S.export.chatgpt_in_app ? 'app' : 'browser',
      v=>save({export:{chatgpt_in_app: v==='app'}}));
  loadPrompt();
  // Дайджест СЛК
  bindNum('slk_period','slk','period_days');
  bindNum('slk_overlap','slk','overlap_days');
  bindToggle('slk_dedup','slk','dedup');
  bindText('slk_folder','slk','folder');
  bindToggle('slk_prefilter','slk','prefilter');
  loadSlk();
  bindTheme();
  bindToggle('gen_fx','general','animations', ()=>setTimeout(()=>location.reload(), 400));
  // Утренняя выгрузка
  bindToggle('mo_on','morning','enabled', loadMorning);
  bindToggle('mo_notify','morning','notify');
  bindToggle('gen_autostart','general','autostart');
  $('mo_time').value = S.morning.time;
  $('mo_time').addEventListener('change', async ()=>{ if($('mo_time').value && await save({morning:{time:$('mo_time').value}}, 'Время сохранено')) loadMorning(); });
  loadMorning();
  // Обновления
  bindText('up_repo','updates','repo', ()=>checkUpdate(true));
  bindToggle('up_auto','updates','auto_check');
  checkUpdate(false);
  // Фильтр мусора
  bindToggle('fl_on','filter','enabled');
  loadWords(); loadFilterSources();
  renderChannels();
  // Перевод
  bindToggle('tr_default','translation','default_on');
  const showKey = ()=>{ $('deepl-row').style.display = S.translation.provider==='deepl' ? '' : 'none'; };
  seg('tr_provider', S.translation.provider, async v=>{ await save({translation:{provider:v}}); showKey(); });
  bindText('tr_key','translation','deepl_key');
  showKey();
  // Дедупликатор
  $('dd_engine').value = S.dedup.engine==='tfidf' ? 'tfidf' : 'auto';
  $('dd_engine').onchange = ()=>save({dedup:{engine:$('dd_engine').value}});
  bindNum('dd_window','dedup','window_days');
  bindToggle('dd_guard','dedup','number_guard');
  bindToggle('dd_related','dedup','related');
  bindNum('dd_rel_thr','dedup','story_threshold');
  $('dd_threshold').value = S.dedup.threshold;
  $('dd_thr_val').textContent = (+S.dedup.threshold).toFixed(2);
  $('dd_threshold').oninput = ()=>{ $('dd_thr_val').textContent = (+$('dd_threshold').value).toFixed(2); };
  $('dd_threshold').onchange = ()=>save({dedup:{threshold:+$('dd_threshold').value}});
  bindToggle('dd_cross','dedup','cross_compare');
  bindToggle('dd_prefer','dedup','prefer_file_as_base');
  // Пароль
  paintPassword();
}

/* ── источники ──────────────────────────────────────────── */
function allSources(){
  return [...(S._builtin_sources||[]), ...(S.sources.custom||[]).map(s=>Object.assign({custom:true, enabled:true}, s))];
}
function renderSources(){
  const q = ($('src-search').value||'').toLowerCase();
  const cat = $('src-cat').value;
  const list = allSources().filter(s=>(!cat || s.category===cat) &&
      (!q || (s.name||'').toLowerCase().includes(q) || (s.url||'').toLowerCase().includes(q)));
  $('src-body').innerHTML = list.map(s=>`
    <tr>
      <td style="width:52px"><label class="switch" title="Отмечен по умолчанию на странице «Сайты»">
        <input type="checkbox" ${s.enabled?'checked':''} onchange="setSrcEnabled('${esc(s.id)}',this.checked)"><span class="slider"></span></label></td>
      <td><div class="s-name">${esc(s.name)} ${s.custom?'<span class="src-custom-tag">СВОЙ</span>':''}</div>
          <div class="s-url">${esc(s.url)}</div><div class="s-test" id="t-${esc(s.id)}"></div></td>
      <td class="s-meta">${esc(s.category||'—')}<br>${esc(s.region||'—')}</td>
      <td class="s-act"><button title="Проверить ленту" onclick="testSrc('${esc(s.id)}')">Проверить</button>${s.custom?
        `<button title="Изменить" onclick="editSrc('${esc(s.id)}')">✎</button><button class="del" title="Удалить" onclick="delSrc('${esc(s.id)}')">✕</button>`:''}</td>
    </tr>`).join('') || '<tr><td colspan="4"><div class="set-note" style="padding:14px">Ничего не найдено</div></td></tr>';
  const all = allSources();
  $('src-summary').textContent = `Встроенных: ${(S._builtin_sources||[]).length} · своих: ${(S.sources.custom||[]).length} · отмечено по умолчанию: ${all.filter(s=>s.enabled).length}`;
}
async function setSrcEnabled(id, on){
  const d = await postJSON('/api/sources/update',{id, enabled:on});
  if(d.ok){
    const s = allSources().find(x=>x.id===id);
    (S._builtin_sources||[]).forEach(x=>{ if(x.id===id) x.enabled=on; });
    (S.sources.custom||[]).forEach(x=>{ if(x.id===id) x.enabled=on; });
    renderSources(); toast((on?'Включён: ':'Выключен: ')+(s?s.name:''),'success',1400);
  }else if(!d._denied) toast(d.error||'Ошибка','error');
}
async function testSrc(id){
  const s = allSources().find(x=>x.id===id); if(!s) return;
  const el = $('t-'+id); el.className='s-test'; el.textContent='проверяю…';
  const d = await (await fetch('/api/sources/test',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({url:s.url,name:s.name})})).json();
  if(d.ok){ el.className='s-test set-note ok'; el.textContent = `✓ лента работает: ${d.count} новостей`+(d.latest?` · последняя ${d.latest.published_at||''}`:''); }
  else{ el.className='s-test set-note err'; el.textContent = '✗ '+(d.error||'ошибка'); }
}
function toggleAdd(force, src){
  const f = $('add-form');
  const open = force===undefined ? !f.classList.contains('open') : force;
  f.classList.toggle('open', open);
  $('ns-id').value = src ? src.id : '';
  $('ns-name').value = src ? src.name : ''; $('ns-url').value = src ? src.url : '';
  $('ns-region').value = src && src.region!=='—' ? src.region : ''; $('ns-cat').value = src ? src.category : 'Свои';
  $('ns-save').textContent = src ? 'Сохранить' : 'Добавить';
  $('ns-test').textContent=''; $('ns-test').className='set-note';
  if(open) $('ns-name').focus();
}
function editSrc(id){ toggleAdd(true, allSources().find(x=>x.id===id)); }
async function testNew(){
  const url = $('ns-url').value.trim(); const el = $('ns-test');
  if(!url){ el.className='set-note warn'; el.textContent='Укажите адрес ленты'; return; }
  el.className='set-note'; el.textContent='проверяю…';
  const d = await (await fetch('/api/sources/test',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({url})})).json();
  el.className = 'set-note '+(d.ok?'ok':'err');
  el.textContent = d.ok ? `✓ работает: ${d.count} новостей` : '✗ '+(d.error||'ошибка');
}
async function saveSource(){
  const body = {name:$('ns-name').value.trim(), url:$('ns-url').value.trim(), region:$('ns-region').value.trim(), category:$('ns-cat').value};
  if(!body.name || !body.url){ toast('Укажите название и адрес','warn'); return; }
  const id = $('ns-id').value;
  const d = await postJSON(id?'/api/sources/update':'/api/sources/add', id?Object.assign({id},body):body);
  if(d.error){ toast(d.error,'error'); return; }
  if(d._denied) return;
  toggleAdd(false); await load(); toast(id?'Источник изменён':'Источник добавлен','success');
}
async function delSrc(id){
  const s = allSources().find(x=>x.id===id);
  if(!confirm('Удалить источник «'+(s?s.name:id)+'»?')) return;
  const d = await postJSON('/api/sources/delete',{id});
  if(d.ok){ await load(); toast('Источник удалён','success'); } else if(!d._denied) toast(d.error||'Ошибка','error');
}

/* ── Telegram ───────────────────────────────────────────── */
let TG = null;
async function loadTgStatus(){
  const line = $('tg-acc-line'), act = $('tg-acc-actions'), login = $('tg-login');
  line.innerHTML = 'Проверка подключения…'; act.innerHTML='';
  try{ TG = await (await fetch('/api/tg/status')).json(); }catch(e){ line.textContent='Нет ответа'; return; }
  const wp = $('w-tg-state');
  if(!TG.configured){
    line.innerHTML = 'Не подключён<small>Сначала укажите API ID и API Hash ниже.</small>';
    login.style.display='none';
    wp.className='pill warn'; wp.textContent='не подключён';
  }else if(TG.authorized){
    line.innerHTML = `<span class="pill ok">✓ вход выполнен</span> &nbsp;${esc(TG.me||'')}<small>Сессия хранится в папке данных программы.</small>`;
    act.innerHTML = '<button class="btn danger" onclick="tgLogout()">Выйти из аккаунта</button>';
    login.style.display='none';
    wp.className='pill ok'; wp.textContent='подключён '+(TG.me||'');
  }else if(TG.auth_error){
    line.innerHTML = `<span class="pill warn">нет связи</span><small>${esc(TG.auth_error)}</small>`;
    act.innerHTML = '<button class="btn" onclick="loadTgStatus()">Повторить</button>';
    login.style.display='none';
    wp.className='pill warn'; wp.textContent='нет связи';
  }else{
    line.innerHTML = 'Вход не выполнен<small>Введите номер телефона аккаунта Telegram, с которого читаете каналы.</small>';
    login.style.display='';
    wp.className='pill warn'; wp.textContent='нужен вход';
  }
  const db = TG.db||{};
  $('tg-refresh-note').textContent = `В базе ${db.total||0} постов · последний ${db.last_date||'—'}` +
     (TG.last_refresh?` · обновлено ${TG.last_refresh}`:'') + (TG.last_error?` · ⚠ ${TG.last_error}`:'');
  $('tg-refresh-btn').disabled = !TG.configured;
  if(TG.refresh_task && TG.refresh_task.status==='running') followTgRefresh();
}
function tgResetLogin(){ $('st-phone').style.display=''; $('st-code').style.display='none'; $('st-pass').style.display='none'; $('tg-login-err').textContent=''; }
async function busy(btn, fn){ const t=btn.textContent; btn.disabled=true; btn.textContent='⏳'; try{ return await fn(); } finally{ btn.disabled=false; btn.textContent=t; } }
async function tgSendCode(btn){
  const phone = $('tg-phone').value.trim(); if(!phone){ $('tg-phone').focus(); return; }
  const d = await busy(btn, ()=>postJSON('/api/tg/login/code',{phone}));
  if(d.ok && d.already){ loadTgStatus(); return; }
  if(d.ok){ $('st-phone').style.display='none'; $('st-code').style.display=''; $('tg-login-err').textContent=''; $('tg-code').focus(); }
  else if(!d._denied) $('tg-login-err').textContent = d.error||'Ошибка';
}
async function tgVerify(btn){
  const code = $('tg-code').value.trim(); if(!code) return;
  const d = await busy(btn, ()=>postJSON('/api/tg/login/verify',{code}));
  if(d.ok){ toast('Telegram подключён','success'); tgResetLogin(); loadTgStatus(); }
  else if(d.need_password){ $('st-code').style.display='none'; $('st-pass').style.display=''; $('tg-login-err').textContent=''; $('tg-pass').focus(); }
  else if(!d._denied) $('tg-login-err').textContent = d.error||'Ошибка';
}
async function tgPassword(btn){
  const password = $('tg-pass').value; if(!password) return;
  const d = await busy(btn, ()=>postJSON('/api/tg/login/password',{password}));
  if(d.ok){ toast('Telegram подключён','success'); $('tg-pass').value=''; tgResetLogin(); loadTgStatus(); }
  else if(!d._denied) $('tg-login-err').textContent = d.error||'Ошибка';
}
async function tgLogout(){
  if(!confirm('Выйти из аккаунта Telegram в этой программе? Собранные посты останутся.')) return;
  const d = await postJSON('/api/tg/logout',{});
  if(d.ok){ toast('Вы вышли из Telegram','success'); loadTgStatus(); }
}
function renderChannels(){
  if(!S) return;
  const mine = S.telegram.channels||[];
  $('ch-list').innerHTML = mine.length ? mine.map(c=>`<span class="chip">@${esc(c)}<button title="Убрать" onclick="delChannel('${esc(c)}')">✕</button></span>`).join('')
    : '<span class="set-note">Пока пусто.</span>';
  fetch('/api/tg/config').then(r=>r.json()).then(cfg=>{
    const m = new Set(mine.map(c=>c.toLowerCase()));
    const db = (cfg.db_channels||[]).filter(c=>!m.has(c.toLowerCase()));
    $('ch-db-row').style.display = db.length ? '' : 'none';
    $('ch-db').innerHTML = db.map(c=>`<span class="chip db">@${esc(c)}</span>`).join('');
  }).catch(()=>{});
}
async function addChannel(){
  const v = $('ch-input').value.trim(); if(!v) return;
  const d = await postJSON('/api/tg/channels/add',{channel:v});
  if(d.error){ toast(d.error,'error'); return; }
  if(d.ok){ S.telegram.channels = d.channels; $('ch-input').value=''; renderChannels(); toast('Канал добавлен: @'+d.channel,'success'); }
}
async function delChannel(c){
  const d = await postJSON('/api/tg/channels/delete',{channel:c});
  if(d.ok){ S.telegram.channels = d.channels; renderChannels(); toast('Канал убран из списка','success',1500); }
}
let tgTimer = null;
async function tgRefresh(){
  const d = await (await fetch('/api/tg/refresh',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'})).json();
  if(!d.ok){ toast(d.error||'Не удалось','error'); return; }
  followTgRefresh();
}
function followTgRefresh(){
  const btn = $('tg-refresh-btn'); btn.disabled = true; btn.textContent='⏳ Обновление…';
  if(tgTimer) clearInterval(tgTimer);
  tgTimer = setInterval(async ()=>{
    const t = await (await fetch('/api/tg/refresh/status')).json();
    const last = (t.log||[]).slice(-1)[0] || '';
    $('tg-refresh-note').textContent = `${t.progress||0}% · ${last}`;
    if(t.status!=='running'){
      clearInterval(tgTimer); tgTimer=null; btn.disabled=false; btn.textContent='Обновить из Telegram';
      if(t.status==='done') toast('Новых постов: '+((t.result||{}).added||0),'success');
      else toast(((t.result||{}).error)||'Ошибка обновления','error',6000);
      loadTgStatus(); renderChannels();
    }
  }, 1000);
}
async function importDb(){
  let p = await Native.pickFile('db');
  if(p===null && !(await Native.available())) p = prompt('Полный путь к файлу news.db:');
  if(!p) return;
  const d = await postJSON('/api/tg/import_db',{path:p});
  if(d.ok){ toast('Добавлено постов: '+d.added,'success'); loadTgStatus(); renderChannels(); }
  else if(!d._denied) toast(d.error||'Ошибка','error',6000);
}

/* ── дедупликатор: модель ────────────────────────────────── */
let modelTimer = null;
async function loadEngine(){
  const e = await (await fetch('/api/dedup/engine')).json();
  const pill = $('model-pill'), btn = $('model-btn'), note = $('model-note');
  if(!e.available){ pill.className='pill warn'; pill.textContent='нет в этой сборке'; btn.style.display='none';
    note.textContent='Используется TF-IDF.'; return; }
  if(e.ready){ pill.className='pill ok'; pill.textContent='✓ скачана'; btn.style.display='none';
    note.textContent='Работает без интернета.'; }
  else{ pill.className='pill warn'; pill.textContent='не скачана'; btn.style.display='';
    note.textContent='Скачается сама при первой дедупликации, или нажмите «Скачать» сейчас (нужен интернет).'; }
  if(e.task && e.task.status==='running'){
    pill.className='pill'; pill.textContent='⏳ скачивание…'; btn.style.display='none';
    note.textContent = (e.task.log||[]).slice(-1)[0] || 'Скачивание…';
    if(!modelTimer) modelTimer = setInterval(loadEngine, 2000);
  }else{
    if(modelTimer){ clearInterval(modelTimer); modelTimer=null;
      if(e.task && e.task.status==='error') toast('Не удалось скачать модель: '+((e.task.log||[]).slice(-1)[0]||''),'error',7000);
      if(e.task && e.task.status==='done') toast('Модель скачана','success'); }
  }
}
async function downloadModel(){
  const d = await postJSON('/api/dedup/engine/download',{});
  if(d.ok) loadEngine();
}

/* ── данные ─────────────────────────────────────────────── */
async function loadDataInfo(){
  const d = await (await fetch('/api/data/info')).json();
  $('data-dir').textContent = d.data_dir;
  $('data-default-btn').style.display = d.data_dir===d.default_data_dir ? 'none' : '';
  const c = d.counts;
  $('data-stats').textContent = `${d.size_mb} МБ · выгрузок ${c.parser} · дедупликаций ${c.dedup} · TG-выборок ${c.tg} · недель ${c.weeks} · постов Telegram ${d.tg_db.total}`;
  $('hist-stats').textContent = `Сейчас: выгрузок ${c.parser}, дедупликаций ${c.dedup}, TG-выборок ${c.tg}. Недельная база и посты не затрагиваются.`;
}
async function loadWeeks(){
  const weeks = await (await fetch('/api/weeks')).json();
  $('weeks-list').innerHTML = weeks.length ? weeks.map(w=>`
    <div class="set-row" style="padding:8px 0">
      <div class="set-lbl"><b>${esc(w.label)}</b><small>${w.count} новостей · сайты ${w.sites} · Telegram ${w.tg}</small></div>
      <div class="set-ctl"><button class="btn" onclick="downloadUrl('/api/week/${w.key}/export?fmt=xlsx','неделю ${esc(w.label)}')">XLSX</button>
        <button class="btn" onclick="downloadUrl('/api/week/${w.key}/export?fmt=csv','неделю ${esc(w.label)}')">CSV</button>
        <button class="btn danger" onclick="delWeek('${w.key}','${esc(w.label)}')">✕</button></div>
    </div>`).join('') : '<span class="set-note">Недель пока нет. На страницах «Сайты» и «Telegram» есть кнопка «В недельную базу».</span>';
}
async function delWeek(key, label){
  if(!confirm('Удалить неделю '+label+' из недельной базы безвозвратно?')) return;
  const d = await postJSON('/api/week/'+key+'/delete',{});
  if(d.ok){ toast('Неделя '+label+' удалена','success'); loadWeeks(); loadDataInfo(); }
  else if(!d._denied) toast(d.error||'Ошибка','error');
}
async function clearWeeks(){
  if(!confirm('Полностью очистить недельную базу (все недели)? Действие необратимо.')) return;
  const d = await postJSON('/api/weeks/clear',{});
  if(d.ok){ toast('Удалено недель: '+d.deleted_weeks,'success'); loadWeeks(); loadDataInfo(); }
}
async function clearHistory(){
  if(!confirm('Очистить всю историю выгрузок, дедупликаций и TG-выборок?')) return;
  const d = await postJSON('/api/history/clear',{});
  if(d.ok){ toast('Удалено: '+d.deleted,'success'); loadDataInfo(); }
}
async function openDataDir(){
  const d = await (await fetch('/api/data/open',{method:'POST'})).json();
  if(!d.ok) toast(d.error||'Не удалось открыть папку','error');
}
async function askFolder(promptText){
  let p = await Native.pickFolder();
  if(p===null && !(await Native.available())) p = prompt(promptText);
  return p;
}
async function moveDataDir(){
  const p = await askFolder('Полный путь к новой папке для данных:');
  if(!p) return;
  if(!confirm('Скопировать данные в «'+p+'» и использовать эту папку после перезапуска?')) return;
  const d = await postJSON('/api/data/location',{path:p});
  if(d.ok) toast('Готово. Перезапустите программу — данные будут в: '+d.path,'success',9000);
  else if(!d._denied) toast(d.error||'Ошибка','error',7000);
}
async function resetDataDir(){
  if(!confirm('Вернуть стандартную папку данных? Текущая папка останется на месте (данные не копируются).')) return;
  const d = await postJSON('/api/data/location',{path:''});
  if(d.ok) toast('После перезапуска будет использоваться: '+d.path,'success',8000);
}
async function importOld(reportId){
  const p = await askFolder('Полный путь к папке «ВЕРСИЯ 2»:');
  if(!p) return;
  const rep = $(reportId); rep.textContent = '⏳ Переношу данные…';
  const d = await postJSON('/api/data/import_old',{path:p});
  if(d._denied){ rep.textContent=''; return; }
  if(d.ok){
    rep.innerHTML = d.report.map(l=>'✓ '+esc(l)).join('<br>');
    toast('Данные перенесены','success');
    const r = await fetch('/api/settings',{headers:authHeaders()}); if(r.ok){ S = await r.json(); fill(); }
    loadTgStatus();
  }else{ rep.innerHTML = '<span style="color:var(--red)">✗ '+esc(d.error||'Ошибка')+'</span>'; }
}

/* ── пароль ─────────────────────────────────────────────── */
function paintPassword(){
  const on = !!(S.security||{}).protected;
  $('pw-state').className = 'pill '+(on?'ok':'warn');
  $('pw-state').textContent = on ? 'пароль установлен' : 'без пароля';
  $('pw-remove').style.display = on ? '' : 'none';
  $('pw-lock').style.display = on ? '' : 'none';
}
async function setPassword(){
  const a = $('pw1').value, b = $('pw2').value;
  if(a.length<4){ $('pw-err').textContent='Минимум 4 символа'; return; }
  if(a!==b){ $('pw-err').textContent='Пароли не совпадают'; return; }
  const d = await postJSON('/api/settings/password',{password:a});
  if(d.ok){ Admin.token = d.token||''; S.security = {protected:true}; $('pw1').value=$('pw2').value=''; $('pw-err').textContent='';
    paintPassword(); toast('Пароль сохранён','success'); }
  else if(!d._denied) $('pw-err').textContent = d.error||'Ошибка';
}
async function removePassword(){
  if(!confirm('Убрать пароль? Настройки сможет менять любой, у кого есть доступ к компьютеру.')) return;
  const d = await postJSON('/api/settings/password',{password:''});
  if(d.ok){ Admin.token=''; S.security={protected:false}; paintPassword(); toast('Пароль убран','success'); }
}
async function lockNow(){
  if(Admin.token){ try{ await fetch('/api/admin/lock',{method:'POST',headers:{'X-Admin-Token':Admin.token}}); }catch(e){} }
  Admin.token=''; showLock();
}

/* ── промпт ──────────────────────────────────────────────── */
async function loadPrompt(){
  const d = await (await fetch('/api/export/prompt',{headers:authHeaders()})).json();
  $('ex_prompt').value = d.prompt || '';
  $('ex_prompt_state').textContent = d.is_default ? 'используется промпт по умолчанию' : 'ваш промпт';
  $('ex_prompt_state').className = 'pill ' + (d.is_default ? '' : 'ok');
}
async function savePrompt(){
  const v = $('ex_prompt').value;
  if(!v.includes('{{ПЕРИОД}}') && !confirm('В промпте нет {{ПЕРИОД}} — даты не будут подставляться автоматически. Сохранить?')) return;
  if(await save({export:{prompt: v}}, 'Промпт сохранён')) loadPrompt();
}
async function resetPrompt(){
  if(!confirm('Вернуть промпт по умолчанию? Ваши правки будут потеряны.')) return;
  if(await save({export:{prompt: ''}}, 'Возвращён промпт по умолчанию')) loadPrompt();
}
async function pickExportFolder(){
  const p = await askFolder('Полный путь к папке для выгрузок:');
  if(!p) return;
  $('ex_folder').value = p; await save({export:{folder:p}}, 'Папка выгрузок: '+p);
}

/* ── тема ───────────────────────────────────────────────── */
function applyTheme(t){
  const d = document.documentElement; d.dataset.themePref = t;
  d.dataset.theme = t === 'system' ? (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light') : t;
}
function bindTheme(){
  const seg = $('gen_theme'), cur = (S.general && S.general.theme) || 'light';
  seg.querySelectorAll('button').forEach(b => {
    b.classList.toggle('on', b.dataset.v === cur);
    b.onclick = async () => {
      seg.querySelectorAll('button').forEach(x => x.classList.toggle('on', x === b));
      applyTheme(b.dataset.v);
      await save({general:{theme:b.dataset.v}}, 'Тема сохранена');
    };
  });
}

/* ── подбор порога дедупликации ───────────────────────────── */
let CAL = null;
const CAL_KIND = k => k === 'telegram' ? 'TG' : 'Сайт';
function calCard(n){
  return `<div class="cal-meta"><span class="ex-kind ${n.kind}">${CAL_KIND(n.kind)}</span> ${esc(n.source)} · ${esc(n.published)}</div>
    <div class="cal-title">${n.url ? `<a href="#" onclick="openExternal('${esc(n.url)}');return false">${esc(n.title)}</a>` : esc(n.title)}</div>
    <div class="cal-text">${esc(n.text)}${n.text.length >= 420 ? '…' : ''}</div>`;
}
async function calStart(){
  const btn = $('cal_start'); btn.disabled = true; btn.textContent = 'Ищу пары…';
  $('cal_res').style.display = 'none';
  let d; try{ d = await (await fetch('/api/calibrate/pairs?n=20')).json(); }catch(e){ d = {ok:false, error:'нет ответа'}; }
  btn.disabled = false; btn.textContent = 'Начать подбор';
  if(!d.ok){ toast(d.error, 'warn', 5000); return; }
  if(!d.pairs.length){ calShow(d.summary); toast('Новых пар «на грани» нет — ответов уже достаточно или новостей мало', 'warn', 5000); return; }
  CAL = {pairs: d.pairs, i: 0, backend: d.backend, summary: d.summary};
  $('cal').style.display = ''; $('cal_note').textContent = `движок: ${d.backend === 'tfidf' ? 'TF-IDF' : 'нейросеть'} · ответов раньше: ${d.summary.labels}`;
  calPaint();
}
function calPaint(){
  const p = CAL.pairs[CAL.i];
  $('cal_prog').textContent = `Пара ${CAL.i + 1} из ${CAL.pairs.length}`;
  $('cal_bar').style.width = (CAL.i / CAL.pairs.length * 100) + '%';
  $('cal_a').innerHTML = calCard(p.a); $('cal_b').innerHTML = calCard(p.b);
}
async function calAnswer(same){
  if(!CAL) return;
  const p = CAL.pairs[CAL.i];
  if(same !== null){
    const r = await postJSON('/api/calibrate/label', {a:p.a.id, b:p.b.id, same, similarity:p.similarity, backend:CAL.backend});
    if(r.ok) CAL.summary = r;
  }
  CAL.i++;
  if(CAL.i >= CAL.pairs.length) return calFinish();
  calPaint();
}
function calFinish(){
  if(!CAL) return;
  $('cal').style.display = 'none';
  calShow(CAL.summary); CAL = null;
}
function calShow(r){
  const box = $('cal_res'); box.style.display = '';
  const cur = r.current, best = r.best;
  if(!best){
    box.innerHTML = `<b>Ответов: ${r.labels}.</b> Нужно ещё ${r.need || 'несколько'} (и хотя бы по одному «одно событие» и «разные»), чтобы рассчитать порог.`;
    return;
  }
  const same = Math.abs(best.threshold - cur.threshold) < 0.005;
  box.innerHTML = `<div class="cal-nums">
      <div><span>Сейчас</span><b>${cur.threshold.toFixed(2)}</b><small>ошибочно объединит: ${cur.false_merges} · пропустит повторов: ${cur.missed}</small></div>
      <div class="best"><span>Рекомендуем</span><b>${best.threshold.toFixed(2)}</b><small>ошибочно объединит: ${best.false_merges} · пропустит: ${best.missed} · точность ${Math.round(best.accuracy * 100)}%</small></div>
    </div>
    <div class="step-row">${same ? '<span class="pill ok">текущий порог уже оптимален</span>'
      : `<button class="btn primary" onclick="calApply(${best.threshold})">Применить ${best.threshold.toFixed(2)}</button>`}
      <span class="set-note">по ${r.labels} ответам (одно событие: ${r.same})</span>
      <button class="btn" style="margin-left:auto" onclick="calReset()">Сбросить ответы</button></div>`;
}
async function calApply(t){
  const r = await postJSON('/api/calibrate/apply', {threshold:t});
  if(!r.ok) return toast(r.error || 'Не получилось', 'error');
  S.dedup.threshold = r.threshold; $('dd_threshold').value = r.threshold; $('dd_thr_val').textContent = r.threshold.toFixed(2);
  toast(`Порог ${r.threshold.toFixed(2)} применён`, 'success');
  $('cal_res').style.display = 'none';
}
async function calReset(){
  if(!confirm('Удалить все ответы подбора порога?')) return;
  await postJSON('/api/calibrate/reset', {});
  $('cal_res').style.display = 'none'; toast('Ответы сброшены', 'success');
}
document.addEventListener('keydown', e => {
  if(!CAL || /input|textarea|select/i.test((e.target.tagName || ''))) return;
  if(e.key === '1') calAnswer(true); else if(e.key === '2') calAnswer(false); else if(e.key === '3') calAnswer(null);
});

/* ── утренняя выгрузка ───────────────────────────────────── */
const fmtMsk = iso => iso ? new Date(iso).toLocaleString('ru-RU', {timeZone:'Europe/Moscow', day:'2-digit', month:'2-digit', hour:'2-digit', minute:'2-digit'}) : '—';
async function loadMorning(){
  try{
    const d = await (await fetch('/api/morning/status')).json();
    const sch = d.schedule || {}, last = d.last;
    let t = sch.enabled ? `следующая: ${fmtMsk(sch.next_run_at)} МСК` : 'выключено';
    if(last) t += ` · последняя: ${fmtMsk(last.at)} — ${last.error ? last.error : (last.rows + ' строк')}`;
    $('mo_state').textContent = t;
  }catch(e){}
}
async function morningRun(){
  const r = await postJSON('/api/morning/run', {});
  if(!r.ok){ toast(r.error || 'Не получилось', 'error'); return; }
  const btn = $('mo_run'); btn.disabled = true; btn.textContent = 'Собираю и готовлю…';
  const t = setInterval(async ()=>{
    const j = await (await fetch('/api/jobs/' + r.job_id)).json();
    if(j.status !== 'queued' && j.status !== 'running'){
      clearInterval(t); btn.disabled = false; btn.textContent = 'Запустить'; loadMorning();
      const res = j.result || {};
      if(j.status === 'done' && !res.error) toast(`Выгрузка готова: ${res.rows} строк — откройте экран «Выгрузка»`, 'success', 6000);
      else toast(res.error || j.error || 'Ошибка', 'warn', 6000);
    }
  }, 2500);
}

/* ── полный текст статей ───────────────────────────────── */
async function loadFulltext(){
  try{
    const d = await (await fetch('/api/fulltext/stats')).json();
    $('ft_stats').textContent = d.total
      ? `новостей с сайтов: ${d.total} · коротких: ${d.short} · полный текст взят: ${d.ok}` +
        (d.failed ? ` · страница не открылась: ${d.failed}` : '') + (d.pending ? ` · ждут: ${d.pending}` : '')
      : 'новостей с сайтов пока нет';
  }catch(e){}
}
async function fulltextBackfill(){
  const r = await postJSON('/api/fulltext/backfill', {days: 7});
  if(!r.ok){ toast(r.error || 'Не получилось', 'error'); return; }
  const btn = $('ft_btn'); btn.disabled = true; btn.textContent = 'Дотягиваю…';
  const t = setInterval(async ()=>{
    const j = await (await fetch('/api/jobs/' + r.job_id)).json();
    loadFulltext();
    if(j.status !== 'queued' && j.status !== 'running'){
      clearInterval(t); btn.disabled = false; btn.textContent = 'Дотянуть полные тексты';
      toast(j.status === 'done' ? `Полный текст взят для ${(j.result || {}).ok || 0} статей` : (j.error || 'Ошибка'),
            j.status === 'done' ? 'success' : 'error', 5000);
    }
  }, 2000);
}

/* ── обновления и восстановление ──────────────────────────── */
async function checkUpdate(force){
  const st = $('up_state'), btn = $('up_install');
  st.textContent = 'проверяю…'; btn.style.display = 'none';
  let d; try{ d = await (await fetch('/api/update/check' + (force ? '?force=1' : ''))).json(); }catch(e){ st.textContent = 'не удалось проверить'; return; }
  if(!d.configured){ st.textContent = `установлена ${d.current} · укажите репозиторий, чтобы проверять обновления`; return; }
  if(!d.ok){ st.textContent = `установлена ${d.current} · ${d.error}`; return; }
  if(d.available){
    st.innerHTML = `установлена ${esc(d.current)} · <b style="color:var(--green)">доступна ${esc(d.latest)}</b>` +
      (d.url ? ` · <a href="#" onclick="openExternal('${esc(d.url)}');return false">что нового</a>` : '');
    if(d.asset) btn.style.display = '';
    else st.innerHTML += ' · установщика для этой системы в релизе нет';
  } else st.textContent = `установлена ${d.current} — это последняя версия`;
}
async function installUpdate(){
  if(!confirm('Скачать и запустить установщик новой версии? На Windows программа закроется, данные сохранятся.')) return;
  const r = await postJSON('/api/update/install', {});
  if(!r.ok){ toast(r.error || 'Не получилось', 'error'); return; }
  const btn = $('up_install'); btn.disabled = true;
  const t = setInterval(async ()=>{
    const s = await (await fetch('/api/update/status')).json();
    if(s.status === 'running') btn.textContent = `Скачиваю… ${Math.round((s.progress || 0) * 100)}%`;
    else{
      clearInterval(t); btn.disabled = false; btn.textContent = 'Скачать и установить';
      if(s.status === 'done') toast('Установщик запущен — следуйте его шагам' + (navigator.platform.startsWith('Mac') ? ': перетащите программу в «Программы»' : ''), 'success', 6000);
      else toast('Обновление: ' + (s.error || 'ошибка'), 'error', 6000);
    }
  }, 700);
}
async function restoreBackup(input){
  const f = input.files[0]; input.value = '';
  if(!f) return;
  if(!confirm(`Восстановить данные из «${f.name}»? Текущие данные будут отложены в отдельную папку.`)) return;
  const fd = new FormData(); fd.append('file', f);
  const r = await (await fetch('/api/data/restore', {method:'POST', body:fd, headers:authHeaders()})).json();
  if(!r.ok){ toast(r.error || 'Не получилось', 'error'); return; }
  $('restore-note').innerHTML = `Копия${r.created ? ' от ' + esc(r.created.replace('T', ' ')) : ''} принята и применится при перезапуске.`;
  if(confirm('Перезапустить программу сейчас?')) await fetch('/api/app/restart', {method:'POST'});
}

/* ── фильтр мусора ───────────────────────────────────────── */
async function loadWords(){
  const d = await (await fetch('/api/filter/config')).json();
  for(const k of ['stop','topic']){
    $('fl_'+k).value = d[k];
    $('fl_'+k+'_state').textContent = d[k+'_default'] ? 'список по умолчанию' : 'ваш список';
    $('fl_'+k+'_state').className = 'pill ' + (d[k+'_default'] ? '' : 'ok');
  }
}
async function saveWords(k){
  if(await save({filter:{[k]: $('fl_'+k).value}}, 'Список сохранён')){ loadWords(); if(k==='topic') loadFilterSources(); }
}
async function resetWords(k){
  if(!confirm('Вернуть список по умолчанию? Ваши правки будут потеряны.')) return;
  if(await save({filter:{[k]: ''}}, 'Возвращён список по умолчанию')){ loadWords(); if(k==='topic') loadFilterSources(); }
}
let FL_SRC = [];
async function loadFilterSources(){
  const d = await (await fetch('/api/filter/sources')).json();
  FL_SRC = (d.sources || []).filter(s => s.total || s.space_only);
  const rec = FL_SRC.filter(s => s.recommended && !s.space_only);
  $('fl_rec_btn').disabled = !rec.length;
  $('fl_src_note').textContent = rec.length ? `рекомендовано: ${rec.length}` : 'рекомендаций нет';
  $('fl_sources').innerHTML = FL_SRC.map(s => `<tr title="${esc(s.examples.join(' · '))}">
    <td style="width:46px"><label class="switch"><input type="checkbox" ${s.space_only?'checked':''} onchange="setSpaceOnly(${s.id}, this.checked)"><span class="slider"></span></label></td>
    <td><span class="ex-kind ${s.kind}">${s.kind==='telegram'?'TG':'Сайт'}</span> ${esc(s.name)}
      ${s.recommended && !s.space_only ? '<span class="pill warn" style="margin-left:6px">рекомендуем</span>' : ''}</td>
    <td class="ex-time" style="text-align:right;width:120px">${Math.round(s.share*100)}% не про космос</td>
    <td class="ex-time" style="text-align:right;width:90px">${s.total} за 30 дн.</td></tr>`).join('')
    || '<tr><td class="set-note" style="padding:14px">Новостей за 30 дней пока нет.</td></tr>';
}
async function setSpaceOnly(id, on){
  const d = await postJSON('/api/filter/source', {ids:[id], space_only:on});
  if(d.ok) toast(on ? '«Только про космос» включено' : '«Только про космос» выключено', 'success', 1400);
  loadFilterSources();
}
async function enableRecommended(){
  const ids = FL_SRC.filter(s => s.recommended && !s.space_only).map(s => s.id);
  if(!ids.length) return;
  const d = await postJSON('/api/filter/source', {ids, space_only:true});
  if(d.ok) toast(`«Только про космос» включено для ${ids.length} источников`, 'success');
  loadFilterSources();
}

/* ── о программе / выход / приветствие ──────────────────── */
async function loadAbout(){
  const i = await (await fetch('/api/app/info')).json();
  $('ab-name').textContent = i.name; $('ab-ver').textContent = 'версия '+i.version;
  $('ab-log').textContent = i.data_dir + (i.platform==='win32'?'\\logs\\app.log':'/logs/app.log');
  $('quit-row').style.display = (await Native.available()) ? 'none' : '';
}
async function quitApp(){
  if(!confirm('Закрыть программу?')) return;
  await fetch('/api/app/quit',{method:'POST'});
  document.body.innerHTML = '<div style="padding:80px;text-align:center;color:#94a3b8;font-family:sans-serif">Программа закрыта. Эту вкладку можно закрыть.</div>';
}
async function finishWelcome(){
  await save({general:{first_run_done:true}}, 'Готово!');
  location.href = S.general.start_page || '/';
}
function togglePw(id, btn){ const el=$(id); el.type = el.type==='password' ? 'text' : 'password'; btn.textContent = el.type==='password'?'👁':'🙈'; }
async function openExternal(url){
  if(await Native.available()) window.pywebview.api.open_external(url); else window.open(url,'_blank');
}

load();


/* ── дайджест СЛК ──────────────────────────────────────── */
async function loadSlk(){ loadSlkWords(); loadSlkPrompt(); loadSlkSources(); }
async function loadSlkWords(){
  const d = await (await fetch('/api/slk/config')).json();
  for(const k of ['names','rocket','military']){
    $('slk_'+k).value = d[k];
    $('slk_'+k+'_state').textContent = d[k+'_default'] ? 'список по умолчанию' : 'ваш список';
    $('slk_'+k+'_state').className = 'pill ' + (d[k+'_default'] ? '' : 'ok');
  }
}
async function saveSlkWords(k){ if(await save({slk:{[k]: $('slk_'+k).value}}, 'Список сохранён')) loadSlkWords(); }
async function resetSlkWords(k){
  if(!confirm('Вернуть список по умолчанию? Ваши правки будут потеряны.')) return;
  if(await save({slk:{[k]: ''}}, 'Возвращён список по умолчанию')) loadSlkWords();
}
async function loadSlkPrompt(){
  const d = await (await fetch('/api/export/prompt?profile=slk',{headers:authHeaders()})).json();
  $('slk_prompt').value = d.prompt || '';
  $('slk_prompt_state').textContent = d.is_default ? 'встроенный промпт' : 'ваш промпт';
  $('slk_prompt_state').className = 'pill ' + (d.is_default ? '' : 'ok');
}
async function saveSlkPrompt(){
  const v = $('slk_prompt').value;
  if(!v.includes('{{ПЕРИОД}}') && !confirm('В промпте нет {{ПЕРИОД}} — даты не будут подставляться автоматически. Сохранить?')) return;
  if(await save({slk:{prompt: v}}, 'Промпт СЛК сохранён')) loadSlkPrompt();
}
async function resetSlkPrompt(){
  if(!confirm('Вернуть встроенный промпт СЛК? Ваши правки будут потеряны.')) return;
  if(await save({slk:{prompt: ''}}, 'Возвращён встроенный промпт')) loadSlkPrompt();
}
async function pickSlkFolder(){
  const p = await askFolder('Полный путь к папке для выгрузок СЛК:');
  if(!p) return;
  $('slk_folder').value = p; await save({slk:{folder:p}}, 'Папка выгрузок СЛК: '+p);
}
async function loadSlkSources(){
  let d; try{ d = await (await fetch('/api/slk/sources')).json(); }catch(e){ return; }
  if(!d.ok){ $('slk_sources').innerHTML = `<tr><td class="set-note" style="padding:14px">${esc(d.error||'')}</td></tr>`; return; }
  const list = d.sources;
  const on = list.filter(s => s.enabled), bad = on.filter(s => s.problem || s.error);
  $('slk_src_note').textContent = `включено ${on.length} из ${list.length}` + (bad.length ? ` · с ошибками ${bad.length}` : '');
  const tag = s => s.kind === 'telegram' ? 'TG' : s.html ? 'страница' : 'RSS';
  $('slk_sources').innerHTML = list.map(s => {
    const state = s.error ? `<span class="rv-reason" title="${esc(s.error)}">${esc(s.error.slice(0, 120))}</span>`
      : s.last_ok ? `<span class="set-note">собрано ${esc(s.last_ok)} · за 30 дн. ${s.n30}${
          s.page_dated ? ` · дата со страницы статьи: ${s.page_dated}` : ''}${
          s.undated ? ` · <span style="color:var(--amber)">без даты: ${s.undated}</span>` : ''}${
          s.archive ? ` · архив сайта (не выгружается): ${s.archive}` : ''}</span>`
      : '<span class="set-note">ещё не собирался</span>';
    return `<tr><td style="width:46px"><label class="switch"><input type="checkbox" ${s.enabled ? 'checked' : ''}
        onchange="slkToggle(${s.id}, this.checked)"><span class="slider"></span></label></td>
      <td><b>${esc(s.name)}</b> <span class="ex-kind">${tag(s)}</span>${s.trusted ? ' <span class="rv-badge info" title="Сайт компании из перечня: без предфильтра">перечень ТЗ</span>' : ''}${
        s.general ? ' <span class="rv-badge" title="Издание общего профиля: нужно и космическое, и ракетное слово">общий профиль</span>' : ''}
        <div class="set-note mono" style="font-size:11px">${esc(s.url)}</div>${state}</td></tr>`;
  }).join('') || '<tr><td class="set-note" style="padding:14px">Источников СЛК нет.</td></tr>';
}
async function slkToggle(id, on){
  const d = await postJSON('/api/slk/source', {id, enabled: on});
  if(!d.ok && !d._denied) toast(d.error || 'Не получилось', 'error');
  loadSlkSources();
}
async function slkCollect(){
  const btn = $('slk_collect_btn');
  const r = await postJSON('/api/slk/collect', {});
  if(!r.ok || !r.jobs){ toast(r.error || 'Нет включённых источников СЛК', 'warn'); return; }
  btn.disabled = true; btn.textContent = 'Сбор…';
  const t = setInterval(async () => {
    const st = await (await fetch('/api/collect/now/status')).json();
    btn.textContent = `Сбор… ${st.progress || 0}%`;
    if(st.status !== 'running'){
      clearInterval(t); btn.disabled = false; btn.textContent = 'Собрать источники СЛК';
      toast('Сбор источников СЛК завершён', 'success'); loadSlkSources();
    }
  }, 1500);
}
async function slkImport(pick){
  let path = '';
  if(pick){ path = await askFolder('Папка старого «Парсера СЛК» (Windows: %APPDATA%\\SLK Parser):'); if(!path) return; }
  const r = await postJSON('/api/slk/import', {path});
  if(r._denied) return;
  if(!r.ok){ $('slk_import_note').innerHTML = `<span style="color:var(--amber)">${esc(r.error || 'Не получилось')}</span>`; return; }
  $('slk_import_note').innerHTML = `Из <span class="mono">${esc(r.folder)}</span>: добавлено источников ${r.added}` +
    (r.exists ? `, уже были ${r.exists}` : '') + (r.urls_fixed ? `, исправлено адресов ${r.urls_fixed}` : '') +
    (r.skipped.length ? `, пропущено ${r.skipped.length}` : '') +
    (r.notes.length ? '<br>' + r.notes.map(esc).join('<br>') : '');
  toast('Перенос из парсера СЛК выполнен', 'success'); loadSlkSources();
}
