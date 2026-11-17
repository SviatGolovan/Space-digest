/* Space Digest 4 — эффекты интерфейса в духе Aceternity UI и Magic UI, на чистом JS.
   Magic UI: Animated Grid Pattern, Border Beam, Ripple, Confetti, Orbiting Circles,
   Animated Beam, Scroll Progress, Number Ticker, Blur Fade.
   Background Beams + Aurora + Spotlight (фон), Glowing Effect (карточки), Tabs/Card Hover
   (скользящая подсветка пунктов), Text Generate (заголовки), Meteors (готовая выгрузка),
   счётчики чисел. Всё отключается в Настройки → Общие → «Анимации» (класс .fx на <html>)
   и при системной настройке «уменьшить движение». */
(function(){
  'use strict';
  const root = document.documentElement;
  const reduced = window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches;
  const FX = root.classList.contains('fx') && !reduced;
  const CARDS = '.card,.stat,.table-wrap,.set-group,.an-panel,.w-card,#progress-wrap,.lock-screen';

  /* ── Скользящая подсветка пунктов (Aceternity Tabs / Card Hover Effect) ── */
  function pill(container, itemSel, activeSel){
    if(container.__pill) return;
    const p = document.createElement('span');
    p.className = 'fx-pill'; p.style.left = '0'; p.style.top = '0'; p.style.opacity = '0';
    container.prepend(p); container.classList.add('has-pill'); container.__pill = p;
    let hover = null, raf = 0;
    const place = () => {
      raf = 0;
      const el = hover || container.querySelector(activeSel);
      if(!el || !el.offsetParent){ p.style.opacity = '0'; return; }
      const c = container.getBoundingClientRect(), r = el.getBoundingClientRect();
      p.style.width = r.width + 'px'; p.style.height = r.height + 'px';
      p.style.transform = `translate(${r.left - c.left - container.clientLeft}px,${r.top - c.top - container.clientTop}px)`;
      p.style.opacity = '1';
      const isHover = !!hover && !hover.matches(activeSel);
      if(p.classList.contains('hover') !== isHover) p.classList.toggle('hover', isHover);
    };
    const update = () => { if(!raf) raf = requestAnimationFrame(place); };
    container.addEventListener('mouseover', e => {
      const it = e.target.closest(itemSel);
      if(it && container.contains(it) && it !== hover){ hover = it; update(); }
    });
    container.addEventListener('mouseleave', () => { hover = null; update(); });
    new MutationObserver(update).observe(container, {subtree:true, attributes:true, attributeFilter:['class'], childList:true});
    if(window.ResizeObserver) new ResizeObserver(update).observe(container);
    window.addEventListener('resize', update);
    // первое появление — без «прилёта» из угла
    p.style.transition = 'none'; place(); requestAnimationFrame(() => { p.style.transition = ''; });
  }
  function initPills(){
    document.querySelectorAll('.tabbar').forEach(c => pill(c, '.tab-link', '.tab-link.active'));
    document.querySelectorAll('.set-nav').forEach(c => pill(c, 'a', 'a.active'));
    document.querySelectorAll('.seg').forEach(c => pill(c, 'button', 'button.on'));
  }

  /* ── Фон: Aurora + Background Beams + Spotlight ── */
  function beamsSVG(){
    const NS = 'http://www.w3.org/2000/svg';
    const svg = document.createElementNS(NS, 'svg');
    svg.setAttribute('class', 'beams'); svg.setAttribute('viewBox', '0 0 696 316');
    svg.setAttribute('preserveAspectRatio', 'xMidYMid slice'); svg.setAttribute('fill', 'none');
    const defs = document.createElementNS(NS, 'defs');
    const paths = [];
    for(let i = 0; i < 50; i++){
      const a = 380 - i * 5, b = 189 + i * 6, c = 312 - i * 5, d = 216 - i * 6, e = 152 - i * 5, f = 343 - i * 6,
            g = 616 - i * 5, h = 470 - i * 6, k = 684 - i * 5, l = 875 - i * 6;
      paths.push(`M-${a} -${b}C-${a} -${b} -${c} ${d} ${e} ${f}C${g} ${h} ${k} ${l} ${k} ${l}`);
    }
    defs.innerHTML = `<radialGradient id="fxb-base" cx="0" cy="0" r="1" gradientUnits="userSpaceOnUse"
        gradientTransform="translate(352 34) rotate(90) scale(555 1560)">
        <stop offset=".07" stop-color="#94a3b8"/><stop offset=".24" stop-color="#94a3b8"/><stop offset=".44" stop-color="#94a3b8" stop-opacity="0"/></radialGradient>`;
    const base = document.createElementNS(NS, 'path');
    base.setAttribute('d', paths.join(' ')); base.setAttribute('stroke', 'url(#fxb-base)');
    base.setAttribute('stroke-opacity', '.18'); base.setAttribute('stroke-width', '.5');
    svg.appendChild(defs); svg.appendChild(base);
    const rnd = (a, b) => a + Math.random() * (b - a);
    paths.forEach((d, i) => {
      if(i % 3) return;                                 // анимируем каждый третий луч — легче для видеокарты
      const id = 'fxb-' + i, dur = rnd(10, 20).toFixed(1) + 's', begin = rnd(0, 10).toFixed(1) + 's';
      const y2 = (93 + Math.random() * 8).toFixed(0) + '%';
      const grad = document.createElementNS(NS, 'linearGradient');
      grad.setAttribute('id', id);
      grad.innerHTML = `<stop stop-color="#0ea5e9" stop-opacity="0"/><stop stop-color="#0ea5e9"/>
        <stop offset=".325" stop-color="#2563eb"/><stop offset="1" stop-color="#6366f1" stop-opacity="0"/>
        <animate attributeName="x1" values="0%;100%" dur="${dur}" begin="${begin}" repeatCount="indefinite"/>
        <animate attributeName="x2" values="0%;95%" dur="${dur}" begin="${begin}" repeatCount="indefinite"/>
        <animate attributeName="y1" values="0%;100%" dur="${dur}" begin="${begin}" repeatCount="indefinite"/>
        <animate attributeName="y2" values="0%;${y2}" dur="${dur}" begin="${begin}" repeatCount="indefinite"/>`;
      defs.appendChild(grad);
      const p = document.createElementNS(NS, 'path');
      p.setAttribute('d', d); p.setAttribute('stroke', `url(#${id})`);
      p.setAttribute('stroke-opacity', '.55'); p.setAttribute('stroke-width', '.6');
      svg.appendChild(p);
    });
    return svg;
  }
  /* Animated Grid Pattern (Magic UI): случайные клетки сетки плавно вспыхивают */
  function gridSVG(){
    const NS = 'http://www.w3.org/2000/svg', S = 44;
    const svg = document.createElementNS(NS, 'svg');
    svg.setAttribute('class', 'grid');
    svg.innerHTML = `<defs><pattern id="fxg" width="${S}" height="${S}" patternUnits="userSpaceOnUse">
      <path d="M${S} 0H0V${S}" fill="none" stroke="rgba(37,99,235,.10)" stroke-width="1"/></pattern></defs>
      <rect width="100%" height="100%" fill="url(#fxg)"/>`;
    const cells = [];
    for(let i = 0; i < 26; i++){
      const r = document.createElementNS(NS, 'rect');
      r.setAttribute('width', S - 1); r.setAttribute('height', S - 1);
      svg.appendChild(r); cells.push(r);
    }
    const move = r => {
      const cols = Math.ceil(innerWidth / S), rows = Math.ceil(innerHeight * 0.7 / S);
      r.setAttribute('x', Math.floor(Math.random() * cols) * S + 1);
      r.setAttribute('y', Math.floor(Math.random() * rows) * S + 1);
    };
    cells.forEach((r, i) => { move(r); setTimeout(() => r.classList.add('on'), i * 180); });
    setInterval(() => {
      if(document.hidden || root.classList.contains('fx-idle')) return;
      const r = cells[Math.floor(Math.random() * cells.length)];
      r.classList.remove('on');
      setTimeout(() => { move(r); r.classList.add('on'); }, 1700);
    }, 1400);
    return svg;
  }

  function initBackground(){
    if(document.getElementById('fx-bg')) return;
    const bg = document.createElement('div');
    bg.id = 'fx-bg'; bg.setAttribute('aria-hidden', 'true');
    bg.innerHTML = '<div class="aurora"></div>';
    bg.appendChild(gridSVG());
    bg.appendChild(beamsSVG());
    document.body.prepend(bg);
    // свернули окно — останавливаем SMIL-анимации лучей
    const svg = bg.querySelector('svg');
    document.addEventListener('visibilitychange', () => {
      try{ document.hidden ? svg.pauseAnimations() : svg.unpauseAnimations(); }catch(e){}
    });
  }

  /* ── Glowing Effect + Spotlight на карточках ── */
  let cards = [];
  function collectCards(){
    cards = Array.from(document.querySelectorAll(CARDS));
    cards.forEach(c => c.classList.add('fx-glow'));
  }
  function initGlow(){
    collectCards();
    let pending = null, raf = 0;
    const PROX = 70;
    const frame = () => {
      raf = 0;
      const e = pending; if(!e) return;
      for(const c of cards){
        if(!c.offsetParent){ continue; }
        const r = c.getBoundingClientRect();
        const near = e.clientX > r.left - PROX && e.clientX < r.right + PROX &&
                     e.clientY > r.top - PROX && e.clientY < r.bottom + PROX;
        if(near){
          const cx = r.left + r.width / 2, cy = r.top + r.height / 2;
          const ang = Math.atan2(e.clientY - cy, e.clientX - cx) * 180 / Math.PI + 90;
          c.style.setProperty('--fx-a', ang.toFixed(1) + 'deg');
          c.style.setProperty('--fx-x', (e.clientX - r.left).toFixed(0) + 'px');
          c.style.setProperty('--fx-y', (e.clientY - r.top).toFixed(0) + 'px');
          if(c.__on !== true){ c.style.setProperty('--fx-o', '1'); c.__on = true; }
        } else if(c.__on){ c.style.setProperty('--fx-o', '0'); c.__on = false; }
      }
    };
    document.addEventListener('pointermove', e => {
      if(root.classList.contains('fx-idle')) return;
      pending = e; if(!raf) raf = requestAnimationFrame(frame);
    }, {passive:true});
    document.addEventListener('pointerleave', () => { cards.forEach(c => { c.style.setProperty('--fx-o', '0'); c.__on = false; }); });
    let t = 0;
    new MutationObserver(() => { clearTimeout(t); t = setTimeout(collectCards, 300); })
      .observe(document.body, {childList:true, subtree:true});
  }

  /* ── Text Generate: слова проявляются из размытия ── */
  function generate(el){
    if(!el || el.__gen === el.textContent) return;
    const text = el.textContent.trim();
    el.innerHTML = '';
    text.split(/\s+/).forEach((w, i) => {
      const s = document.createElement('span');
      s.className = 'fx-word'; s.textContent = w;
      s.style.animationDelay = (i * 0.08) + 's';
      el.appendChild(s); el.appendChild(document.createTextNode(' '));
    });
    el.__gen = el.textContent;
  }
  function initGenerate(){
    const secs = document.querySelectorAll('.set-sec');
    if(!secs.length) return;
    let last = null;
    const run = () => {
      const s = document.querySelector('.set-sec.active');
      if(!s || s === last) return;                     // анимируем только при смене раздела
      last = s;
      const h = s.querySelector('.set-h h2');
      if(h){ h.__gen = null; generate(h); }
    };
    const mo = new MutationObserver(run);
    secs.forEach(sec => mo.observe(sec, {attributes:true, attributeFilter:['class']}));
    run();
  }

  /* ── Meteors в панели готовой выгрузки ── */
  function meteors(box, n){
    if(box.__meteors) return;
    box.__meteors = true;
    for(let i = 0; i < n; i++){
      const m = document.createElement('span');
      m.className = 'fx-meteor';
      m.style.left = (Math.random() * 110 - 5) + '%';
      m.style.animationDelay = (Math.random() * 6).toFixed(2) + 's';
      m.style.animationDuration = (Math.random() * 6 + 4).toFixed(2) + 's';
      box.appendChild(m);
    }
  }
  function initMeteors(){
    const steps = document.getElementById('steps');
    if(!steps) return;
    const check = () => { if(steps.style.display !== 'none') meteors(steps, 14); };
    new MutationObserver(check).observe(steps, {attributes:true, attributeFilter:['style']});
    check();
  }

  /* ── Числа плавно «набегают» ── */
  function initCounters(){
    document.querySelectorAll('.stat-val').forEach(el => {
      let busy = false, prev = parseInt(el.textContent, 10);
      new MutationObserver(() => {
        if(busy) return;
        const txt = el.textContent.trim();
        if(!/^\d+$/.test(txt)){ prev = NaN; return; }
        const to = +txt, from = isNaN(prev) ? 0 : prev;
        prev = to;
        if(from === to) return;
        const t0 = performance.now(), D = 700;
        busy = true;
        const step = now => {
          const k = Math.min(1, (now - t0) / D), e = 1 - Math.pow(1 - k, 3);
          el.textContent = Math.round(from + (to - from) * e);
          if(k < 1) requestAnimationFrame(step); else { el.textContent = to; busy = false; }
        };
        requestAnimationFrame(step);
      }).observe(el, {childList:true, characterData:true, subtree:true});
    });
  }

  /* ── Появление панелей при загрузке ── */
  function initReveal(){
    let i = 0;
    document.querySelectorAll('.sidebar > *, .main > *, .set-sec.active > *').forEach(el => {
      if(el.offsetParent === null) return;
      el.classList.add('fx-in'); el.style.animationDelay = Math.min(i++ * 0.05, 0.4) + 's';
    });
  }

  /* ── Значок «доступна новая версия» на кнопке «Настройки» ── */
  function initUpdateDot(){
    const dot = document.getElementById('upd-dot');
    if(!dot) return;
    setTimeout(() => {
      fetch('/api/update/check?auto=1').then(r => r.json()).then(d => {
        if(d && d.available){ dot.classList.add('on'); dot.title = 'Доступна версия ' + d.latest + ' — Настройки → О программе'; }
      }).catch(() => {});
    }, 2500);
  }

  /* ── Confetti (Magic UI): праздник, когда выгрузка готова или DOCX забран ── */
  window.fxConfetti = function(origin){
    if(!FX) return;
    const cv = document.createElement('canvas');
    cv.style.cssText = 'position:fixed;inset:0;width:100%;height:100%;pointer-events:none;z-index:1200';
    const dpr = Math.min(2, devicePixelRatio || 1);
    cv.width = innerWidth * dpr; cv.height = innerHeight * dpr;
    document.body.appendChild(cv);
    const ctx = cv.getContext('2d'); ctx.scale(dpr, dpr);
    let ox = innerWidth / 2, oy = innerHeight * 0.6;
    if(origin && origin.getBoundingClientRect){ const r = origin.getBoundingClientRect(); ox = r.left + r.width / 2; oy = r.top + r.height / 2; }
    const colors = ['#1d4ed8', '#2563eb', '#3b82f6', '#0ea5e9', '#7dd3fc', '#93c5fd', '#ffffff', '#facc15'];
    const P = Array.from({length: 140}, () => {
      const a = -Math.PI / 2 + (Math.random() - 0.5) * 1.6, v = 7 + Math.random() * 9;
      return {x: ox, y: oy, vx: Math.cos(a) * v, vy: Math.sin(a) * v, w: 5 + Math.random() * 5, h: 3 + Math.random() * 4,
              r: Math.random() * 6, vr: (Math.random() - 0.5) * 0.4, c: colors[(Math.random() * colors.length) | 0], life: 1};
    });
    const t0 = performance.now();
    const tick = now => {
      ctx.clearRect(0, 0, innerWidth, innerHeight);
      let alive = 0;
      for(const p of P){
        p.vy += 0.28; p.vx *= 0.985; p.vy *= 0.985; p.x += p.vx; p.y += p.vy; p.r += p.vr;
        p.life = Math.max(0, 1 - (now - t0) / 2600);
        if(p.y < innerHeight + 20 && p.life > 0){ alive++;
          ctx.save(); ctx.globalAlpha = p.life; ctx.translate(p.x, p.y); ctx.rotate(p.r);
          ctx.fillStyle = p.c; ctx.strokeStyle = 'rgba(15,40,90,.15)'; ctx.lineWidth = .5;
          ctx.fillRect(-p.w / 2, -p.h / 2, p.w, p.h); ctx.strokeRect(-p.w / 2, -p.h / 2, p.w, p.h); ctx.restore(); }
      }
      if(alive) requestAnimationFrame(tick); else cv.remove();
    };
    requestAnimationFrame(tick);
  };

  /* ── Animated Beam (Magic UI): схема «Сайты + Telegram → Space Digest → ChatGPT → DOCX» ── */
  function initFlow(){
    const box = document.getElementById('fx-flow');
    if(!box || box.__done) return;
    box.__done = true;
    const ico = {
      rss: '<path d="M5 19m-1 0a1 1 0 1 0 2 0a1 1 0 1 0-2 0"/><path d="M4 4a16 16 0 0 1 16 16"/><path d="M4 11a9 9 0 0 1 9 9"/>',
      tg: '<path d="M15 10l-4 4 6 6 4-16-18 7 4 2 2 6 3-4"/>',
      gpt: '<path d="M8 9h8M8 13h6"/><path d="M18 4a3 3 0 0 1 3 3v8a3 3 0 0 1-3 3h-5l-5 3v-3H6a3 3 0 0 1-3-3V7a3 3 0 0 1 3-3z"/>',
      doc: '<path d="M14 3v4a1 1 0 0 0 1 1h4"/><path d="M17 21H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h7l5 5v11a2 2 0 0 1-2 2z"/><path d="M9 13h6M9 17h6"/>',
    };
    const svgI = n => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">${ico[n]}</svg>`;
    const logo = document.querySelector('header .logo svg');
    const nodes = [
      {id: 'rss', x: 10, y: 28, label: 'Сайты (RSS)', html: svgI('rss')},
      {id: 'tg', x: 10, y: 72, label: 'Telegram', html: svgI('tg')},
      {id: 'hub', x: 40, y: 50, label: 'Space Digest', html: logo ? logo.outerHTML : '', hub: true},
      {id: 'gpt', x: 68, y: 50, label: 'ChatGPT', html: svgI('gpt')},
      {id: 'doc', x: 90, y: 50, label: 'DOCX', html: svgI('doc')},
    ];
    const NS = 'http://www.w3.org/2000/svg';
    const svg = document.createElementNS(NS, 'svg');
    svg.innerHTML = '<defs></defs>';
    box.appendChild(svg);
    nodes.forEach(n => {
      const el = document.createElement('div');
      el.className = 'fx-node' + (n.hub ? ' hub' : '');
      el.style.left = n.x + '%'; el.style.top = n.y + '%';
      el.innerHTML = `<div class="b">${n.html}</div><span>${n.label}</span>`;
      box.appendChild(el); n.el = el.querySelector('.b');
    });
    const links = [['rss', 'hub', 0], ['tg', 'hub', 0.6], ['hub', 'gpt', 1.2], ['gpt', 'doc', 1.8]];
    const draw = () => {
      const c = box.getBoundingClientRect();
      if(!c.width) return;
      svg.querySelectorAll('path').forEach(p => p.remove());
      const defs = svg.querySelector('defs'); defs.innerHTML = '';
      links.forEach(([a, b, delay], i) => {
        const A = nodes.find(n => n.id === a).el.getBoundingClientRect(), B = nodes.find(n => n.id === b).el.getBoundingClientRect();
        const x1 = A.right - c.left, y1 = A.top + A.height / 2 - c.top, x2 = B.left - c.left, y2 = B.top + B.height / 2 - c.top;
        const mx = (x1 + x2) / 2, d = `M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}`;
        const base = document.createElementNS(NS, 'path');
        base.setAttribute('d', d); base.style.stroke = 'var(--track-2)'; base.setAttribute('stroke-width', '2');
        base.setAttribute('fill', 'none'); base.setAttribute('stroke-linecap', 'round');
        svg.appendChild(base);
        if(!FX) return;
        const beam = base.cloneNode(); const len = base.getTotalLength();
        // градиент в координатах страницы: у прямой линии нулевая высота, «по рамке» он бы не нарисовался
        defs.insertAdjacentHTML('beforeend', `<linearGradient id="fxbeam${i}" gradientUnits="userSpaceOnUse" x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}">
          <stop offset="0" stop-color="#7dd3fc"/><stop offset=".5" stop-color="#0ea5e9"/><stop offset="1" stop-color="#1d4ed8"/></linearGradient>`);
        beam.setAttribute('stroke', `url(#fxbeam${i})`); beam.setAttribute('stroke-width', '2.5');
        beam.setAttribute('stroke-dasharray', `${Math.min(70, len * .45)} ${len}`);
        beam.animate([{strokeDashoffset: Math.min(70, len * .45)}, {strokeDashoffset: -len}],
                     {duration: 2400, delay: delay * 1000, iterations: Infinity, easing: 'cubic-bezier(.4,0,.2,1)'});
        svg.appendChild(beam);
      });
    };
    if(window.ResizeObserver) new ResizeObserver(draw).observe(box);
    requestAnimationFrame(draw);
  }

  /* ── Scroll Progress ── */
  function initProgress(){
    const bar = document.createElement('div');
    bar.id = 'fx-progress'; document.body.appendChild(bar);
    let raf = 0;
    const upd = () => { raf = 0;
      const h = document.documentElement.scrollHeight - innerHeight;
      bar.style.setProperty('--p', h > 0 ? (scrollY / h).toFixed(4) : 0);
    };
    addEventListener('scroll', () => { if(!raf) raf = requestAnimationFrame(upd); }, {passive:true});
    upd();
  }

  /* ── Ripple: волна от точки нажатия на кнопке ── */
  function initRipple(){
    document.addEventListener('pointerdown', e => {
      const b = e.target.closest('.btn,.btn-fetch,.btn-run,.btn-csv,.btn-week,.btn-secondary,.hist-btn,.gear-btn');
      if(!b || b.disabled) return;
      const r = b.getBoundingClientRect(), d = Math.max(r.width, r.height);
      const s = document.createElement('span');
      s.className = 'fx-ripple';
      s.style.width = s.style.height = d + 'px';
      s.style.left = (e.clientX - r.left - d / 2) + 'px'; s.style.top = (e.clientY - r.top - d / 2) + 'px';
      if(getComputedStyle(b).position === 'static') b.style.position = 'relative';
      b.appendChild(s); setTimeout(() => s.remove(), 650);
    });
  }

  /* ── Пустые состояния: вместо эмодзи — единая линейная иконка (планета с орбитой) ── */
  const EMPTY_SVG = '<svg viewBox="0 0 24 24" width="26" height="26" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="5"/><ellipse cx="12" cy="12" rx="10" ry="3.6" transform="rotate(-24 12 12)"/></svg>';
  function iconEmpty(){
    document.querySelectorAll('.empty-icon:not(.fx-svg)').forEach(ic => {
      ic.classList.add('fx-svg'); ic.innerHTML = EMPTY_SVG;
    });
  }

  /* ── Orbiting Circles вокруг иконок пустых состояний ── */
  function orbitEmpty(){
    document.querySelectorAll('.empty-icon:not(.fx-orb)').forEach(ic => {
      ic.classList.add('fx-orb');
      const w = document.createElement('div');
      w.className = 'fx-orbit';
      w.innerHTML = '<span class="ring"></span><span class="ring r2"></span><span class="sat"></span><span class="sat s2"></span><span class="sat s3"></span>';
      ic.parentNode.insertBefore(w, ic); w.appendChild(ic);
    });
  }

  /* ── Border Beam на панели готовой выгрузки ── */
  function initBorderBeam(){
    const steps = document.getElementById('steps');
    if(!steps) return;
    steps.classList.add('fx-beam');
    const ring = document.createElement('span');
    ring.className = 'fx-beam-ring'; steps.appendChild(ring);
  }

  /* ── Пауза, когда окно не в фокусе ──
     Все окна программы (и ChatGPT) рисует один графический процесс WebView2: если главное
     окно продолжает анимации, пока вы работаете в ChatGPT, тормозит именно ChatGPT. */
  function initIdle(){
    let paused = [];
    const apply = () => {
      const idle = document.hidden || !document.hasFocus();
      if(idle === root.classList.contains('fx-idle')) return;
      root.classList.toggle('fx-idle', idle);
      if(!document.getAnimations) return;
      if(idle){
        paused = document.getAnimations().filter(a => a.playState === 'running');
        paused.forEach(a => { try{ a.pause(); }catch(e){} });
      } else {
        paused.forEach(a => { try{ if(a.playState === 'paused') a.play(); }catch(e){} });
        paused = [];
      }
    };
    addEventListener('blur', apply); addEventListener('focus', apply);
    document.addEventListener('visibilitychange', apply);
    setTimeout(apply, 300);
  }

  function init(){
    initIdle();
    initUpdateDot();
    initFlow();
    iconEmpty();
    let it = 0;
    new MutationObserver(() => { clearTimeout(it); it = setTimeout(iconEmpty, 30); })
      .observe(document.body, {childList:true, subtree:true});
    if(!FX) return;
    initBackground(); initPills(); initGlow(); initGenerate(); initMeteors(); initCounters(); initReveal();
    initProgress(); initRipple(); initBorderBeam(); orbitEmpty();
    let ot = 0;
    new MutationObserver(() => { clearTimeout(ot); ot = setTimeout(orbitEmpty, 60); })
      .observe(document.body, {childList:true, subtree:true});
    // секции настроек и вкладки, появляющиеся позже
    setTimeout(initPills, 500);
  }
  if(document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
