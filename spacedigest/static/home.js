/* Экран «Обзор»: сводка на сегодня, график за 14 дней, здоровье источников, выгрузки. */
'use strict';
const $ = id => document.getElementById(id);
const esc = s => escHtml(s == null ? '' : String(s));
const N = n => (+n || 0).toLocaleString('ru-RU');
let D = null;

function plural(n, one, few, many){
  const a = Math.abs(n) % 100, b = a % 10;
  return (a > 10 && a < 20) ? many : b === 1 ? one : (b >= 2 && b <= 4) ? few : many;
}
const mskDate = iso => iso ? new Date(iso).toLocaleString('ru-RU', {timeZone:'Europe/Moscow', day:'2-digit', month:'2-digit', hour:'2-digit', minute:'2-digit'}) : '—';
const ddmm = d => d.slice(8, 10) + '.' + d.slice(5, 7);
const kindTag = k => `<span class="ex-kind ${k}">${k === 'telegram' ? 'TG' : 'Сайт'}</span>`;

/* ── главное на сейчас ── */
function paintHero(){
  const h = +D.now_msk.slice(11, 13);
  $('hero-hi').textContent = h < 5 ? 'Доброй ночи' : h < 12 ? 'Доброе утро' : h < 18 ? 'Добрый день' : 'Добрый вечер';
  const last = D.exports[0], m = D.morning && D.morning.last, p = D.pending;
  const fresh = m && m.export_id && last && last.id === m.export_id && !last.docx && (Date.now() - new Date(m.at) < 18 * 3600e3);
  let main, sub, act;
  if(fresh){
    main = `Утренняя выгрузка готова: <b>${N(m.rows)}</b> ${plural(m.rows, 'строка', 'строки', 'строк')}`;
    sub = `Подготовлена в ${mskDate(m.at)} МСК. Осталось вставить промпт и CSV в ChatGPT.`;
    act = `<a class="btn-run fx-cta hero-cta" href="/export?open=${m.export_id}">Открыть выгрузку</a>`;
  } else if(p.total){
    main = `С прошлой выгрузки: <b>${N(p.total)}</b> ${plural(p.total, 'новость', 'новости', 'новостей')}`;
    sub = [p.by_kind.rss ? `сайты ${N(p.by_kind.rss)}` : '', p.by_kind.telegram ? `Telegram ${N(p.by_kind.telegram)}` : '',
           p.filtered ? `фильтр отсеет ${N(p.filtered)}` : ''].filter(Boolean).join(' · ');
    act = `<a class="btn-run fx-cta hero-cta" href="/export">Подготовить выгрузку</a>`;
  } else {
    main = 'Новых новостей с прошлой выгрузки нет';
    sub = D.last_collect ? `Последний сбор: ${mskDate(D.last_collect)} МСК` : 'Сбор ещё не запускался';
    act = `<button class="btn" onclick="collectNow(this)">Собрать сейчас</button>`;
  }
  $('hero-main').innerHTML = main; $('hero-sub').textContent = sub;
  $('hero-act').innerHTML = act + (last && last.docx ? '' : '') + `<a class="btn fx-arrow" href="/export">Экран выгрузки</a>`;
}
async function collectNow(btn){
  btn.disabled = true; btn.textContent = 'Собираю…';
  try{ await fetch('/api/collect/now', {method:'POST'}); }catch(e){}
  toast('Сбор запущен — новости появятся через пару минут', 'success');
  setTimeout(load, 8000);
}

/* ── плитки ── */
function paintTiles(){
  $('t-rss').textContent = D.today.rss; $('t-tg').textContent = D.today.telegram;
  const c = D.chart, i = c.days.length - 2;
  $('t-rss-sub').textContent = `вчера ${N(c.rss[i])}`;
  $('t-tg-sub').textContent = `вчера ${N(c.telegram[i])}`;
}

