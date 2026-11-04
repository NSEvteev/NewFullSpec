/* Поведение страниц карты. Страницы собирает tools/build.py — руками не правятся; поведение — только здесь.
   Тема одна, светлая: переключателя нет.
   1. Ссылки на код и на md открываются в редакторе. Полный путь страница считает сама из своего места на диске
      (body[data-repo] — путь от страницы к корню репо), поэтому в html нет путей этой машины. Страница открыта
      не с диска — ссылка показывает путь подсказкой.
   2. Меню разделов подсвечивает раздел, который сейчас на экране; ссылка внутрь свёрнутого раскрывает его.
   3. Поиск в шапке: Ctrl+K — в строку поиска; найденное в ключах карты (ASIS/keys.js) — выпадающим списком,
      ↑ ↓ — выбор, Enter — переход, Esc — закрыть. Общее меню «Сервисы» и «Процессы» — открыт один список.
      Строка таблицы с классом row-link — ссылка целиком (data-href).
   4. Сводные таблицы: «раскрыть все» и «только с проблемами».
   5. Процесс: наведение на строку стрелки подсвечивает её на схеме, и наоборот (data-a).
   6. Доска: колесо и кнопки «− / +» — масштаб, тянуть фон — сдвиг, тянуть узел — переставить (браузер помнит раскладку,
      «Сбросить» возвращает её из project/board.yaml), «Во весь экран», «Скопировать раскладку» — блок nodes для
      project/board.yaml; галочки под доской включают и выключают виды связей; наведение на процесс в колонке
      справа — его путь по доске с номерами стрелок; от 115 % подписи видны у всех линий. */
