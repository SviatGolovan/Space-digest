/* ============================================================
   export.js — экран «Выгрузка»: всё новое → CSV + промпт → ChatGPT → DOCX
   ============================================================ */
const $ = id => document.getElementById(id);
const esc = escHtml;
const PROFILE = window.PROFILE || 'space';          // space — общий дайджест, slk — РН сверхлёгкого класса
const SLK = PROFILE === 'slk';
let MODE = SLK ? 'window' : 'since_last';
let CURRENT = null;          // последняя подготовленная выгрузка {id, prompt, ...}

function params(){
  const kinds = [];
  if($('k-rss').checked) kinds.push('rss');
  if($('k-tg').checked) kinds.push('telegram');
  return {mode: MODE, date_from: $('date-from').value, date_to: $('date-to').value,
          kinds, dedupe: $('dedupe').checked, profile: PROFILE};
}
async function postJ(url, body){
  const r = await fetch(url, {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body||{})});
  return r.json();
}
const fmtDT = iso => iso ? new Date(iso).toLocaleString('ru-RU',{day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'}) : '—';
const fmtPeriod = (a,b) => !a ? '—' : (a===b ? a.split('-').reverse().join('.') :
  a.split('-').reverse().slice(0,2).join('.') + ' – ' + b.split('-').reverse().join('.'));

/* ── режим ─────────────────────────────────────────────── */
document.querySelectorAll('#mode button').forEach(b => b.onclick = () => {
  MODE = b.dataset.v;
  document.querySelectorAll('#mode button').forEach(x => x.classList.toggle('on', x === b));
  $('dates-row').style.display = MODE === 'dates' ? '' : 'none';
  loadPreview();
});
['k-rss','k-tg','date-from','date-to'].forEach(id => $(id).addEventListener('change', loadPreview));

/* ── предпросмотр ──────────────────────────────────────── */
async function loadPreview(){
  const d = await postJ('/api/export/preview', params());
  if(!d.ok){ $('mode-hint').innerHTML = '<span style="color:var(--amber)">'+esc(d.error||'')+'</span>'; return; }
  $('st-total').textContent = d.total - (d.filtered || 0);
  $('st-rss').textContent = d.by_kind.rss; $('st-tg').textContent = d.by_kind.telegram;
  const word = SLK ? ' за период' : ' новых';
  $('cnt-rss').textContent = d.by_kind.rss + word; $('cnt-tg').textContent = d.by_kind.telegram + word;
  $('st-period').textContent = fmtPeriod(d.period_from, d.period_to);
  if(d.window){
    const w = d.window, nf = new Date(w.new_from); nf.setDate(nf.getDate() - 1);
    $('st-period').textContent = fmtPeriod(w.date_from, w.date_to);
    $('mode-hint').innerHTML = `Новые дни: <b>${fmtPeriod(w.new_from, w.date_to)}</b> (${w.period_days} дн.)` +
      (w.overlap_days ? ` + перекрытие с прошлым поиском <b>${fmtPeriod(w.date_from, nf.toISOString().slice(0,10))}</b> (${w.overlap_days} дн.). ` +
        'Что уже было в прошлом дайджесте, придёт с отметкой.' : '.');
    $('mode-window').textContent = `${w.period_days} + ${w.overlap_days} дн.`;
  } else if(d.mode === 'since_last'){
    $('mode-hint').innerHTML = d.fallback
      ? 'Выгрузок ещё не было — берём новости за вчера и сегодня.'
      : 'Всё, что собрано после выгрузки <b>' + fmtDT(d.since) + '</b>. Ничего не пропадёт и не повторится.';
  } else {
    $('mode-hint').textContent = 'Новости, опубликованные в выбранные даты (включительно).';
  }
  $('btn-prepare').disabled = !d.total;
  $('list-note').textContent = [d.filtered ? `${SLK ? 'предфильтр' : 'фильтр мусора'} отсеет ${d.filtered}` : '',
    d.undated ? `без даты на сайте: ${d.undated} — ChatGPT проверит дату поиском` : '',
    d.total > d.sample.length ? `показаны первые ${d.sample.length} из ${d.total}` : ''].filter(Boolean).join(' · ');
  $('preview-body').innerHTML = d.sample.length ? d.sample.map(n => `
    <tr${n.filtered ? ' class="pv-off"' : ''}><td class="ex-time">${esc(n.published)}</td>
      <td class="ex-src"><span class="ex-kind ${n.kind}">${n.kind==='telegram'?'TG':'Сайт'}</span> ${esc(n.source)}</td>
      <td>${n.url ? `<a href="${esc(n.url)}" target="_blank" class="ex-title">${esc(n.title)}</a>` : esc(n.title)}${
        n.undated ? '<span class="rv-badge warn" title="У новости на сайте нет даты. Показан день, когда программа её впервые увидела">дата не подтверждена</span>' : ''}${
        n.filtered ? `<span class="rv-reason">отсеется: ${esc(n.filtered)}</span>` : ''}</td></tr>`).join('')
    : `<tr><td><div class="empty"><div class="empty-icon">📭</div><div class="empty-title">Новых новостей нет</div>
       <div class="empty-sub">Нажмите «Собрать сейчас» или выберите режим «За даты».</div></div></td></tr>`;
}

/* ── сбор ──────────────────────────────────────────────── */
async function loadCollect(){
  let d; try{ d = await (await fetch('/api/collect/status')).json(); }catch(e){ return; }
  const line = (label, k, extra) => {
    const x = d[k];
    const prob = x.problems.length ? ` · <span style="color:var(--amber)" title="${esc(x.problems.join(', '))}">проблемных: ${x.problems.length}</span>` : '';
    return `<div class="ex-c-row"><b>${label}</b><span>${x.auto ? 'авто' : 'вручную'} · за сутки +${x.new_24h} · последний ${x.last_ok || '—'}${prob}${extra||''}</span></div>`;
  };
  $('collect-status').innerHTML = line('Сайты', 'rss') +
    line('Telegram', 'telegram', d.telegram_configured ? '' : ' · <a href="/settings#telegram">не подключён</a>') +
    (d.active_jobs ? `<div class="set-note">⏳ идёт сбор: задач ${d.active_jobs}</div>` : '');
}
let collectTimer = null;
async function collectNow(){
  const btn = $('btn-collect');
  const r = await postJ('/api/collect/now', {kinds: params().kinds});
  if(!r.ok || !r.jobs){ toast(r.error || 'Нет включённых источников', 'warn'); return; }
  btn.disabled = true; btn.textContent = '⏳ Сбор…';
  clearInterval(collectTimer);
  collectTimer = setInterval(async () => {
    const s = await (await fetch('/api/collect/now/status')).json();
    btn.textContent = `⏳ Сбор… ${s.progress||0}%`;
    if(s.status !== 'running'){
      clearInterval(collectTimer); btn.disabled = false; btn.textContent = 'Собрать сейчас';
      toast('Сбор завершён: новых ' + ((s.result||{}).added||0), 'success');
      loadCollect(); loadPreview();
    }
  }, 1500);
}

/* ── подготовка ────────────────────────────────────────── */
async function prepare(){
  const btn = $('btn-prepare');
  const label = btn.__label || (btn.__label = btn.innerHTML);
  btn.disabled = true; btn.textContent = 'Готовлю…';
  $('steps').style.display = ''; $('steps-body').style.display = 'none';
  $('steps-title').textContent = 'Готовлю выгрузку…'; $('steps-sub').textContent = ''; $('steps-pill').textContent = '';
  const log = $('prep-log'); log.style.display = ''; log.textContent = '';
  const r = await postJ('/api/export/prepare', params());
  if(!r.ok){ toast(r.error || 'Ошибка', 'error'); btn.disabled = false; btn.innerHTML = label; return; }
  const poll = setInterval(async () => {
    const j = await (await fetch('/api/jobs/' + r.job_id)).json();
    log.innerHTML = (j.log || '').split('\n').filter(Boolean).map(esc).join('<br>');
    if(j.status === 'done' || j.status === 'failed' || j.status === 'cancelled'){
      clearInterval(poll); btn.disabled = false; btn.innerHTML = label;
      if(j.status !== 'done'){
        $('steps-title').textContent = 'Не получилось'; log.innerHTML += '<br><span style="color:var(--red)">' + esc(j.error||'') + '</span>';
        return;
      }
      await showExport(j.result.export_id, true);
      loadPreview(); loadHistory();
    }
  }, 700);
}

async function showExport(id, fresh){
  CURRENT = await (await fetch('/api/export/' + id)).json();
  const e = CURRENT;
  $('steps').style.display = ''; $('steps-body').style.display = '';
  $('prep-log').style.display = fresh ? '' : 'none';
  paintHeader();
  $('s2-file').textContent = e.csv_name;
  paintResult();
  RV_OPEN.clear(); RV_TAB = 'rows'; setTab();
  loadReview();
  if(fresh) watchDocx(); else stopWatch();
  if(fresh){
    const ok = await copyText(e.prompt);
    $('s1-note').textContent = ok ? 'Вставьте его в ChatGPT: Ctrl+V (на Mac ⌘V).'
                                  : 'Не удалось скопировать автоматически — нажмите «Скопировать снова».';
    toast(ok ? 'Промпт скопирован в буфер обмена' : 'Скопируйте промпт кнопкой', ok ? 'success' : 'warn');
  }
  $('steps').scrollIntoView({behavior:'smooth', block:'nearest'});
}
function paintHeader(){
  const e = CURRENT;
  $('steps-title').textContent = `Выгрузка готова: ${e.items_exported} ${plural(e.items_exported, 'строка', 'строки', 'строк')} в CSV`;
  $('steps-sub').textContent = `период ${fmtPeriod(e.period_from, e.period_to)} · ${e.folder}`;
}
function paintResult(){
  const e = CURRENT; if(!e) return;
  const pill = $('steps-pill');
  if(e.status === 'done' && e.result_exists){
    pill.className = 'pill ok'; pill.textContent = '✓ DOCX получен';
    $('s4-note').innerHTML = `Готово: <span class="mono">${esc(e.result_name)}</span> лежит в папке выгрузки.`;
    $('btn-docx').textContent = 'Открыть DOCX'; $('btn-docx').onclick = () => openExport('result');
  } else {
    pill.className = 'pill warn'; pill.textContent = 'ждём DOCX';
    $('s4-note').textContent = WATCH ? 'Слежу за «Загрузками»: как только DOCX появится, он сам попадёт в папку выгрузки.' : 'Как только файл появится в «Загрузках», он будет сохранён в папку выгрузки. Кнопка — если хотите сразу.';
    $('btn-docx').textContent = 'Забрать DOCX'; $('btn-docx').onclick = collectDocx;
  }
}

/* ── проверка выгрузки ─────────────────────────────────── */
let REVIEW = null, RV_TAB = 'rows';
const RV_OPEN = new Set();
function plural(n, one, few, many){
  const a = Math.abs(n) % 100, b = a % 10;
  return (a > 10 && a < 20) ? many : b === 1 ? one : (b >= 2 && b <= 4) ? few : many;
}
const pct = s => s == null ? '' : Math.round(s * 100) + '%';
const kindTag = k => `<span class="ex-kind ${k}">${k === 'telegram' ? 'TG' : 'Сайт'}</span>`;
const titleLink = n => n.url ? `<a href="${esc(n.url)}" target="_blank" class="ex-title">${esc(n.title)}</a>` : esc(n.title);
const actBtn = (id, action, label) => `<button class="btn" onclick="rvAction(${id}, '${action}')">${label}</button>`;
const RV_NOTES = {
  rows: 'Правки сразу сохраняются в CSV — делайте их до отправки файла в ChatGPT.',
  multi: 'Одно событие из нескольких источников — одна строка: полный текст основной версии + новые факты остальных.',
  known: 'Эти события уже были в прошлых выгрузках. Если появились новые подробности — верните новость в CSV.',
  excluded: 'Убранные строки не попадут в CSV и не считаются «уже выгруженными».',
  filtered: 'Отсеяно фильтром мусора (Настройки → Фильтр мусора). Ошибся — верните новость в CSV.',
};
if(SLK){
  RV_NOTES.rows = 'Правки сразу сохраняются в CSV. «Было в дайджесте» и «дата не подтверждена» ChatGPT разберёт по промпту.';
  RV_NOTES.filtered = 'Отсеяно предфильтром СЛК (Настройки → СЛК) или фильтром мусора. Ошибся — верните новость в CSV.';
}
function setTab(){
  document.querySelectorAll('#rv-tabs button').forEach(x => x.classList.toggle('on', x.dataset.v === RV_TAB));
}
document.querySelectorAll('#rv-tabs button').forEach(b => b.onclick = () => { RV_TAB = b.dataset.v; setTab(); paintReview(); });

async function loadReview(){
  if(!CURRENT) return;
  const d = await (await fetch(`/api/export/${CURRENT.id}/review`)).json();
  if(!d.ok){ $('review').style.display = 'none'; return; }
  REVIEW = d; $('review').style.display = ''; paintReview(); loadSuggest();
}

/* ── подсказки фильтра: из статистики источников и из того, что вы убирали ── */
const SG_KEY = 'sd.filter.dismissed';
function sgDismissed(){ try{ return JSON.parse(localStorage.getItem(SG_KEY) || '[]'); }catch(e){ return []; } }
function sgDismiss(key){
  try{ localStorage.setItem(SG_KEY, JSON.stringify([...new Set([...sgDismissed(), key])])); }catch(e){}
  loadSuggest();
}
let SUGG = null;
async function loadSuggest(){
  if(!CURRENT || SLK) return;
  let d; try{ d = await (await fetch('/api/filter/suggest?export_id=' + CURRENT.id)).json(); }catch(e){ return; }
  if(!d.ok) return;
  const off = new Set(sgDismissed());
  SUGG = {sources: d.sources.filter(s => !off.has('src:' + s.id)), stop: d.stop.filter(w => !off.has('w:' + w.word))};
  const chips = [
    ...SUGG.sources.map(s => `<span class="sg-chip"><button onclick="sgSource([${s.id}])" title="${esc(s.examples.join(' · '))}">только про космос: ${esc(s.name)}<small>${Math.round(s.share * 100)}% не про космос</small></button><button class="x" title="Не предлагать" onclick="sgDismiss('src:${s.id}')">×</button></span>`),
    ...SUGG.stop.map(w => `<span class="sg-chip"><button onclick="sgStop('${esc(w.word)}')" title="${esc(w.examples.join(' · '))}">стоп-слово «${esc(w.word)}»<small>в убранном ×${w.count}</small></button><button class="x" title="Не предлагать" onclick="sgDismiss('w:${esc(w.word)}')">×</button></span>`),
  ];
  if(SUGG.sources.length > 1) chips.push(`<button class="btn" onclick="sgSource([${SUGG.sources.map(s => s.id).join(',')}])">Включить для всех источников</button>`);
  $('rv-sugg').style.display = chips.length ? '' : 'none';
  $('rv-sugg').innerHTML = chips.length ? '<b>Фильтр мусора предлагает:</b>' + chips.join('') : '';
}
function applyFilterReply(r, what){
  if(!r.ok){ toast(r.error || 'Не получилось', 'warn'); return; }
  if(r.review){ REVIEW = r.review; CURRENT = {...CURRENT, ...r.export}; paintHeader(); paintReview(); loadHistory(); }
  toast(what + (r.refiltered ? ` · из этой выгрузки отсеяно ${r.refiltered}, CSV обновлён` : ''), 'success');
  if(r.warning) toast(r.warning, 'warn');
  loadSuggest(); loadPreview();
}
async function sgSource(ids){
  const r = await postJ('/api/filter/source', {ids, space_only: true, export_id: CURRENT && CURRENT.id});
  applyFilterReply(r, ids.length > 1 ? `«Только про космос» включено для ${ids.length} источников` : '«Только про космос» включено');
}
async function sgStop(word){
  const r = await postJ('/api/filter/stop', {word, export_id: CURRENT && CURRENT.id});
  applyFilterReply(r, `Стоп-слово «${word}» добавлено`);
}
function storyRows(s, open){
  const more = s.others.length ? `<span class="rv-more" onclick="rvToggle(${s.id})">${open ? '▾' : '▸'} ещё ${s.others.length} ${plural(s.others.length, 'источник', 'источника', 'источников')}</span>` : '';
  let html = `<tr${s.off ? ' class="rv-off"' : ''}><td class="rv-n">${s.n || ''}</td><td class="ex-time">${esc(s.published)}</td>
    <td class="ex-src">${kindTag(s.kind)} ${esc(s.source)}</td><td>${titleLink(s)}${badges(s)}${more}</td>
    <td class="rv-act">${s.off ? actBtn(s.id, 'include', 'Вернуть') : actBtn(s.id, 'exclude', 'Убрать')}</td></tr>`;
  if(open) html += s.others.map(o => `<tr class="rv-sub"><td></td><td class="ex-time">${esc(o.published)}</td>
    <td class="ex-src">${kindTag(o.kind)} ${esc(o.source)}</td>
    <td>↳ ${titleLink(o)}<span class="rv-meta">сходство ${pct(o.similarity)} · ${o.added
        ? `<b>+${o.added} симв. новых фактов</b>` : 'новых фактов нет — только ссылка'}</span></td>
    <td class="rv-act">${s.off ? '' : actBtn(o.id, 'separate', 'Отдельной строкой')}</td></tr>`).join('');
  return html;
}
function badges(s){
  let b = '';
  if(s.undated) b += '<span class="rv-badge warn" title="У новости на сайте нет даты — ChatGPT проверит её поиском">дата не подтверждена</span>';
  else if(s.date_check) b += `<span class="rv-badge" title="Как определена дата">дата ${esc(s.date_check)}</span>`;
  if(s.note) b += `<span class="rv-badge info" title="${esc(s.note)}">было в дайджесте</span>`;
  if(s.related) b += `<span class="rv-badge" title="Один сюжет, разные части события: номера соседей — в столбце «Связанные строки» CSV">сюжет +${s.related}</span>`;
  return b;
}
function paintReview(){
  const d = REVIEW; if(!d) return;
  const c = d.counts;
  $('rv-c-rows').textContent = c.rows; $('rv-c-multi').textContent = c.multi;
  $('rv-c-known').textContent = c.known; $('rv-c-excluded').textContent = c.excluded;
  $('rv-c-filtered').textContent = c.filtered;
  $('rv-note').textContent = RV_NOTES[RV_TAB];
  let html = '';
  if(RV_TAB === 'rows' || RV_TAB === 'multi'){
    const list = RV_TAB === 'multi' ? d.stories.filter(s => s.others.length) : d.stories;
    html = list.map(s => storyRows(s, RV_TAB === 'multi' || RV_OPEN.has(s.id))).join('');
  } else if(RV_TAB === 'known'){
    html = d.known.map(k => {
      const m = k.match;
      const what = m ? `${m.url ? `<a href="${esc(m.url)}" target="_blank">${esc(m.title)}</a>` : esc(m.title)} — ${esc(m.source)}${m.exported ? `, выгрузка ${m.exported}` : ''}` : '—';
      return `<tr><td class="rv-n"></td><td class="ex-time">${esc(k.published)}</td>
        <td class="ex-src">${kindTag(k.kind)} ${esc(k.source)}</td>
        <td>${titleLink(k)}<span class="rv-match">похоже на: ${what} · ${pct(k.similarity)}${k.others.length ? ` · вместе с ещё ${k.others.length} ${plural(k.others.length, 'версией', 'версиями', 'версиями')}` : ''}</span></td>
        <td class="rv-act">${actBtn(k.id, 'restore', 'Вернуть в CSV')}</td></tr>`;
    }).join('');
  } else if(RV_TAB === 'filtered'){
    html = d.filtered.map(f => `<tr><td class="rv-n"></td><td class="ex-time">${esc(f.published)}</td>
        <td class="ex-src">${kindTag(f.kind)} ${esc(f.source)}</td>
        <td>${titleLink(f)}<span class="rv-reason">${esc(f.reason || '')}</span></td>
        <td class="rv-act">${actBtn(f.id, 'restore', 'Вернуть в CSV')}</td></tr>`).join('');
  } else {
    html = d.excluded.map(s => storyRows({...s, off: true}, false)).join('');
  }
  $('rv-body').innerHTML = html || `<tr><td><div class="set-note" style="padding:16px">${
    {rows: 'Строк нет.', multi: 'Повторов между источниками не нашлось — каждая новость в своей строке.',
     known: 'Ничего из этой выгрузки раньше не выгружалось.', excluded: 'Вы ничего не убирали.',
     filtered: 'Фильтр ничего не отсеял.'}[RV_TAB]}</div></td></tr>`;
}
function rvToggle(id){ RV_OPEN.has(id) ? RV_OPEN.delete(id) : RV_OPEN.add(id); paintReview(); }
async function rvAction(id, action){
  if(!CURRENT) return;
  const r = await postJ(`/api/export/${CURRENT.id}/item`, {item_id: id, action});
  if(!r.ok){ toast(r.error || 'Не получилось', 'warn'); return loadReview(); }
  REVIEW = r; CURRENT = {...CURRENT, ...r.export};
  paintHeader(); paintReview(); loadHistory();
  if(action === 'exclude' || action === 'include') loadSuggest();
  toast({separate: 'Версия вынесена отдельной строкой', restore: 'Новость возвращена в CSV',
         exclude: 'Строка убрана из CSV', include: 'Строка возвращена в CSV'}[action] + ' · CSV обновлён', 'success');
}

/* ── действия с выгрузкой ──────────────────────────────── */
async function copyText(text){
  try{ if(await Native.available() && await window.pywebview.api.copy_text(text)) return true; }catch(e){}
  try{ await navigator.clipboard.writeText(text); return true; }catch(e){}
  try{ return (await postJ('/api/clipboard', {text})).ok; }catch(e){ return false; }
}
async function copyPrompt(){
  if(!CURRENT) return;
  toast(await copyText(CURRENT.prompt) ? 'Промпт скопирован' : 'Не удалось скопировать', 'success');
}
async function openExport(what){
  if(!CURRENT) return;
  const r = await postJ(`/api/export/${CURRENT.id}/open`, {what});
  if(!r.ok) toast(r.error || 'Не удалось открыть', 'error');
}
/* Автоподхват DOCX: пока выгрузка ждёт результат, каждые 5 с смотрим «Загрузки» и папку выгрузки */
let WATCH = null;
function watchDocx(){
  stopWatch();
  if(!CURRENT || CURRENT.result_exists) return;
  const id = CURRENT.id, until = Date.now() + 45 * 60 * 1000;
  WATCH = setInterval(async ()=>{
    if(!CURRENT || CURRENT.id !== id || CURRENT.result_exists || Date.now() > until) return stopWatch();
    let r; try{ r = await postJ(`/api/export/${id}/collect`); }catch(e){ return; }
    if(r.ok && CURRENT && CURRENT.id === id){
      stopWatch(); CURRENT = {...CURRENT, ...r.export}; paintResult(); loadHistory();
      toast('DOCX из ChatGPT найден и сохранён в папку выгрузки', 'success', 6000);
      if(window.fxConfetti) fxConfetti($('btn-docx'));
    }
  }, 5000);
  paintResult();
}
function stopWatch(){ if(WATCH){ clearInterval(WATCH); WATCH = null; if(CURRENT) paintResult(); } }

async function openChat(){
  watchDocx();
  if(await Native.available()){
    const how = await window.pywebview.api.open_chatgpt();
    if(how === 'browser') toast('ChatGPT открыт в браузере', 'info');
  } else {
    await postJ('/api/chatgpt/open');
  }
}
async function collectDocx(){
  if(!CURRENT) return;
  let r = await postJ(`/api/export/${CURRENT.id}/collect`);
  if(!r.ok && await Native.available()){
    if(confirm((r.error || 'DOCX не найден') + '\n\nВыбрать файл вручную?')){
      const p = await Native.pickFile('any');
      if(p) r = await postJ(`/api/export/${CURRENT.id}/collect`, {path: p});
    } else return;
  }
  if(!r.ok){ toast(r.error, 'warn', 7000); return; }
  CURRENT = {...CURRENT, ...r.export};
  paintResult(); loadHistory();
  toast('DOCX сохранён в папку выгрузки', 'success');
  if(window.fxConfetti) fxConfetti($('btn-docx'));
}

/* ── история ───────────────────────────────────────────── */
async function loadHistory(){
  const list = await (await fetch('/api/export/list?profile=' + PROFILE)).json();
  $('history-body').innerHTML = list.length ? list.map(e => `
    <tr class="ex-hist" onclick="showExport(${e.id}, false)">
      <td class="ex-time">${fmtDT(e.created_at)}</td>
      <td>период ${fmtPeriod(e.period_from, e.period_to)}</td>
      <td>${e.items_exported} ${plural(e.items_exported, 'строка', 'строки', 'строк')}${e.duplicates_removed ? ` <span class="set-note">(повторов свёрнуто: ${e.duplicates_removed})</span>` : ''}</td>
      <td style="text-align:right">${e.status === 'done' && e.result_exists
          ? '<span class="pill ok">DOCX ✓</span>' : '<span class="pill">без DOCX</span>'}</td>
    </tr>`).join('')
    : '<tr><td><div class="set-note" style="padding:14px">Выгрузок пока не было.</div></td></tr>';
}

/* ── старт ─────────────────────────────────────────────── */
(async function init(){
  const today = new Date(); const y = new Date(Date.now() - 864e5);
  const iso = d => d.toISOString().slice(0,10);
  $('date-from').value = iso(y); $('date-to').value = iso(today);
  try{ const p = await Prefs.get(), sec = SLK ? p.slk : p.export; if(sec) $('dedupe').checked = sec.dedup !== false; }catch(e){}
  loadPreview(); loadCollect(); loadHistory();
  setInterval(loadCollect, 30000);
  // Открыть выгрузку по ссылке (?open=ID — с обзора) или свежую утреннюю, если DOCX к ней ещё нет
  const want = +new URLSearchParams(location.search).get('open');
  if(want) return showExport(want, false);
  if(SLK) return;                                    // утренняя выгрузка — только общая
  try{
    const m = await (await fetch('/api/morning/status')).json();
    const last = m.last;
    if(last && last.export_id && Date.now() - new Date(last.at) < 18 * 3600e3){
      const e = await (await fetch('/api/export/' + last.export_id)).json();
      if(e && !e.result_exists){
        await showExport(last.export_id, false);
        toast(`Утренняя выгрузка готова: ${e.items_exported} строк. Промпт — кнопкой «Скопировать снова».`, 'success', 6000);
      }
    }
  }catch(e){}
})();