/* ── график: столбцы с накоплением, сайты внизу, Telegram сверху ── */
function paintChart(){
  const box = $('chart'), c = D.chart;
  const W = box.clientWidth || 640, H = Math.max(220, Math.min(420, (box.clientHeight || 220) - 4)), padL = 34, padR = 8, padT = 10, padB = 26;
  const n = c.days.length, tot = c.days.map((_, k) => c.rss[k] + c.telegram[k]);
  const max = Math.max(4, ...tot);
  const step = Math.pow(10, Math.floor(Math.log10(max))), nice = Math.ceil(max / step) * step;
  const ticks = [0, nice / 2, nice];
  const y = v => padT + (H - padT - padB) * (1 - v / nice);
  const slot = (W - padL - padR) / n, bw = Math.min(28, slot * 0.62);
  const r = 4, gap = 2;
  let g = '';
  ticks.forEach(t => {
    g += `<line class="grid" x1="${padL}" x2="${W - padR}" y1="${y(t)}" y2="${y(t)}"/>` +
         `<text class="ax" x="${padL - 8}" y="${y(t) + 4}" text-anchor="end">${N(t)}</text>`;
  });
  const topPath = (x, yTop, yBot) => {           // скругление 4px только у вершины столбца
    const h = yBot - yTop, rr = Math.min(r, h, bw / 2);
    if(h <= 0) return '';
    return `M${x},${yBot} V${yTop + rr} Q${x},${yTop} ${x + rr},${yTop} H${x + bw - rr} Q${x + bw},${yTop} ${x + bw},${yTop + rr} V${yBot} Z`;
  };
  c.days.forEach((d, k) => {
    const x = padL + slot * k + (slot - bw) / 2, base = y(0);
    const yR = y(c.rss[k]), yT = y(c.rss[k] + c.telegram[k]);
    const hasTg = c.telegram[k] > 0, hasR = c.rss[k] > 0;
    // нижний сегмент (сайты); если сверху есть Telegram — без скругления, с зазором 2px
    if(hasR) g += hasTg ? `<rect class="b rss" x="${x}" y="${yR}" width="${bw}" height="${Math.max(0, base - yR)}"/>`
                        : `<path class="b rss" d="${topPath(x, yR, base)}"/>`;
    if(hasTg) g += `<path class="b tg" d="${topPath(x, yT, (hasR ? yR - gap : base))}"/>`;
    if(k % 2 === (n - 1) % 2) g += `<text class="ax${k === n - 1 ? ' today' : ''}" x="${x + bw / 2}" y="${H - 8}" text-anchor="middle">${k === n - 1 ? 'сегодня' : ddmm(d)}</text>`;
    g += `<rect class="hit" x="${padL + slot * k}" y="${padT}" width="${slot}" height="${H - padT - padB}" data-k="${k}"/>`;
  });
  box.innerHTML = `<svg viewBox="0 0 ${W} ${H}" width="100%" height="${H}">${g}</svg><div class="tip" id="tip"></div>`;
  const tip = $('tip');
  box.querySelectorAll('.hit').forEach(h => {
    h.addEventListener('mouseenter', () => {
      const k = +h.dataset.k;
      box.querySelectorAll('.hit').forEach(x => x.classList.toggle('on', x === h));
      tip.innerHTML = `<b>${new Date(c.days[k] + 'T12:00:00').toLocaleDateString('ru-RU', {day:'numeric', month:'long', weekday:'short'})}</b>
        <div><i class="sw rss"></i>Сайты<span>${N(c.rss[k])}</span></div>
        <div><i class="sw tg"></i>Telegram<span>${N(c.telegram[k])}</span></div>
        <div class="tot">Всего<span>${N(tot[k])}</span></div>`;
      const bx = (padL + slot * k + slot / 2) / W * box.clientWidth;
      tip.style.left = Math.min(box.clientWidth - 170, Math.max(0, bx - 80)) + 'px';
      tip.classList.add('show');
    });
  });
  box.addEventListener('mouseleave', () => { tip.classList.remove('show'); box.querySelectorAll('.hit.on').forEach(x => x.classList.remove('on')); });
  $('chart-table').innerHTML = `<table class="news-table"><thead><tr><th>День</th><th>Сайты</th><th>Telegram</th><th>Всего</th></tr></thead><tbody>${
    c.days.map((d, k) => `<tr><td>${ddmm(d)}</td><td>${N(c.rss[k])}</td><td>${N(c.telegram[k])}</td><td><b>${N(tot[k])}</b></td></tr>`).reverse().join('')}</tbody></table>`;
}
function toggleChartTable(){
  const t = $('chart-table'), show = t.style.display === 'none';
  t.style.display = show ? '' : 'none'; $('chart').style.display = show ? 'none' : '';
  $('chart-tbl-btn').textContent = show ? 'График' : 'Таблица';
}