(function () {
  'use strict';
  const root = document.documentElement;
  const store = {
    get(k, d) { try { return localStorage.getItem(k) || d; } catch (e) { return d; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* без хранилища — по умолчанию */ } },
  };

  document.addEventListener('DOMContentLoaded', () => {

    /* 1. редактор */
    const tpl = document.body.dataset.editor || '';
    const repo = new URL(document.body.dataset.repo || './', location.href);
    document.querySelectorAll('a.cref, a.md-src').forEach((a) => {
      const rel = a.dataset.p, line = a.dataset.l || '1';
      if (!rel) return;
      const abs = new URL(rel, repo);
      if (location.protocol === 'file:' && tpl) {
        let p = decodeURIComponent(abs.pathname);
        if (/^\/[A-Za-z]:\//.test(p)) p = p.slice(1);
        a.href = tpl.replace('{path}', p).replace('{line}', line);
      } else {
        a.removeAttribute('href');
        a.title = `${rel}:${line} — открыть в редакторе можно со страницы, открытой с диска`;
      }
    });

    /* 2. меню и свёрнутое */
    function openTo() {
      if (!location.hash) return;
      const t = document.getElementById(decodeURIComponent(location.hash.slice(1)));
      if (!t) return;
      let d = t.tagName === 'DETAILS' ? t : t.closest('details');
      while (d) { d.open = true; d = d.parentElement && d.parentElement.closest('details'); }
      t.scrollIntoView({ block: 'start' });
    }
    window.addEventListener('hashchange', openTo);
    openTo();
    const links = new Map();
    document.querySelectorAll('.side .toc > li > a[href^="#"]').forEach((a) => links.set(a.getAttribute('href').slice(1), a));
    if (links.size && 'IntersectionObserver' in window) {
      const vis = new Set();
      const io = new IntersectionObserver((es) => {
        es.forEach((e) => (e.isIntersecting ? vis.add(e.target.id) : vis.delete(e.target.id)));
        const cur = [...document.querySelectorAll('main.secs > .sec')].find((s) => vis.has(s.id));
        links.forEach((a, id) => a.parentElement.classList.toggle('active', !!cur && cur.id === id));
      }, { rootMargin: '-10% 0px -60% 0px' });
      document.querySelectorAll('main.secs > .sec').forEach((s) => io.observe(s));
    }

    /* 3. поиск в шапке: ключи карты из ASIS/keys.js, найденное — выпадающим списком под строкой */
    const find = document.querySelector('.find input');
    const res = document.querySelector('.find .find-res');
    const KEYS = window.MAP_KEYS || [];
    const asis = document.body.dataset.asis || '';
    const norm = (s) => String(s).toLowerCase().replace(/ё/g, 'е');
    const escH = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
    const index = KEYS.map((k) => ({ k, name: norm(k.n), all: norm(`${k.n} ${k.w} ${k.s} ${k.k}`) }));
    let hits = [], cur = -1;
    const show = () => {
      const words = norm(find.value).split(/\s+/).filter(Boolean);
      if (!words.length) { res.hidden = true; return; }
      // сначала совпадение в начале имени, потом в имени, потом в смысле; не больше 12
      hits = index.filter((x) => words.every((w) => x.all.includes(w)))
        .map((x) => ({ x, r: x.name.startsWith(words[0]) ? 0 : x.name.includes(words[0]) ? 1 : 2 }))
        .sort((a, b) => a.r - b.r).slice(0, 12).map((h) => h.x.k);
      cur = hits.length ? 0 : -1;
      res.innerHTML = hits.length
        ? hits.map((k, i) => `<a href="${escH(asis + k.u)}" class="${i === cur ? 'on' : ''}"><b>${escH(k.n)}</b>`
          + `<span class="fr-k">${escH(k.k)}${k.s ? ` · ${escH(k.s)}` : ''}</span><span class="fr-w">${escH(k.w)}</span></a>`).join('')
        : '<p class="fr-none">ничего не найдено</p>';
      res.hidden = false;
    };
    const mark = () => res.querySelectorAll('a').forEach((a, i) => a.classList.toggle('on', i === cur));
    if (find && res) {
      find.addEventListener('input', show);
      find.addEventListener('focus', () => { if (find.value) show(); });
      find.addEventListener('keydown', (e) => {
        if (e.key === 'ArrowDown' && hits.length) { e.preventDefault(); cur = (cur + 1) % hits.length; mark(); }
        else if (e.key === 'ArrowUp' && hits.length) { e.preventDefault(); cur = (cur - 1 + hits.length) % hits.length; mark(); }
        else if (e.key === 'Enter' && cur >= 0) { e.preventDefault(); location.href = asis + hits[cur].u; res.hidden = true; }
        else if (e.key === 'Escape') { res.hidden = true; find.blur(); }
      });
      document.addEventListener('click', (e) => { if (!e.target.closest('.find')) res.hidden = true; });
    }
    document.addEventListener('keydown', (e) => {
      if ((e.ctrlKey || e.metaKey) && e.code === 'KeyK' && find) { e.preventDefault(); find.focus(); find.select(); }
    });

    /* 3а. общее меню: открыт один список; щелчок мимо и Esc закрывают */
    const menus = [...document.querySelectorAll('.gnav details')];
    menus.forEach((d) => d.addEventListener('toggle', () => { if (d.open) menus.forEach((o) => { if (o !== d) o.open = false; }); }));
    document.addEventListener('click', (e) => { if (!e.target.closest('.gnav details')) menus.forEach((d) => { d.open = false; }); });
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape') menus.forEach((d) => { d.open = false; }); });

    /* 3б. строка-ссылка: щелчок в любом месте строки — переход; ссылки внутри строки ведут себя как обычно */
    document.querySelectorAll('tr.row-link[data-href]').forEach((tr) => tr.addEventListener('click', (ev) => {
      if (ev.target.closest('a, button, input, summary')) return;
      if (window.getSelection && String(window.getSelection())) return;   // выделяли текст — не переходить
      if (ev.ctrlKey || ev.metaKey) window.open(tr.dataset.href, '_blank'); else location.href = tr.dataset.href;
    }));

    /* 4. сводные таблицы */
    document.querySelectorAll('.ix-tools').forEach((t) => {
      const ix = t.nextElementSibling;
      if (!ix) return;
      t.querySelectorAll('button').forEach((b) => b.addEventListener('click', () => {
        if (b.dataset.ix === 'open') {
          const rows = [...ix.querySelectorAll(':scope > details.ix-r')];
          const open = rows.some((r) => !r.open);
          rows.forEach((r) => { r.open = open; });
          b.textContent = open ? 'свернуть все' : 'раскрыть все';
        } else if (b.dataset.ix === 'pm') {
          const on = ix.classList.toggle('only-pm');
          b.setAttribute('aria-pressed', String(on));
        }
      }));
    });

    /* 5. процесс: пара «строка ↔ стрелка» */
    document.querySelectorAll('[data-a]').forEach((el) => {
      el.addEventListener('mouseenter', () => {
        document.body.classList.add('pairing');
        document.querySelectorAll(`[data-a="${el.dataset.a}"]`).forEach((x) => x.classList.add('on'));
      });
      el.addEventListener('mouseleave', () => {
        document.body.classList.remove('pairing');
        document.querySelectorAll('[data-a].on').forEach((x) => x.classList.remove('on'));
      });
    });

    /* 6. доска */
    document.querySelectorAll('[data-board]').forEach(board);
  });

  function board(box) {
    const data = JSON.parse(box.querySelector('.board-data').textContent);
    const panel = box.closest('[data-board-panel]') || box;
    const svg = box.querySelector('.board-svg');
    const NS = 'http://www.w3.org/2000/svg';
    const CW = 300, RH = 150, W = 220, H = 80;
    const LAYOUT = 'map-board-layout';
    const pos = {};
    const home = () => data.nodes.forEach((n) => { pos[n.id] = { x: n.x, y: n.y }; });
    home();
    try {   // переставленное руками браузер помнит; «Сбросить» возвращает раскладку из project/board.yaml
      const saved = JSON.parse(store.get(LAYOUT, '{}'));
      Object.keys(saved).forEach((id) => { if (pos[id]) pos[id] = saved[id]; });
    } catch (e) { /* без сохранённой раскладки */ }
    const keep = () => store.set(LAYOUT, JSON.stringify(pos));
    let view = { x: -40, y: -40, k: 1 };
    const defs = document.createElementNS(NS, 'defs');
    svg.appendChild(defs);
    const g = document.createElementNS(NS, 'g');
    svg.appendChild(g);
    const el = (tag, attrs, parent) => {
      const e = document.createElementNS(NS, tag);
      Object.entries(attrs).forEach(([k, v]) => e.setAttribute(k, v));
      (parent || g).appendChild(e);
      return e;
    };
    const KIND = { request: 'k-request', external: 'k-external', human: 'k-human', db: 'k-db', redis: 'k-redis', file: 'k-file' };
    Object.entries(KIND).forEach(([k, cls]) => {
      const m = el('marker', { id: `b-${k}`, viewBox: '0 0 10 10', refX: 9, refY: 5, markerWidth: 6, markerHeight: 6, orient: 'auto-start-reverse' }, defs);
      el('path', { d: 'M0,0 L10,5 L0,10 z', class: `m-${cls.slice(2)}` }, m);
    });
    const center = (id) => ({ x: pos[id].x * CW + W / 2, y: pos[id].y * RH + H / 2 });
    const edges = data.edges.filter((e) => pos[e.from] && pos[e.to]).map((e) => {
      const cls = `b-edge ${KIND[e.kind] || 'k-inner'}${e.broken ? ' broken' : ''}`;
      const a = el(e.href ? 'a' : 'g', e.href ? { href: e.href, class: cls } : { class: cls });
      const p = el('path', { 'marker-end': `url(#b-${e.kind})`, 'stroke-width': 2 + Math.min(e.w || 1, 4) * 0.6 }, a);
      const t = el('text', { 'text-anchor': 'middle' }, a);
      t.textContent = e.label || '';
      if (e.title) { const ti = el('title', {}, a); ti.textContent = e.title; }
      return { e, a, p, t };
    });
    const nodes = data.nodes.map((n) => {
      const cls = `b-node k-${n.kind}${n.unplaced ? ' unplaced' : ''}${n.st ? ` st-${n.st}` : ''}`;   // st — судьба узла в «как будет»
      const a = el(n.href ? 'a' : 'g', n.href ? { href: n.href, class: cls } : { class: cls });
      el('rect', { width: W, height: H, rx: n.kind === 'human' ? H / 2 : 3, class: 'box' }, a);   // человек — скруглённый
      const t = el('text', { x: 14, y: 28, class: 't' }, a); t.textContent = n.title;
      if (n.sub) { const s = el('text', { x: 14, y: 49, class: 's' }, a); s.textContent = n.sub; }
      if (n.counts) { const c = el('text', { x: 14, y: 68, class: 'c' }, a); c.textContent = n.counts; }
      if (n.db) {
        el('rect', { x: 10, y: H, width: 18 + n.db.length * 6.6, height: 22, class: 'dbt' }, a);
        const d = el('text', { x: 18, y: H + 15, class: 'dbs' }, a); d.textContent = n.db;
      }
      if (n.pm) {
        el('circle', { cx: W - 4, cy: 4, r: 12, class: 'pmc' }, a);
        const pt = el('text', { x: W - 4, y: 8.5, 'text-anchor': 'middle', class: 'pmt' }, a); pt.textContent = String(n.pm);
      }
      if (n.what || n.stw) { const ti = el('title', {}, a); ti.textContent = [n.stw, n.what].filter(Boolean).join(' — '); }
      return { n, a };
    });
    function edgePath(e) {
      const a = center(e.from), b = center(e.to);
      const dx = b.x - a.x, dy = b.y - a.y;
      const sx = Math.abs(dx) * H > Math.abs(dy) * W ? Math.sign(dx) * W / 2 : dx * (H / 2) / Math.max(Math.abs(dy), 1);
      const sy = Math.abs(dx) * H > Math.abs(dy) * W ? dy * (W / 2) / Math.max(Math.abs(dx), 1) : Math.sign(dy) * H / 2;
      const x1 = a.x + sx, y1 = a.y + sy, x2 = b.x - sx, y2 = b.y - sy;
      return { d: `M${x1},${y1} C${x1 + dx * 0.3},${y1} ${x2 - dx * 0.3},${y2} ${x2},${y2}`, mx: (x1 + x2) / 2, my: (y1 + y2) / 2 - 8 };
    }
    const zoomOf = () => parseFloat(getComputedStyle(root).zoom) || 1;
    const pct = panel.querySelector('[data-b="pct"]');
    function draw() {
      nodes.forEach(({ n, a }) => a.setAttribute('transform', `translate(${pos[n.id].x * CW},${pos[n.id].y * RH})`));
      edges.forEach(({ e, p, t }) => { const r = edgePath(e); p.setAttribute('d', r.d); t.setAttribute('x', r.mx); t.setAttribute('y', r.my); });
      const r = svg.getBoundingClientRect();
      const z = zoomOf();
      svg.setAttribute('viewBox', `${view.x} ${view.y} ${r.width / z / view.k} ${r.height / z / view.k}`);
      box.classList.toggle('zoomed', view.k >= 1.15);   // от 115 % подписи видны у всех линий
      if (pct) pct.textContent = `${Math.round(view.k * 100)} %`;
    }
    function fit() {
      const r = svg.getBoundingClientRect();
      if (!r.width || !r.height) return;
      const z = zoomOf();
      const xs = Object.values(pos).map((p) => p.x * CW), ys = Object.values(pos).map((p) => p.y * RH);
      const w = Math.max(...xs) - Math.min(...xs) + W + 120, h = Math.max(...ys) - Math.min(...ys) + H + 120;
      view.k = Math.min(r.width / z / w, r.height / z / h, 1.4);
      view.x = Math.min(...xs) - 60 - (r.width / z / view.k - w) / 2;
      view.y = Math.min(...ys) - 60 - (r.height / z / view.k - h) / 2;
      draw();
    }
    function zoomAt(k2, cx, cy) {   // cx, cy — точка доски, которая остаётся на месте
      k2 = Math.max(0.3, Math.min(3, k2));
      view.x = cx - (cx - view.x) * view.k / k2; view.y = cy - (cy - view.y) * view.k / k2; view.k = k2;
      draw();
    }
    // сдвиг, масштаб, перетаскивание узла
    let drag = null;
    svg.addEventListener('wheel', (ev) => {
      ev.preventDefault();
      const r = svg.getBoundingClientRect(), z = zoomOf();
      zoomAt(view.k * (ev.deltaY < 0 ? 1.12 : 1 / 1.12), view.x + (ev.clientX - r.left) / z / view.k, view.y + (ev.clientY - r.top) / z / view.k);
    }, { passive: false });
    svg.addEventListener('pointerdown', (ev) => {
      const node = ev.target.closest('.b-node');
      const id = node ? nodes.find((x) => x.a === node).n.id : null;
      drag = { id, sx: ev.clientX, sy: ev.clientY, vx: view.x, vy: view.y, p: id ? { ...pos[id] } : null, moved: false };
      svg.setPointerCapture(ev.pointerId);
      if (!id) svg.classList.add('panning');
    });
    svg.addEventListener('pointermove', (ev) => {
      if (!drag) return;
      const z = zoomOf() * view.k;
      const dx = (ev.clientX - drag.sx) / z, dy = (ev.clientY - drag.sy) / z;
      if (Math.abs(dx) + Math.abs(dy) > 3) drag.moved = true;
      if (drag.id) { pos[drag.id] = { x: Math.round((drag.p.x + dx / CW) * 20) / 20, y: Math.round((drag.p.y + dy / RH) * 20) / 20 }; }
      else { view.x = drag.vx - dx; view.y = drag.vy - dy; }
      draw();
    });
    svg.addEventListener('pointerup', () => {
      svg.classList.remove('panning');
      if (drag && drag.id && drag.moved) keep();
      setTimeout(() => { drag = null; }, 0);
    });
    svg.addEventListener('click', (ev) => { if (drag && drag.moved) ev.preventDefault(); }, true);
    // наведение на узел — только его связи
    const clear = () => {
      box.classList.remove('dim', 'route');
      box.querySelectorAll('.hot').forEach((x) => x.classList.remove('hot'));
      edges.forEach(({ e, t }) => { t.textContent = e.label || ''; });
    };
    nodes.forEach(({ n, a }) => {
      a.addEventListener('mouseenter', () => {
        box.classList.add('dim'); a.classList.add('hot');
        edges.forEach((x) => { if (x.e.from === n.id || x.e.to === n.id) { x.a.classList.add('hot');
          nodes.forEach((y) => { if (y.n.id === x.e.from || y.n.id === x.e.to) y.a.classList.add('hot'); }); } });
      });
      a.addEventListener('mouseleave', clear);
    });
    // путь процесса: наведение на процесс в колонке справа — его рёбра с номерами стрелок, остальное бледнеет
    panel.querySelectorAll('[data-proc]').forEach((li) => {
      li.addEventListener('mouseenter', () => {
        const pairs = (data.routes || {})[li.dataset.proc] || [];
        box.classList.add('route');
        const nums = new Map();
        pairs.forEach(([s, r, num]) => {
          const x = edges.find((y) => (y.e.from === s && y.e.to === r) || (y.e.from === r && y.e.to === s));
          if (x) { x.a.classList.add('hot'); nums.set(x, (nums.get(x) || []).concat(num)); }
          nodes.forEach((y) => { if (y.n.id === s || y.n.id === r) y.a.classList.add('hot'); });
        });
        nums.forEach((list, x) => { x.t.textContent = list.join(' · '); });
      });
      li.addEventListener('mouseleave', clear);
    });
    // виды связей — галочками под доской
    const kinds = () => {
      const off = new Set([...panel.querySelectorAll('input[data-kind]')].filter((i) => !i.checked).map((i) => i.dataset.kind));
      edges.forEach(({ e, a }) => a.classList.toggle('off', off.has(e.kind) || (e.broken && off.has('broken'))));
    };
    panel.querySelectorAll('input[data-kind]').forEach((i) => i.addEventListener('change', kinds));
    // кнопки
    const btn = (name, fn) => { const b = panel.querySelector(`[data-b="${name}"]`); if (b) b.addEventListener('click', fn); };
    const mid = () => { const r = svg.getBoundingClientRect(), z = zoomOf(); return [view.x + r.width / z / view.k / 2, view.y + r.height / z / view.k / 2]; };
    btn('fit', fit);
    btn('in', () => zoomAt(view.k * 1.2, ...mid()));
    btn('out', () => zoomAt(view.k / 1.2, ...mid()));
    btn('full', () => { if (document.fullscreenElement) document.exitFullscreen(); else if (panel.requestFullscreen) panel.requestFullscreen(); });
    document.addEventListener('fullscreenchange', () => setTimeout(fit, 50));
    btn('reset', () => { store.set(LAYOUT, '{}'); home(); fit(); });
    btn('copy', (ev) => {
      const lines = ['nodes:'].concat(Object.keys(pos).map((id) => `  ${/[:/~]/.test(id) ? `'${id}'` : id}: [${pos[id].x}, ${pos[id].y}]`));
      const text = lines.join('\n') + '\n';
      const b = ev.currentTarget;
      (navigator.clipboard ? navigator.clipboard.writeText(text) : Promise.reject()).then(
        () => { b.textContent = 'Скопировано'; setTimeout(() => { b.textContent = 'Скопировать раскладку'; }, 1600); },
        () => { window.prompt('Раскладка для project/board.yaml', text); });
    });
    window.addEventListener('resize', fit);
    fit();
  }
})();