/* ── источники ── */
function paintHealth(){
  const s = D.sources, a = s.active;
  $('h-sum').innerHTML = `<div><b>${N(a.rss)}</b><span>сайтов</span></div><div><b>${N(a.telegram)}</b><span>каналов</span></div>
    <div class="${s.problems_total ? 'bad' : 'ok'}"><b>${s.problems_total || '✓'}</b><span>${s.problems_total ? 'требуют внимания' : 'все работают'}</span></div>`;
  $('h-list').innerHTML = s.problems.slice(0, 5).map(p => `<li class="${p.why}">
      <span class="dot"></span><div><div class="nm">${kindTag(p.kind)} ${esc(p.name)}</div><div class="why">${esc(p.text)}</div></div></li>`).join('')
    + (s.problems_total > 5 ? `<li class="none"><a class="link-btn" href="/settings#sources">и ещё ${s.problems_total - 5} — открыть список</a></li>` : '')
    || '<li class="none">Ни одной ошибки сбора, все источники присылают новости.</li>';
}

/* ── утренняя выгрузка ── */
function paintMorning(){
  const m = D.morning || {}, sch = m.schedule || {}, last = m.last;
  const on = sch.enabled;
  $('m-box').innerHTML = `<div class="m-time"><span class="m-clock">${esc(sch.at_time || '09:00')}</span><span class="pill ${on ? 'ok' : ''}">${on ? 'включена' : 'выключена'}</span></div>
    <div class="m-line">${on ? `Следующая: ${mskDate(sch.next_run_at)} МСК` : 'Включите в настройках — к утру CSV и промпт будут готовы сами.'}</div>
    ${last ? `<div class="m-line">Последняя: ${mskDate(last.at)} — ${last.error ? esc(last.error) : `${N(last.rows)} ${plural(last.rows, 'строка', 'строки', 'строк')}`}</div>` : ''}
    ${m.autostart === false && on ? '<div class="m-warn">Программа не запускается вместе с компьютером — если она будет закрыта утром, выгрузка подготовится при запуске.</div>' : ''}`;
}

/* ── выгрузки ── */
function paintExports(){
  $('ex-list').innerHTML = D.exports.map(e => `<li>
      <span class="tl-dot ${e.docx ? 'ok' : ''}"></span>
      <a href="/export?open=${e.id}" class="tl-main"><b>${mskDate(e.created_at)}</b>
        <span>период ${ddmm(e.period_from || '0000-00-00')}${e.period_to && e.period_to !== e.period_from ? '–' + ddmm(e.period_to) : ''} · ${N(e.rows)} ${plural(e.rows, 'строка', 'строки', 'строк')}</span></a>
      <span class="pill ${e.docx ? 'ok' : 'warn'}">${e.docx ? 'DOCX получен' : 'без DOCX'}</span></li>`).join('')
    || '<li class="none">Выгрузок пока не было.</li>';
}

/* ── топ источников ── */
function paintTop(){
  const max = Math.max(1, ...D.top.map(t => t.n));
  $('top-list').innerHTML = D.top.map(t => `<li><div class="nm">${kindTag(t.kind)} ${esc(t.name)}</div>
      <div class="bar"><i style="width:${Math.max(4, t.n / max * 100)}%"></i></div><b>${N(t.n)}</b></li>`).join('')
    || '<li class="none">Сегодня новостей ещё не было.</li>';
}

/* ── качество ── */
function paintQuality(){
  const f = D.fulltext;
  const pct = f.short ? Math.round(f.ok / f.short * 100) : 100;
  $('q-box').innerHTML = (f.short ? `
    <div class="q-row"><div><b>${N(f.ok)}</b> из ${N(f.short)} коротких статей</div><span>полный текст взят со страницы (7 дней)</span>
      <div class="bar"><i style="width:${pct}%"></i></div></div>` : `
    <div class="q-row"><div><b>Коротких статей нет</b></div><span>за 7 дней все новости сайтов пришли с полным текстом</span></div>`) + `
    <div class="q-row"><div><b>${N(D.filtered_week)}</b> ${plural(D.filtered_week, 'новость', 'новости', 'новостей')}</div><span>отсеял фильтр мусора за неделю</span></div>
    <div class="q-row"><div><b>${mskDate(D.last_collect)}</b></div><span>последний сбор (МСК)</span></div>`;
}

async function load(){
  try{ D = await (await fetch('/api/dashboard')).json(); }catch(e){ return; }
  if(!D.ok){ $('hero-main').textContent = D.error || 'Ядро не запущено'; return; }
  paintHero(); paintTiles(); paintChart(); paintHealth(); paintMorning(); paintExports(); paintTop(); paintQuality();
}
let rt = 0;
window.addEventListener('resize', () => { clearTimeout(rt); rt = setTimeout(() => D && paintChart(), 150); });
load();
setInterval(load, 60000);
