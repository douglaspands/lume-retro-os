/* lume-launcher · motor de UI do protótipo.
   Não conhece nenhum tema, nenhum dado e nenhuma ferramenta do sistema: só usa as interfaces de
   Lume.themes, Lume.data, Lume.i18n e Lume.system. Em um app real isto seria Rust + SDL2.
   Princípios mantidos de propósito:
   - renderização por evento (sem laço de animação; só redesenha quando há input),
   - só as linhas visíveis da grade existem no DOM,
   - o menu Sistema só amostra enquanto está aberto,
   - layout em "em": independente de resolução. */
(function () {
  'use strict';
  const { themes, data, i18n, system, files } = window.Lume;
  const CONSOLES = data.CONSOLES, gamesOf = data.gamesOf, art = data.art;
  const LANGS = i18n.langs;
  const NETS = system.wifi.networks, DEVS = system.bt.devices;

  /* ------------------------------------------------------------ estado e preferências */
  const load = (k, d) => { try { const v = localStorage.getItem('lume.' + k); return v === null ? d : JSON.parse(v); } catch (e) { return d; } };
  const save = (k, v) => { try { localStorage.setItem('lume.' + k, JSON.stringify(v)); } catch (e) { /* segue sem persistir */ } };

  const P = { lang: load('lang', 'pt-BR'), vol: load('vol', 60), bri: load('bri', 80) };
  const favs = new Set(load('favs', []));
  /* opções de emulador/core, aspecto e shader em 3 camadas, da mais específica para a mais geral:
       jogo (GOV)  →  console (CDEF)  →  padrão do sistema (1º core da lista).
     O jogo só guarda o que foi mudado nele; o resto herda do console. */
  const GOV = load('gov', {});                       // { idDoJogo: { core?, aspect?, shader? } }
  const CDEF = load('cdef', {});                     // { idDoConsole: { core?, aspect?, shader? } }
  const ASPECTS = ['core', '4:3'];
  const SHADERS = ['none', 'scanlines', 'crt', 'lcd', 'sharp'];   // lista de exemplo: no app real vem dos shaders instalados no RetroArch
  const urlTheme = new URLSearchParams(location.search).get('tema');
  const env = { theme: urlTheme || load('theme', 'material-escuro'), wifi: load('dwifi', true), bt: load('dbt', true), lite: load('lite', false), res: load('res', '640x480'), demo: load('demo', true), real: load('real', false), ppi: load('ppi', 96) };
  const S = { screen: 'dock', dock: 0, g: 0, top: 0, q: '', kb: null, jt: 0, jk: 0, s: 0, stop: 0, view: false, vlist: [], vi: 0, fp: [], fi: 0, ftop: 0, text: false, off: false, menu: null, si: 0, sub: null, wifiConn: 0, btConn: [], sys: null, stopSys: null, launching: false, th: null };
  const QS = new URLSearchParams(location.search);
  if (['pt-BR', 'en', 'es'].includes(QS.get('idioma'))) P.lang = QS.get('idioma');   // review override, not saved
  if (/^\d+x\d+$/.test(QS.get('res') || '')) env.res = QS.get('res');
  const t = k => i18n.t(P.lang, k);
  /* device-fixes 4.1 · D12 review toggle: ?limite=off drops the red dot, the "restart learning" row and the limit in the failure
     line (the whole brightness-limit feature in one flag, easy to remove if the E4 timing fix makes it unnecessary);
     ?limite=none shows a device without a limit; ?limite=<1-10> sets the limit level. Default: limit 7 (GA36). */
  const BL = { on: QS.get('limite') !== 'off', limit: 7, stick: false };
  if (QS.get('limite') === 'none') BL.limit = null;
  else if (/^([1-9]|10)$/.test(QS.get('limite') || '')) BL.limit = +QS.get('limite');
  /* device-fixes 4.1 · D5 card panel (simulated; on the device it reads statvfs, last-trim and last-check, keyed by boot number) */
  const CARD = { boot: 152, free: '58,4 GB', trim: 150, check: 140, run: 'idle', out: 'ok', bytes: '1,2 GB', pending: false };
  if (['idle', 'running', 'ok', 'fail'].includes(QS.get('cartao'))) { CARD.run = QS.get('cartao'); if (CARD.run === 'fail') CARD.out = 'fail'; }
  /* save states válidos para o jogo COM um core: save state é específico do core, então trocar o emulador troca a lista.
     Saves reais só valem para o core a que pertencem; jogos sem nenhum save real ganham inventados (por core) se a opção estiver ligada. */
  const savesOf = (g, core) => { const real = data.savesFor(g, core); return real.length || g.saves.length ? real : (env.demo ? data.demoSaves(g, core) : []); };
  const savesElse = (g, core) => data.consoleOf(g.cid).cores.map(data.coreName).filter(c => c !== core).reduce((n, c) => n + savesOf(g, c).length, 0);
  /* Dock: Favoritos, consoles, Arquivos, Capturas (imagens salvas pelo RetroArch) e, por último, Configurações */
  const dockItems = () => [{ id: 'fav', kind: 'fav' }, ...CONSOLES.map(c => ({ id: c.id, kind: 'console', c })),
    ...(files.available ? [{ id: 'files', kind: 'files' }] : []), { id: 'shots', kind: 'shots' }, { id: 'set', kind: 'set' }];

  /* ------------------------------------------------------------ DOM base */
  /* simulated; on the device it comes from /sys/class/power_supply (capacity + status).
     Force it for review: ?bat=5&carga=charging|discharging|full&idioma=en|pt-BR|es&tema=<id>, or the toolbar controls. */
  const BAT = { p: 82, st: 'discharging', warned: false };
  const WARN_AT = 5;                                // low-battery limit (game-governor D7), same as the service
  if (QS.has('bat')) BAT.p = Math.max(0, Math.min(100, parseInt(QS.get('bat'), 10) || 0));
  if (['charging', 'discharging', 'full'].includes(QS.get('carga'))) BAT.st = QS.get('carga');
  const bar3 = '<div class="topbar"><span class="net"></span><span class="r"><span class="batt"></span></span></div>';
  const FOLDER_PATH = '<path d="M3 6.5A1.5 1.5 0 0 1 4.5 5H9l2 2.5h8.5A1.5 1.5 0 0 1 21 9v9.5a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 18.5z"';
  const ICON_FOLDER = `<svg class="gi" viewBox="0 0 24 24" aria-hidden="true">${FOLDER_PATH} fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/></svg>`;
  const DOC_PATH = '<path d="M6 3h8l4 4v14H6z" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/>';
  const ICON_WIFI = '<svg viewBox="0 0 20 14" aria-label="Wi-Fi"><path d="M1.5 5a12 12 0 0 1 17 0M4.5 8a8 8 0 0 1 11 0M7.5 11a4 4 0 0 1 5 0" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/><circle cx="10" cy="12.6" r="1.2" fill="currentColor"/></svg>';
  /* bateria na horizontal: contorno + ponta + preenchimento proporcional ao nível; tudo em currentColor */
  /* charge mark: a bolt inside the body, filled with the text colour and haloed with the theme background
     (paint-order stroke), so it reads over the filled part and over the empty part in light and dark themes.
     It lives inside the icon, so the icon and the percentage text keep their width. 'full' has no bolt. */
  const BOLT = '<path class="bolt" d="M15.6 2.6 10.4 7.6h3.1l-1 3.8 5.2-5.2h-3.2z" fill="currentColor" stroke="var(--bg)" stroke-width="1.1" stroke-linejoin="round" paint-order="stroke"/>';
  const battHtml = (p, st) => `<svg viewBox="0 0 30 14" aria-hidden="true"><rect x="1" y="1" width="25" height="12" rx="2.5" fill="none" stroke="currentColor" stroke-width="1.6"/><rect x="27" y="4.5" width="2" height="5" rx="1" fill="currentColor"/><rect x="3.5" y="3.5" width="${(20 * p / 100).toFixed(1)}" height="7" rx="1" fill="currentColor"/>${st === 'charging' ? BOLT : ''}</svg><span>${p}%</span>`;
  const ICON_SHOTS = '<svg class="gi" viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="4" width="18" height="16" rx="2.5" fill="none" stroke="currentColor" stroke-width="1.8"/><circle cx="9" cy="10" r="1.8" fill="currentColor"/><path d="M4 18l5.5-5.5 3.5 3.5 3-3L20 17" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round" stroke-linecap="round"/></svg>';
  document.title = 'lume-launcher · protótipo';
  document.getElementById('app').innerHTML = `
    <div id="tools">
      <b style="color:#fff;letter-spacing:.04em">lume-launcher</b>
      <label>Tema <select id="theme"></select></label>
      <label title="Janela: a interface se ajusta sozinha ao tamanho da janela do navegador">Tela <select id="res"><option value="auto">Janela (responsivo)</option><option>640x480</option><option>480x320</option><option>720x720</option><option>854x480</option><option>1280x720</option></select></label>
      <label><input type="checkbox" id="dwifi"> Dongle Wi-Fi</label>
      <label><input type="checkbox" id="dbt"> Dongle Bluetooth</label>
      <label title="Battery review: level, state, and the low-battery warning (also ?bat=5&carga=charging&idioma=en)">Bateria <input type="number" id="batp" min="0" max="100"> <select id="bats"><option value="discharging">descarregando</option><option value="charging">carregando</option><option value="full">cheia</option></select> <button id="batw" type="button">Aviso 5%</button></label>
      <label title="Cartão (4.1): estado do 'Otimizar agora'. Também ?cartao=idle|running|ok|fail">Cartão <select id="cardst"><option value="idle">ocioso</option><option value="running">otimizando</option><option value="ok">ok (bytes)</option><option value="fail">falha</option></select></label>
      <label title="Brilho (D12, depende da revisão pós-E4): liga/desliga o pontinho vermelho, o limite e a linha Recomeçar. Também ?limite=off|none|1-10"><input type="checkbox" id="d12"> Limite de brilho (D12)</label>
      <label title="Atalhos F2/F3 (Fn+Volume) e F4 (Fn+Select)"><button id="fnup" type="button">Fn+Vol ▲</button> <button id="fndn" type="button">Fn+Vol ▼</button> <button id="fnrep" type="button">Fn+Select</button></label>
      <label title="Inventa save states (com miniatura) em alguns jogos que não têm, para avaliar a tela"><input type="checkbox" id="demo"> Save states de demonstração</label>
      <label title="Mostra a tela no tamanho físico aproximado de 3,5 polegadas, para avaliar legibilidade"><input type="checkbox" id="real"> Tamanho real 3,5″</label>
      <label title="Densidade de pixels do seu monitor (ex.: 24″ Full HD ≈ 92, 27″ QHD ≈ 109)">ppi do monitor <input type="number" id="ppi" min="50" max="400"></label>
    </div>
    <div id="themedesc"></div>
    <div id="fit"><div id="box" style="position:relative">
      <div id="stage">
        <div id="bgfx"></div>
        <div class="screen on" id="s-dock">${bar3}
          <div id="dock-area"><div id="dock"></div><div id="dock-label"><h1></h1><p></p></div></div>
          <div class="hints"></div></div>
        <div class="screen" id="s-games"><div class="ghead"></div><div id="grid"></div><div id="gtitle"></div><div class="hints"></div></div>
        <div class="screen" id="s-set"><div class="ghead"></div><div class="settings"><div class="slist"></div><div class="spanel"></div></div><div class="hints"></div></div>
        <div class="screen" id="s-shots"><div class="ghead"></div><div id="sgrid"></div><div id="stitle"></div><div class="hints"></div></div>
        <div class="screen" id="s-files"><div class="ghead"></div><div id="flist"></div><div class="hints"></div></div>
        <div id="o-view"></div>
        <div id="o-text"></div>
        <div id="o-kb"></div>
        <div class="overlay" id="o-menu"><div class="sheet"></div></div>
        <div id="o-edge"></div>
        <div id="toast"></div><div id="launch"></div><div id="dim"></div>
      </div>
    </div></div>
    <div id="help">Teclado: ←→↑↓ navegam · Enter/Z = A · Esc/Backspace/X = B · PgUp/PgDn (ou L1/R1) = página · Y = opções do console · / = buscar (lista de jogos) · T = próximo tema · F2/F3 = Fn+Volume ▲▼ · F4 = Fn+Select (relato da falha de tela) · ?tela=card|card-act|card-running|card-ok|card-fail|card-check|sleep|edge|edge-nolimit|report|bri|bri-act|reset</div>`;
  const $ = (s, r) => (r || document).querySelector(s);
  const stage = $('#stage'), box = $('#box');
  const cssv = n => getComputedStyle(stage).getPropertyValue(n).trim();

  /* ------------------------------------------------------------ tema, resolução, brilho */
  function applyTheme() {
    if (!themes.list().some(x => x.id === env.theme)) env.theme = themes.list()[0].id;
    S.th = themes.apply(stage, env.theme); syncGrid(); buildDock();       // o conjunto de logos (branco/colorido) vem do tema
    const lite = env.lite || !!(S.th.features && S.th.features.lite);
    stage.classList.toggle('lite', lite);
    // os valores do tema ficam em style inline e vencem a regra .lite do CSS: no modo lite, fixa sem animação e sem desfoque também aqui
    if (lite) { stage.style.setProperty('--t', '0s'); stage.style.setProperty('--blur', 'none'); }
    $('#theme').value = env.theme; $('#themedesc').textContent = S.th.description;
    save('theme', env.theme); renderAll();
  }
  function cycleTheme() {
    const l = themes.list(), i = l.findIndex(x => x.id === env.theme);
    env.theme = l[(i + 1) % l.length].id; applyTheme();
  }
  function applyRes() {
    // 'auto': a tela ocupa a janela e o layout se reorganiza sozinho (colunas, linhas, ícones visíveis) conforme o tamanho e a proporção
    let w, h, s;
    if (env.res === 'auto') { w = Math.max(280, Math.floor(innerWidth - 32)); h = Math.max(220, Math.floor(innerHeight - 150)); }
    else [w, h] = env.res.split('x').map(Number);
    stage.style.width = w + 'px'; stage.style.height = h + 'px';
    stage.style.fontSize = (Math.min(w / 640, h / 480) * 16) + 'px';     // a escala vem da menor dimensão, para nada estourar
    if (env.res === 'auto') s = 1;
    else if (env.real) { const inch = 3.5 * w / Math.hypot(w, h); s = (inch * env.ppi / (window.devicePixelRatio || 1)) / w; }   // largura física de uma tela de 3,5″
    else s = Math.min((innerWidth - 32) / w, (innerHeight - 150) / h, 1.6);
    stage.style.position = 'absolute'; stage.style.left = '0'; stage.style.top = '0';
    stage.style.transformOrigin = '0 0'; stage.style.transform = `scale(${s})`;
    box.style.width = (w * s) + 'px'; box.style.height = (h * s) + 'px';
    renderAll();
  }
  const applyBri = () => { $('#dim').style.opacity = String((1 - P.bri / 100) * 0.75); };

  /* ------------------------------------------------------------ helpers */
  /* indicadores de estado (sem relógio: estes aparelhos não guardam a hora). Bateria sempre; Wi-Fi/BT só quando conectados */
  function status() {
    document.querySelectorAll('.batt').forEach(e => (e.innerHTML = battHtml(BAT.p, BAT.st)));
    const net = (env.wifi && S.wifiConn >= 0 ? ICON_WIFI : '') + (env.bt && S.btConn.length ? '<span>BT</span>' : '');
    document.querySelectorAll('.net').forEach(e => (e.innerHTML = net));
  }
  /* low-battery warning: the theme's short toast, once per discharge at or below WARN_AT (re-armed by charging or a higher level) */
  function checkBattery(force) {
    if (BAT.st !== 'discharging' || BAT.p > WARN_AT) { BAT.warned = false; if (!force) return; }
    else if (BAT.warned && !force) return;
    BAT.warned = true; toast(t('lowbatt') + ' ' + BAT.p + '%', 4000);
  }
  const hints = (el, items) => { el.innerHTML = items.map(([k, v]) => `<span><b${/[◀▶▲▼]/.test(k) ? ' class="nav"' : ''}>${k}</b>${v}</span>`).join(''); };   // setas ganham a classe .nav
  let toastT;
  function toast(msg, ms) { const e = $('#toast'); e.textContent = msg; e.classList.add('on'); clearTimeout(toastT); toastT = setTimeout(() => e.classList.remove('on'), ms || 1600); }
  function show(name) {
    S.screen = name;
    ['dock', 'games', 'set', 'shots', 'files'].forEach(n => $('#s-' + n).classList.toggle('on', n === name));
    if (name !== 'set') stopSys();
    status();
  }
  function renderAll() {
    renderDock();
    if (S.screen === 'games') renderGames();
    if (S.screen === 'shots') renderShots();
    if (S.screen === 'files') renderFiles();
    if (S.screen === 'set') renderSettings();
    if (S.menu) renderMenu();
  }

  /* ------------------------------------------------------------ Dock (rotação infinita) */
  function buildDock() {
    const dock = $('#dock'); dock.innerHTML = '';
    dockItems().forEach(it => {
      const el = document.createElement('div'); el.className = 'ditem';
      const set = (S.th && S.th.tokens['logo-set']) || 'white';
      if (it.kind === 'fav') el.innerHTML = '<div><span class="glyph">★</span></div>';
      else if (it.kind === 'set') el.innerHTML = '<div><span class="glyph">⚙</span></div>';
      else if (it.kind === 'shots') el.innerHTML = `<div>${ICON_SHOTS}</div>`;
      else if (it.kind === 'files') el.innerHTML = `<div>${ICON_FOLDER}</div>`;
      else {
        // logo oficial da marca (SVG copiado do tema de ES do usuário); sem logo, cai na sigla
        el.innerHTML = it.c.logo ? `<div class="lg"><img class="logo" alt="${it.c.abbr}" src="assets/logos/${set}/${it.c.id}.svg"></div>` : `<div>${it.c.abbr}</div>`;
        el.style.setProperty('--h', it.c.hue);
      }
      if (it.kind !== 'console') el.style.setProperty('--h', it.kind === 'fav' ? 45 : 210);
      dock.appendChild(el);
    });
  }
  function renderDock() {
    const els = $('#dock').children, N = els.length; if (!N) return;
    /* ampliação estilo macOS: o ícone em foco cresce, os vizinhos crescem menos (gaussiana) e empurram os demais;
       quantos ícones aparecem depende da largura da tela (em "em"), então se adapta a qualquer tamanho */
    const fs = parseFloat(getComputedStyle(stage).fontSize) || 16, num = n => parseFloat(cssv(n));
    const icon = num('--icon') || 6, gap = num('--dock-gap') || .6, peak = num('--mag-peak') || 1.5, base = num('--mag-base') || .8, sig = num('--mag-spread') || .8;
    const half = (stage.clientWidth || 640) / fs / 2 - .1;           // metade da largura útil (quase a tela toda: sem pontinhos, o Dock usa o espaço)
    const sc = d => base + (peak - base) * Math.exp(-(d * d) / (2 * sig * sig));
    const maxD = Math.min(Math.floor(N / 2), 8), pos = [0];
    for (let k = 1; k <= maxD; k++) pos[k] = pos[k - 1] + (icon * sc(k - 1) + icon * sc(k)) / 2 + gap;
    for (let i = 0; i < N; i++) {
      const el = els[i]; let d = i - S.dock;
      if (d > N / 2) d -= N; if (d < -N / 2) d += N;              // caminho mais curto no anel
      const ad = Math.abs(d), k = Math.min(ad, maxD), s = sc(ad);
      const hidden = ad > maxD || pos[k] + icon * sc(k) / 2 > half;
      // sem animar quando o item entra ou sai de vista (atravessa a borda do anel)
      el.classList.toggle('nt', hidden || !!el._h); el._h = hidden;
      const x = Math.sign(d) * pos[k] * fs, y = -(s - base) * icon * fs * .15;      // o foco também sobe um pouco
      el.style.transform = `translate(${x}px, ${y}px) scale(${s})`;
      el.style.opacity = hidden ? 0 : Math.max(.5, 1 - ad * .16);
      el.style.zIndex = String(20 - ad);
      el.classList.toggle('sel', d === 0);
    }
    const it = dockItems()[S.dock]; let name, sub;
    if (it.kind === 'fav') { name = t('fav'); sub = favList().length + ' ' + t('games'); }
    else if (it.kind === 'set') { name = t('set'); sub = t('setsub'); }
    else if (it.kind === 'shots') { name = t('shots'); sub = data.shots.length + ' ' + t('imgs'); }
    else if (it.kind === 'files') { name = t('files'); sub = '/' + files.rootName; }
    else { name = it.c.sub; sub = gamesOf(it.id).length + ' ' + t('games'); }
    $('#dock-label h1').textContent = name; $('#dock-label p').textContent = sub;
    hints($('#s-dock .hints'), [['◀▶', t('move')], ['A', t('sel')]]);
    status();
  }

  /* ------------------------------------------------------------ Grade de jogos */
  let COLS = 4, ROWS = 2;
  /* layout responsivo: colunas, linhas e itens visíveis saem do tamanho real da tela (em "em") e não de números fixos.
     Base: a grade do tema (cols x rows) vale para 40em x 30em (640x480); telas mais largas ganham colunas, mais altas ganham linhas. */
  const syncGrid = () => {
    const fs = parseFloat(getComputedStyle(stage).fontSize) || 16, W = (stage.clientWidth || 640) / fs, H = (stage.clientHeight || 480) / fs;
    const tk = S.th ? S.th.tokens : {}, bc = +tk.cols || 4, br = +tk.rows || 2;
    COLS = Math.max(3, Math.min(6, Math.round(bc * W / 40))); ROWS = H >= 38 ? br + 1 : br;
    SC = W >= 48 ? 3 : 2; SR = H >= 38 ? 3 : 2; FR = Math.max(4, Math.min(12, Math.floor((H - 8.5) / 2.55)));
    stage.style.setProperty('--cols', COLS); stage.style.setProperty('--rows', ROWS); stage.style.setProperty('--scols', SC);
  };
  const favList = () => { const out = []; CONSOLES.forEach(c => gamesOf(c.id).forEach(g => { if (favs.has(g.id)) out.push(g); })); return out; };
  /* busca: filtra pelo nome sem diferenciar maiúsculas nem acentos; todas as palavras digitadas precisam aparecer */
  const normTxt = s => String(s).normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
  function filterGames(list, text) {
    const q = normTxt(text || '').trim(); if (!q) return list;
    const words = q.split(/\s+/);
    return list.filter(g => { const n = g._n || (g._n = normTxt(g.title)); return words.every(w => n.includes(w)); });
  }
  let curKey = '', curList = [];
  function curGames() {                                // lista exibida: o console (ou Favoritos) já filtrado pela busca; em cache, pois é chamada a cada tecla
    const it = dockItems()[S.dock], key = it.id + '|' + normTxt(S.q) + '|' + favs.size + '|' + (env.demo ? 1 : 0);
    if (key !== curKey) { curKey = key; curList = filterGames(it.kind === 'fav' ? favList() : gamesOf(it.id), S.q); }
    return curList;
  }
  function openGames() { S.g = 0; S.top = 0; S.q = ''; show('games'); renderGames(); }
  function renderGames() {
    syncGrid();
    const it = dockItems()[S.dock], list = curGames();
    $('#s-games .ghead').innerHTML = `<span class="hl">${it.kind === 'fav' ? t('fav') : it.c.sub}${S.q ? ' · “' + esc(S.q) + '”' : ''}</span><span class="r"><span>${list.length ? (S.g + 1) + ' / ' + list.length : '0'}</span><span class="batt"></span></span>`;
    const grid = $('#grid');
    if (!list.length) { grid.style.display = 'none'; $('#gtitle').textContent = ''; ensureEmpty(true); }
    else {
      ensureEmpty(false); grid.style.display = 'grid';
      const row = Math.floor(S.g / COLS);
      if (row < S.top) S.top = row; if (row > S.top + ROWS - 1) S.top = row - ROWS + 1;
      let html = '';
      for (let i = S.top * COLS; i < Math.min(list.length, (S.top + ROWS) * COLS); i++) {   // só a janela visível
        const g = list[i];
        html += `<div class="tile${i === S.g ? ' sel' : ''}"><img alt="" decoding="async" data-i="${i}" src="${art(g)}">${favs.has(g.id) ? '<span class="fav">★</span>' : ''}${hasOverride(g) ? '<span class="ovr">⚙</span>' : ''}</div>`;   // ⚙ = jogo com emulador/opção própria
      }
      grid.innerHTML = html; $('#gtitle').textContent = list[S.g].title;
    }
    hints($('#s-games .hints'), [['A', t('sel')], ['X', t('search')], ...(it.kind === 'console' ? [['Y', t('console')]] : []), ['B', t('back')]]);
    status();
  }
  function ensureEmpty(on) {
    let e = $('#empty');
    if (on) { if (!e) { e = document.createElement('div'); e.id = 'empty'; $('#s-games').insertBefore(e, $('#gtitle')); } e.textContent = t(S.q ? 'noresults' : 'nofavs'); e.style.whiteSpace = 'pre-line'; }
    else if (e) e.remove();
  }

  /* ------------------------------------------------------------ Busca (teclado na tela) */
  const KB_ROWS = [['1', '2', '3', '4', '5', '6', '7', '8', '9', '0'], 'QWERTYUIOP'.split(''), 'ASDFGHJKL'.split(''), 'ZXCVBNM'.split(''), ['space', 'back', 'clear', 'ok']];
  const kbLabel = k => (k === 'space' ? t('keySpace') : k === 'back' ? '⌫' : k === 'clear' ? t('keyClear') : k === 'ok' ? 'OK' : k);
  const kbBase = () => { const it = dockItems()[S.dock]; return it.kind === 'fav' ? favList() : gamesOf(it.id); };
  function openSearch() { S.kb = { text: S.q || '', r: 1, c: 0 }; renderKb(); $('#o-kb').classList.add('on'); }
  function renderKb() {
    const kb = S.kb, n = filterGames(kbBase(), kb.text).length;                  // contagem ao vivo, a cada letra
    $('#o-kb').innerHTML = `<div class="kq"><span class="kt">${esc(kb.text)}<i class="cur"></i></span><span class="kc">${n} ${t('games')}</span></div><div class="kk">` +
      KB_ROWS.map((row, r) => `<div class="kr">${row.map((k, c) => `<span class="key${k.length > 1 ? ' w' : ''}${r === kb.r && c === kb.c ? ' sel' : ''}">${kbLabel(k)}</span>`).join('')}</div>`).join('') + '</div><div class="hints"></div>';
    hints($('#o-kb .hints'), [['A', t('sel')], ['B', 'OK']]);
  }
  function closeSearch() { S.q = S.kb.text.trim(); S.kb = null; $('#o-kb').classList.remove('on'); S.g = 0; S.top = 0; renderGames(); }
  const kbType = ch => { S.kb.text = (S.kb.text + ch).slice(0, 24); };
  function kbKey(k) {                                  // D-pad move pelas teclas, A digita, B fecha e aplica a busca
    const kb = S.kb;
    if (k === 'B') return closeSearch();
    if (k === 'L') kb.c = Math.max(0, kb.c - 1);
    else if (k === 'R') kb.c = Math.min(KB_ROWS[kb.r].length - 1, kb.c + 1);
    else if (k === 'U') { kb.r = Math.max(0, kb.r - 1); kb.c = Math.min(kb.c, KB_ROWS[kb.r].length - 1); }
    else if (k === 'D') { kb.r = Math.min(KB_ROWS.length - 1, kb.r + 1); kb.c = Math.min(kb.c, KB_ROWS[kb.r].length - 1); }
    else if (k === 'A') {
      const key = KB_ROWS[kb.r][kb.c];
      if (key === 'ok') return closeSearch();
      if (key === 'back') kb.text = kb.text.slice(0, -1); else if (key === 'clear') kb.text = ''; else kbType(key === 'space' ? ' ' : key);
    }
    renderKb();
  }
  /* L1/R1: salto proporcional ao tamanho da lista (cruza ~1000 jogos em poucos toques) e que acelera se o botão for repetido */
  function jumpSize(n) {
    const base = Math.max(COLS * ROWS, Math.ceil(n / 16 / COLS) * COLS), now = Date.now();
    S.jk = now - S.jt < 380 ? Math.min(S.jk + 1, 3) : 0; S.jt = now;
    return base * (1 + S.jk);
  }

  /* ------------------------------------------------------------ Menu do jogo */
  const coresOfId = cid => data.consoleOf(cid).cores.map(data.coreName);
  const valuesFor = (cid, key) => key === 'core' ? coresOfId(cid) : key === 'aspect' ? ASPECTS : SHADERS;
  const sysDefault = (cid, key) => key === 'core' ? coresOfId(cid)[0] : key === 'aspect' ? 'core' : 'none';
  const optLabel = (k, v) => k === 'core' ? v : k === 'aspect' ? (v === 'core' ? t('coreAspect') : '4:3') : t('sh_' + v);
  const hasOverride = g => !!GOV[g.id] && Object.keys(GOV[g.id]).length > 0;
  function eff(g) {                                    // valor efetivo de cada opção e de onde ele vem ('game' | 'console' | 'sys')
    const out = { src: {} };
    ['core', 'aspect', 'shader'].forEach(k => {
      const vals = valuesFor(g.cid, k), go = (GOV[g.id] || {})[k], cd = (CDEF[g.cid] || {})[k];
      if (go && vals.includes(go)) { out[k] = go; out.src[k] = 'game'; }
      else if (cd && vals.includes(cd)) { out[k] = cd; out.src[k] = 'console'; }
      else { out[k] = sysDefault(g.cid, k); out.src[k] = 'sys'; }
    });
    return out;
  }
  function cycleGame(g, key, dir) {                    // lista do jogo: [Padrão, ...valores]; "Padrão" apaga o override do jogo
    const vals = ['', ...valuesFor(g.cid, key)], cur = (GOV[g.id] || {})[key] || '';
    const nxt = vals[(vals.indexOf(cur) + dir + vals.length) % vals.length];
    const o = Object.assign({}, GOV[g.id]); if (nxt) o[key] = nxt; else delete o[key];
    if (Object.keys(o).length) GOV[g.id] = o; else delete GOV[g.id];
    save('gov', GOV);
  }
  function cycleConsole(cid, key, dir) {               // padrão do console: só valores; voltar ao padrão do sistema apaga a chave
    const vals = valuesFor(cid, key), cur = eff({ id: '', cid })[key];
    const nxt = vals[(vals.indexOf(cur) + dir + vals.length) % vals.length];
    const o = Object.assign({}, CDEF[cid]); if (nxt === sysDefault(cid, key)) delete o[key]; else o[key] = nxt;
    if (Object.keys(o).length) CDEF[cid] = o; else delete CDEF[cid];
    save('cdef', CDEF);
  }
  const cycleOpt = (m, key, dir) => (m.kind === 'console' ? cycleConsole(m.cid, key, dir) : cycleGame(m.g, key, dir));
  function openConsoleMenu() {                         // Y na grade de jogos: opções padrão do console inteiro
    const it = dockItems()[S.dock]; if (it.kind !== 'console') return;
    S.menu = { kind: 'console', cid: it.id, i: 0 }; renderMenu(); $('#o-menu').classList.add('on');
  }
  function openMenu() { const g = curGames()[S.g]; if (!g) return; S.menu = { g, i: 0, slots: false }; renderMenu(); $('#o-menu').classList.add('on'); }
  function closeMenu() { S.menu = null; $('#o-menu').classList.remove('on'); if (S.screen === 'games') renderGames(); else if (S.screen === 'set') renderSettings(); }   // redesenha: o selo de "opção própria" pode ter mudado
  const slotName = k => (k === 'a' ? t('auto') : t('slot') + ' ' + k);
  const rowsHtml = (opts, cur) => opts.map((o, i) =>
    `<div class="opt${i === cur ? ' sel' : ''}${o.dis ? ' dis' : ''}"><span class="l">${o.th ? `<img class="sth" alt="" src="${o.th}">` : ''}<span class="lt">${o.l}</span></span><span class="v${o.ovr ? ' ov' : ''}">${o.cyc && i === cur ? '‹ ' + o.v + ' ›' : (o.v || '')}</span></div>`).join('');
  function renderMenu() {
    const m = S.menu;
    if (m.kind === 'power' || m.kind === 'reset') {   // regra de toda confirmação (2026-11-17): a afirmativa em cima, Cancelar embaixo e com o foco; D8: só cima/baixo movem o foco
      const rs = m.kind === 'reset';                  // 'reset' = Recomeçar o aprendizado (4.1, D12)
      m.opts = [{ k: 'yes', l: t(rs ? 'yesNo' : 'yes') }, { k: 'no', l: t('no') }];
      $('#o-menu .sheet').innerHTML = `<div class="sbody"><h2>${t(rs ? 'resetLearn' : 'power')}</h2><div class="sub">${t(rs ? 'resetAsk' : 'powerAsk')}</div>` +
        m.opts.map((o, i) => `<div class="opt${i === m.i ? ' sel' : ''}"><span class="l">${o.l}</span></div>`).join('') + '</div>';
      return;
    }
    if (m.kind === 'console') {                        // padrão do console: vale para todo jogo que não tem opção própria
      const c = data.consoleOf(m.cid), o = eff({ id: '', cid: m.cid });
      const n = gamesOf(m.cid).filter(hasOverride).length, lset = (S.th && S.th.tokens['logo-set']) || 'white';
      const row = k => ({ k, l: t(k === 'core' ? 'emu' : k), v: optLabel(k, o[k]), cyc: true, ovr: o.src[k] === 'console' });
      m.opts = [row('core'), row('aspect'), ...(data.isRetroarch(o.core) ? [row('shader')] : []), { k: 'clear', l: t('clearGames'), v: String(n), dis: n === 0 }];
      m.i = Math.min(m.i, m.opts.length - 1);
      const mark = c.logo ? `<img class="big clogo" alt="${esc(c.abbr)}" src="assets/logos/${lset}/${c.id}.svg">` : `<b>${esc(c.abbr)}</b>`;
      $('#o-menu .sheet').innerHTML = `<div class="cover">${mark}</div><div class="sbody"><h2>${esc(c.sub)}</h2><div class="sub">${t('consoleOpts')}</div>` + rowsHtml(m.opts, m.i) + '</div>';
      return;
    }
    const g = m.g, o = eff(g); let opts;
    // cada opção mostra o valor do jogo (destacado) ou "Padrão (valor herdado do console/sistema)"
    const optRow = k => ({ k, l: t(k === 'core' ? 'emu' : k), v: o.src[k] === 'game' ? optLabel(k, o[k]) : t('inherit') + ' (' + optLabel(k, o[k]) + ')', cyc: true, ovr: o.src[k] === 'game' });
    if (!m.slots) {
      const has = savesOf(g, o.core).length > 0, other = has ? 0 : savesElse(g, o.core);   // save state é do core: avisa se existem em outro
      opts = [{ k: 'play', l: t('play') },
              { k: 'state', l: t('state'), v: has ? '' : (other ? other + ' ' + t('otherCore') : t('nosave')), dis: !has },
              optRow('core'), optRow('aspect'),
              ...(data.isRetroarch(o.core) ? [optRow('shader')] : []),             // shader só existe em core do RetroArch
              { k: 'fav', l: favs.has(g.id) ? t('favDel') : t('favAdd'), v: favs.has(g.id) ? '★' : '☆' }];
    } else opts = savesOf(g, o.core).map(s => ({ k: 'slot:' + s.k, l: slotName(s.k), v: s.d, th: s.th }));
    m.opts = opts; m.i = Math.min(m.i, opts.length - 1);
    // a capa do jogo fica em destaque à esquerda; as opções à direita
    $('#o-menu .sheet').innerHTML = `<div class="cover"><img class="big" alt="" src="${art(g)}"></div><div class="sbody"><h2>${esc(g.title)}</h2><div class="sub">${g.abbr}${m.slots ? ' · ' + o.core + (savesOf(g, o.core).some(s => s.demo) ? ' · demo' : '') : ''}</div>` + rowsHtml(opts, m.i) + '</div>';
  }
  function menuKey(k) {
    const m = S.menu;
    if (k === 'U') { m.i = (m.i + m.opts.length - 1) % m.opts.length; renderMenu(); }
    else if (k === 'D') { m.i = (m.i + 1) % m.opts.length; renderMenu(); }
    else if ((k === 'L' || k === 'R') && m.opts[m.i] && m.opts[m.i].cyc) { cycleOpt(m, m.opts[m.i].k, k === 'R' ? 1 : -1); renderMenu(); }
    else if (k === 'B') { if (m.slots) { m.slots = false; m.i = 0; renderMenu(); } else closeMenu(); }
    else if (k === 'A') {
      const o = m.opts[m.i]; if (o.dis) return;
      if (m.kind === 'power') { closeMenu(); if (o.k === 'yes') shutdown(); return; }
      if (m.kind === 'reset') { closeMenu(); if (o.k === 'yes') resetLearning(); return; }
      if (o.cyc) { cycleOpt(m, o.k, 1); renderMenu(); return; }
      if (m.kind === 'console') {                    // única ação não cíclica do menu do console: limpar as opções próprias dos jogos
        if (o.k === 'clear') { gamesOf(m.cid).forEach(g => { delete GOV[g.id]; }); save('gov', GOV); toast(t('cleared')); renderMenu(); renderGames(); }
        return;
      }
      if (o.k === 'play') launch(m.g, null);
      else if (o.k === 'state') { m.slots = true; m.i = 0; renderMenu(); }
      else if (o.k === 'fav') {
        if (favs.has(m.g.id)) { favs.delete(m.g.id); toast(t('removed')); } else { favs.add(m.g.id); toast(t('added')); }
        save('favs', [...favs]); closeMenu();
        const list = curGames(); if (S.g >= list.length) S.g = Math.max(0, list.length - 1);
        renderGames(); renderDock();
      } else if (o.k.startsWith('slot:')) launch(m.g, o.k.slice(5));
    }
  }
  function launch(g, slot) {
    closeMenu(); S.launching = true;
    const el = $('#launch');
    const o = eff(g);                                  // o que o runner receberia: core, aspecto e, se for RetroArch, shader
    const cfg = [o.core, o.aspect === 'core' ? t('coreAspect') : '4:3'].concat(data.isRetroarch(o.core) && o.shader !== 'none' ? [t('sh_' + o.shader)] : []).join(' · ');
    el.innerHTML = `${t('launching')} <b>${esc(g.title)}</b>${slot ? '<br><small>' + slotName(slot) + '</small>' : ''}<small>${cfg}</small><small>${t('launchNote')}</small>`;
    el.classList.add('on');
    setTimeout(() => { el.classList.remove('on'); S.launching = false; }, 1800);
  }

  /* ------------------------------------------------------------ Arquivos (navegador de pastas: só abre imagem e .txt) */
  let FR = 8;                                          // linhas visíveis; syncGrid() recalcula conforme a altura da tela
  const esc = s => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  const FICON = {
    dir: `<svg viewBox="0 0 24 24" aria-hidden="true">${FOLDER_PATH} fill="currentColor"/></svg>`,
    image: ICON_SHOTS.replace(' class="gi"', ''),
    text: `<svg viewBox="0 0 24 24" aria-hidden="true">${DOC_PATH}<path d="M9 12h6M9 16h6" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>`,
    file: `<svg viewBox="0 0 24 24" aria-hidden="true">${DOC_PATH}</svg>`
  };
  function openFiles() { S.fp = []; S.fi = 0; S.ftop = 0; show('files'); renderFiles(); }
  const fpath = () => { const s = [files.rootName, ...S.fp]; return (s.length > 2 ? '… / ' : '') + s.slice(-2).join(' / '); };
  function renderFiles() {
    const list = files.list(S.fp), box = $('#flist');
    $('#s-files .ghead').innerHTML = `<span class="fpath">${esc(fpath())}</span><span class="r"><span>${list.length ? (S.fi + 1) + ' / ' + list.length : '0'}</span><span class="batt"></span></span>`;
    if (!list.length) box.innerHTML = `<div class="none">${t('emptyDir')}</div>`;
    else {
      if (S.fi < S.ftop) S.ftop = S.fi; if (S.fi > S.ftop + FR - 1) S.ftop = S.fi - FR + 1;
      let h = '';
      for (let i = S.ftop; i < Math.min(list.length, S.ftop + FR); i++) {       // só a janela visível
        const e = list[i];
        h += `<div class="frow${i === S.fi ? ' sel' : ''}${e.kind === 'file' ? ' dis' : ''}"><span class="fi">${FICON[e.kind]}</span><span class="fn">${esc(e.name)}</span><span class="fs">${e.kind === 'dir' ? e.size + ' ' + t('items') : files.fmtSize(e.size)}</span></div>`;
      }
      box.innerHTML = h;
    }
    hints($('#s-files .hints'), [['A', t('openf')], ['B', S.fp.length ? t('up') : t('back')]]);
    status();
  }
  function filesKey(k) {
    const list = files.list(S.fp), n = list.length;
    if (k === 'B') {
      if (!S.fp.length) { show('dock'); renderDock(); return; }
      const from = S.fp.pop(); S.fi = Math.max(0, files.list(S.fp).findIndex(e => e.name === from)); S.ftop = 0;   // volta já na pasta de onde veio
      renderFiles(); return;
    }
    if (!n) return;
    if (k === 'U') S.fi = Math.max(0, S.fi - 1);
    else if (k === 'D') S.fi = Math.min(n - 1, S.fi + 1);
    else if (k === 'PL') S.fi = Math.max(0, S.fi - FR);
    else if (k === 'PR') S.fi = Math.min(n - 1, S.fi + FR);
    else if (k === 'A') {
      const e = list[S.fi];
      if (e.kind === 'dir') { S.fp.push(e.name); S.fi = 0; S.ftop = 0; }
      else if (e.kind === 'image') {
        const imgs = list.filter(x => x.kind === 'image'), where = '/' + [files.rootName, ...S.fp].join('/');
        S.vlist = imgs.map(x => ({ title: x.name, d: where, url: x.url })); S.vi = imgs.indexOf(e);
        S.view = true; renderView(); $('#o-view').classList.add('on'); return;
      } else if (e.kind === 'text') { openText(e); return; }
      else { toast(t('unsup')); return; }                                       // outros tipos aparecem, mas não abrem
    }
    renderFiles();
  }
  /* leitor de texto: ▲▼ rolam por linha, PgUp/PgDn (L1/R1) por página, A ou B fecham */
  function openText(e) {
    S.text = true; const ov = $('#o-text');
    ov.innerHTML = `<div class="th"><span>${esc(e.name)}</span><span class="tp"></span></div><pre>${esc(e.text === null ? t('toobig') : e.text)}</pre>`;
    ov.classList.add('on'); textPos();
  }
  function textPos() { const p = $('#o-text pre'), max = p.scrollHeight - p.clientHeight; $('#o-text .tp').textContent = max > 0 ? Math.round(p.scrollTop / max * 100) + '%' : ''; }
  function textKey(k) {
    const p = $('#o-text pre');
    if (k === 'A' || k === 'B') { S.text = false; $('#o-text').classList.remove('on'); return; }
    const line = parseFloat(getComputedStyle(p).fontSize) * 1.5, page = p.clientHeight * .9;
    if (k === 'U') p.scrollTop -= line; else if (k === 'D') p.scrollTop += line;
    else if (k === 'PL' || k === 'L') p.scrollTop -= page; else if (k === 'PR' || k === 'R') p.scrollTop += page;
    textPos();
  }

  /* ------------------------------------------------------------ Desligar o aparelho */
  function askReset() { S.menu = { kind: 'reset', i: 1 }; renderMenu(); $('#o-menu').classList.add('on'); }   // Sim on top, Cancelar focused
  function askPower() { S.menu = { kind: 'power', i: 1 }; renderMenu(); $('#o-menu').classList.add('on'); }
  function shutdown() {                              // simulado; no aparelho chama o desligamento do sistema
    S.off = true;
    const el = $('#launch');
    el.innerHTML = `${t('off1')}<small>${t('off2')}</small>`; el.classList.add('on');
    setTimeout(() => { if (S.off) el.innerHTML = ''; }, 1500);   // some o texto e fica só a tela preta
  }

  function suspend() {                               // 4.1 (D11): no confirmation; any key "wakes" and the launcher is exactly where it was
    S.off = 'sleep';
    const el = $('#launch');
    el.innerHTML = `${t('sleep1')}<small>${t('sleep2')}</small>`; el.classList.add('on');
    setTimeout(() => { if (S.off) el.innerHTML = ''; }, 1500);
  }

  /* ------------------------------------------------------------ Brilho: linha da borda, limite e relato (4.1, D12; separado de propósito) */
  const lvl = () => Math.max(1, Math.min(10, Math.round(P.bri / 10)));          // 10 levels over the 0-100% scale
  const limDot = () => (BL.on && BL.limit ? BL.limit : null);
  let edgeT;
  function renderEdge() {
    const l = lvl(), lim = limDot();
    $('#o-edge').innerHTML = `<span class="en">${l}</span><div class="etrack"><i style="height:${l * 10}%"></i>${lim ? `<b class="ldot" style="bottom:${lim * 10}%"></b>` : ''}</div>`;
  }
  function showEdge() {                              // the line on the left edge (Fn+Volume); stays up with ?tela=edge for the ruler
    renderEdge(); $('#o-edge').classList.add('on'); clearTimeout(edgeT);
    if (!BL.stick) edgeT = setTimeout(() => $('#o-edge').classList.remove('on'), 1600);
  }
  function fnVolume(dir) {
    P.bri = Math.max(10, Math.min(100, lvl() * 10 + dir * 10)); save('bri', P.bri); applyBri(); showEdge();
    if (S.screen === 'set') renderSettings();
  }
  function reportFailure(ms) {                       // Fn+Select: "the screen failed now"; the limit drops one level below the current
    const l = lvl();
    if (BL.on) { BL.limit = Math.max(1, l - 1); toast(t('reported') + ' · ' + t('limitLvl') + ' ' + BL.limit, ms); }
    else toast(t('reported'), ms);
    if ($('#o-edge').classList.contains('on')) renderEdge();
    if (S.screen === 'set') renderSettings();
  }
  function resetLearning() { BL.limit = null; toast(t('resetDone')); if ($('#o-edge').classList.contains('on')) renderEdge(); renderSettings(); }

  /* ------------------------------------------------------------ Cartão (4.1, D5) */
  function trimNow() {                               // a second request while one runs is ignored
    if (CARD.run === 'running') return;
    CARD.run = 'running'; renderSettings();
    setTimeout(() => { CARD.run = CARD.out; if (CARD.out === 'ok') CARD.trim = CARD.boot; renderSettings(); }, 1800);
  }
  const bootTxt = n => (n === null ? t('never') : t('bootN') + ' ' + n);
  function cardPanel(i) {                            // i = focused action row inside the panel (-1: panel only previewed)
    const res = { idle: '', running: t('trimming'), ok: '✓ ' + CARD.bytes + ' ' + t('freed'), fail: t('trimFail') }[CARD.run];
    return `<h3>${t('card')}</h3>
      <div class="row"><span class="muted">${t('free')}</span><span>${CARD.free}</span></div>
      <div class="row"><span class="muted">${t('lastTrim')}</span><span>${bootTxt(CARD.trim)}</span></div>
      <div class="row"><span class="muted">${t('lastCheck')}</span><span>${bootTxt(CARD.check)}</span></div>
      <div class="row act${i === 0 ? ' sel' : ''}"><span>${t('trimNow')}</span><span class="st${CARD.run === 'fail' ? ' bad' : ''}">${res}</span></div>
      <div class="row act${i === 1 ? ' sel' : ''}"><span>${t('checkNext')}</span><span class="st">${CARD.pending ? t('checkSet') : ''}</span></div>`;
  }
  function briPanel(i) {
    const lim = limDot();
    return `<h3>${t('bri')}</h3><div class="big">${P.bri}%</div>${bar(P.bri, lim)}` +
      (BL.on ? `<div class="row"><span class="muted">${t('briLimit')}</span><span>${lim ? t('level') + ' ' + lim : t('noLimit')}</span></div>
      <div class="row act${i === 0 ? ' sel' : ''}"><span>${t('resetLearn')}</span></div>` : '') + `<p class="note">${t('adj')}</p>`;
  }

  /* ------------------------------------------------------------ Capturas (imagens salvas pelo RetroArch) */
  let SC = 2, SR = 2;                                // capturas são paisagem: poucas e grandes; syncGrid() ajusta à tela
  function openShots() { S.s = 0; S.stop = 0; show('shots'); renderShots(); }
  function renderShots() {
    const list = data.shots, grid = $('#sgrid');
    $('#s-shots .ghead').innerHTML = `<span>${t('shots')}</span><span class="r"><span>${list.length ? (S.s + 1) + ' / ' + list.length : '0'}</span><span class="batt"></span></span>`;
    if (!list.length) { grid.innerHTML = `<div class="none">${t('noshots')}</div>`; $('#stitle').textContent = ''; }
    else {
      const row = Math.floor(S.s / SC);
      if (row < S.stop) S.stop = row; if (row > S.stop + SR - 1) S.stop = row - SR + 1;
      let h = '';
      for (let i = S.stop * SC; i < Math.min(list.length, (S.stop + SR) * SC); i++) h += `<div class="tile${i === S.s ? ' sel' : ''}"><img alt="" decoding="async" src="${list[i].url}"></div>`;
      grid.innerHTML = h; $('#stitle').textContent = list[S.s].title + ' · ' + list[S.s].d;
    }
    hints($('#s-shots .hints'), [['A', t('view')], ['B', t('back')]]);
    status();
  }
  function renderView() {
    const s = S.vlist[S.vi];                           // serve às Capturas e ao navegador de arquivos
    $('#o-view').innerHTML = `<img alt="" src="${s.url}"><div class="cap"><span>${esc(s.title)}</span><span>${esc(s.d)} · ${S.vi + 1}/${S.vlist.length}</span></div>`;
  }
  function viewKey(k) {                                // visualizador em tela cheia: ◀ ▶ trocam de imagem, A ou B fecham
    const n = S.vlist.length;
    if (k === 'A' || k === 'B') {
      S.view = false; $('#o-view').classList.remove('on');
      if (S.screen === 'shots') { S.s = S.vi; renderShots(); }
      else { const j = files.list(S.fp).findIndex(e => e.name === S.vlist[S.vi].title); if (j >= 0) S.fi = j; renderFiles(); }   // seleção acompanha a última imagem vista
      return;
    }
    if (k === 'L') S.vi = (S.vi + n - 1) % n; else if (k === 'R') S.vi = (S.vi + 1) % n; else return;
    renderView();
  }
  function shotsKey(k) {
    const n = data.shots.length;
    if (k === 'B') { show('dock'); renderDock(); return; }
    if (!n) return;
    if (k === 'L') S.s = Math.max(0, S.s - 1);
    else if (k === 'R') S.s = Math.min(n - 1, S.s + 1);
    else if (k === 'U') S.s = Math.max(0, S.s - SC);
    else if (k === 'D') S.s = (S.s + SC < n) ? S.s + SC : S.s;
    else if (k === 'PL') S.s = Math.max(0, S.s - SC * SR);
    else if (k === 'PR') S.s = Math.min(n - 1, S.s + SC * SR);
    else if (k === 'A') { S.vlist = data.shots; S.vi = S.s; S.view = true; renderView(); $('#o-view').classList.add('on'); return; }
    renderShots();
  }

  /* ------------------------------------------------------------ Configurações */
  const setKeys = () => { const a = []; if (env.wifi) a.push('wifi'); if (env.bt) a.push('bt'); a.push('lang', 'theme', 'lite', 'vol', 'bri', 'system', 'card', 'sleep', 'power'); return a; };
  const tn = id => { const k = 'th_' + id, v = t(k); return v === k ? ((themes.list().find(x => x.id === id) || {}).name || id) : v; };   // nome do tema no idioma atual
  const bar = (v, lim) => `<div class="bar${lim ? ' lim' : ''}"><i style="width:${v}%"></i>${lim ? `<b class="ldot" style="left:${lim * 10}%"></b>` : ''}</div>`;   // lim: red dot at the safe-limit level (4.1)
  function openSettings() { S.si = 0; S.sub = null; show('set'); renderSettings(); }

  function renderSettings() {
    const keys = setKeys(); S.si = Math.min(S.si, keys.length - 1);
    if (S.sub && !keys.includes(S.sub.k)) { S.sub = null; stopSys(); }       // dongle removido com o menu aberto
    // amostra CPU/memória só enquanto o item Sistema está selecionado; ao sair dele, para de ler
    if (!S.sub && keys[S.si] === 'system') { if (!S.stopSys) startSys(); } else stopSys();
    $('#s-set .ghead').innerHTML = `<span>${t('set')}</span><span class="r"><span class="batt"></span></span>`;
    $('#s-set .slist').innerHTML = keys.map((k, i) => `<div class="sitem${i === S.si ? ' sel' : ''}">${t(k)}</div>`).join('');
    $('#s-set .spanel').innerHTML = S.sub ? subPanel() : panel(keys[S.si]);
    const cur = keys[S.si], adj = ['lang', 'theme', 'lite', 'vol', 'bri'].includes(cur), act = ['wifi', 'bt', 'power', 'card', 'sleep'].includes(cur) || (cur === 'bri' && BL.on);
    hints($('#s-set .hints'), S.sub ? [['▲▼', t('move')], ['A', t('sel')], ['B', t('back')]]
      : [['▲▼', t('move')], ...(adj ? [['◀▶', t('adj').replace('◀ ▶ ', '')]] : []), ...(act ? [['A', t('openf')]] : []), ['B', t('back')]]);
    status();
  }
  const pick = (title, items, cur, label) => `<h3>${title}</h3>` + items.map(x => `<div class="row${x === cur ? ' sel' : ''}"><span>${label(x)}</span><span>${x === cur ? '✓' : ''}</span></div>`).join('') + `<p class="note">${t('adj')}</p>`;
  function panel(k) {
    if (k === 'wifi') return `<h3>${t('wifi')}</h3><div class="row"><span class="muted">${t('adapter')}</span><span>wlan0</span></div><div class="row"><span class="muted">Status</span><span>${S.wifiConn >= 0 ? t('connected') + ': ' + NETS[S.wifiConn].n : t('disconnected')}</span></div><p class="note">${t('open')}</p>`;
    if (k === 'bt') return `<h3>${t('bt')}</h3><div class="row"><span class="muted">${t('adapter')}</span><span>hci0</span></div><div class="row"><span class="muted">${t('devq')}</span><span>${S.btConn.length} ${t('connected').toLowerCase()}</span></div><p class="note">${t('open')}</p>`;
    if (k === 'lang') return pick(t('lang'), LANGS.map(l => l[0]), P.lang, c => LANGS.find(l => l[0] === c)[1]);
    if (k === 'theme') return pick(t('theme'), themes.list().map(x => x.id), env.theme, tn);
    if (k === 'lite') return pick(t('lite'), [false, true], env.lite, v => t(v ? 'on' : 'off')) + `<p class="note">${t('liteNote')}</p>`;
    if (k === 'vol') return `<h3>${t('vol')}</h3><div class="big">${P.vol}%</div>${bar(P.vol)}<p class="note">${t('adj')}</p>`;
    if (k === 'bri') return briPanel(-1);
    if (k === 'card') return cardPanel(-1);
    if (k === 'sleep') return `<h3>${t('sleep')}</h3><p class="note">${t('sleepNote')}</p><p class="note">${t('open')}</p>`;
    if (k === 'power') return `<h3>${t('power')}</h3><p class="note">${t('open')}</p>`;
    if (k === 'system') return sysPanel();
    return '';
  }
  function subPanel() {
    const k = S.sub.k, i = S.sub.i;
    if (k === 'card') return cardPanel(i);
    if (k === 'bri') return briPanel(i);
    if (k === 'wifi') return `<h3>${t('wifi')} · ${t('netq')}</h3>` + NETS.map((n, j) => `<div class="row${j === i ? ' sel' : ''}"><span>${n.n}</span><span>${j === S.wifiConn ? '✓ ' : ''}${'▂▄▆'.slice(0, n.q)}</span></div>`).join('');
    if (k === 'bt') return `<h3>${t('bt')} · ${t('devq')}</h3>` + DEVS.map((d, j) => `<div class="row${j === i ? ' sel' : ''}"><span>${d.ic} ${d.n}</span><span>${S.btConn.includes(j) ? '✓' : ''}</span></div>`).join('');
    return sysPanel();
  }
  function sysPanel() {                                // estatísticas do sistema: aparecem ao apenas selecionar o item
    const s = S.sys;
    return `<h3>${t('system')}</h3>
      <div class="row"><span class="muted">${t('model')}</span><span>R36S (clone)</span></div>
      <div class="row"><span class="muted">${t('cpu')}</span><span>${s.freq} MHz · ${s.temp} °C</span></div>${bar(s.cpu)}
      <div class="row"><span class="muted">${t('mem')}</span><span>${s.used} / 1024 MB</span></div>${bar(Math.round(s.used / 10.24))}
      <div class="row"><span class="muted">${t('lmem')}</span><span>${s.rss} MB</span></div>
      <div class="row"><span class="muted">${t('storage')}</span><span>41 / 128 GB</span></div>
      <p class="note">${t('simNote')}</p>`;
  }
  function startSys() {
    const h = system.startMetrics(() => { if (S.screen === 'set' && !S.sub && setKeys()[S.si] === 'system') renderSettings(); });
    S.sys = h.value; S.stopSys = h.stop;                       // só amostra enquanto o menu Sistema está aberto
  }
  function stopSys() { if (S.stopSys) { S.stopSys(); S.stopSys = null; } }

  function adjust(k, dir) {
    if (k === 'vol') { P.vol = Math.max(0, Math.min(100, P.vol + dir * 5)); save('vol', P.vol); }
    else if (k === 'bri') { P.bri = Math.max(5, Math.min(100, P.bri + dir * 5)); save('bri', P.bri); applyBri(); }
    else if (k === 'lang') { P.lang = LANGS[(LANGS.findIndex(l => l[0] === P.lang) + dir + LANGS.length) % LANGS.length][0]; save('lang', P.lang); renderDock(); }
    else if (k === 'lite') { env.lite = !env.lite; save('lite', env.lite); applyTheme(); return; }   // liga/desliga; applyTheme aplica a classe e redesenha
    else if (k === 'theme') { const l = themes.list(); env.theme = l[(l.findIndex(x => x.id === env.theme) + dir + l.length) % l.length].id; applyTheme(); return; }   // troca na hora; applyTheme redesenha tudo
    else return;
    renderSettings();
  }
  function settingsKey(k) {
    const keys = setKeys();
    if (S.sub) {
      const list = S.sub.k === 'wifi' ? NETS : S.sub.k === 'bt' ? DEVS : S.sub.k === 'card' ? [0, 1] : S.sub.k === 'bri' ? [0] : null;
      if (k === 'B') { S.sub = null; stopSys(); }
      else if (k === 'A' && S.sub.k === 'card') { if (S.sub.i === 0) trimNow(); else { CARD.pending = !CARD.pending; } }   // "Verificar no próximo boot": one request; A again cancels (prototype choice)
      else if (k === 'A' && S.sub.k === 'bri') { askReset(); return; }
      else if (list && k === 'U') S.sub.i = (S.sub.i + list.length - 1) % list.length;
      else if (list && k === 'D') S.sub.i = (S.sub.i + 1) % list.length;
      else if (k === 'A' && S.sub.k === 'wifi') { const i = S.sub.i; if (S.wifiConn === i) { S.wifiConn = -1; toast(t('disc') + ' ' + NETS[i].n); } else { S.wifiConn = i; toast(t('conn') + ' ' + NETS[i].n); } }
      else if (k === 'A' && S.sub.k === 'bt') { const i = S.sub.i, p = S.btConn.indexOf(i); if (p >= 0) { S.btConn.splice(p, 1); toast(t('disc') + ' ' + DEVS[i].n); } else { S.btConn.push(i); toast(t('conn') + ' ' + DEVS[i].n); } }
      renderSettings(); return;
    }
    if (k === 'B') { show('dock'); renderDock(); return; }
    if (k === 'U') S.si = (S.si + keys.length - 1) % keys.length;
    else if (k === 'D') S.si = (S.si + 1) % keys.length;
    else if (k === 'L') { adjust(keys[S.si], -1); return; }
    else if (k === 'R' && keys[S.si] === 'card') S.sub = { k: 'card', i: 0 };   // ▶ passes to the panel column, as in the list today
    else if (k === 'R') { adjust(keys[S.si], 1); return; }
    else if (k === 'A') {
      const key = keys[S.si];
      if (key === 'wifi' || key === 'bt' || key === 'card' || (key === 'bri' && BL.on)) S.sub = { k: key, i: 0 };
      else if (key === 'sleep') { suspend(); return; }                 // no confirmation (D11)
      else if (key === 'system') return;                  // sem submenu: as estatísticas já estão no painel
      else if (key === 'power') { askPower(); return; }
      else { adjust(key, 1); return; }
    }
    renderSettings();
  }

  /* ------------------------------------------------------------ entrada */
  function press(k) {
    if (S.off) { const sl = S.off === 'sleep'; S.off = false; $('#launch').classList.remove('on'); if (!sl) { show('dock'); renderDock(); } return; }   // wake from sleep keeps the screen   // qualquer tecla "liga" de novo
    if (S.launching) return;
    if (S.kb) return kbKey(k);
    if (S.text) return textKey(k);
    if (S.view) return viewKey(k);
    if (S.menu) return menuKey(k);
    if (S.screen === 'dock') {
      const N = dockItems().length;
      if (k === 'L') { S.dock = (S.dock + N - 1) % N; renderDock(); }
      else if (k === 'R') { S.dock = (S.dock + 1) % N; renderDock(); }
      else if (k === 'A') {
        const kind = dockItems()[S.dock].kind;
        if (kind === 'set') openSettings(); else if (kind === 'shots') openShots(); else if (kind === 'files') openFiles(); else openGames();
      }
    } else if (S.screen === 'games') {
      const n = curGames().length;
      if (k === 'B') {
        if (S.q) { S.q = ''; S.g = 0; S.top = 0; renderGames(); return; }       // com busca ativa, B primeiro limpa o filtro
        show('dock'); renderDock(); return;
      }
      if (k === 'X') return openSearch();
      if (!n) return;
      if (k === 'L') S.g = Math.max(0, S.g - 1);
      else if (k === 'R') S.g = Math.min(n - 1, S.g + 1);
      else if (k === 'U') S.g = Math.max(0, S.g - COLS);
      else if (k === 'PL') S.g = Math.max(0, S.g - jumpSize(n));               // salto de página: listas têm centenas de jogos
      else if (k === 'PR') S.g = Math.min(n - 1, S.g + jumpSize(n));
      else if (k === 'D') S.g = (S.g + COLS < n) ? S.g + COLS : (Math.floor(S.g / COLS) < Math.floor((n - 1) / COLS) ? n - 1 : S.g);
      else if (k === 'A') return openMenu();
      else if (k === 'Y') return openConsoleMenu();                // opções do console inteiro (não de um jogo só)
      renderGames();
    } else if (S.screen === 'shots') shotsKey(k);
    else if (S.screen === 'files') filesKey(k);
    else if (S.screen === 'set') settingsKey(k);
  }
  const KEYS = { ArrowLeft: 'L', ArrowRight: 'R', ArrowUp: 'U', ArrowDown: 'D', Enter: 'A', z: 'A', Z: 'A', Escape: 'B', Backspace: 'B', x: 'B', X: 'B', PageUp: 'PL', PageDown: 'PR', '[': 'PL', ']': 'PR', y: 'Y', Y: 'Y', '/': 'X' };
  addEventListener('keydown', e => {
    if (e.target && e.target.tagName === 'SELECT') return;
    if (S.kb) {                                        // teclado físico (só para o protótipo): digita direto na busca
      if (e.key.length === 1 && /[A-Za-z0-9 ]/.test(e.key)) { e.preventDefault(); kbType(e.key.toUpperCase()); renderKb(); return; }
      if (e.key === 'Backspace') { e.preventDefault(); S.kb.text = S.kb.text.slice(0, -1); renderKb(); return; }
    }
    if (e.key === 'F2' || e.key === 'F3') { e.preventDefault(); fnVolume(e.key === 'F2' ? 1 : -1); return; }   // Fn+Volume (simulated)
    if (e.key === 'F4') { e.preventDefault(); reportFailure(); return; }                                       // Fn+Select (simulated)
    if (e.key === 't' || e.key === 'T') { e.preventDefault(); cycleTheme(); return; }
    const k = KEYS[e.key]; if (k) { e.preventDefault(); press(k); }
  });

  /* gamepad: só consulta enquanto houver um conectado */
  let padT = null, last = {};
  function poll() {
    const gp = (navigator.getGamepads && navigator.getGamepads() || [])[0]; if (!gp) return;
    const b = i => gp.buttons[i] && gp.buttons[i].pressed;
    const now = { L: b(14) || gp.axes[0] < -.6, R: b(15) || gp.axes[0] > .6, U: b(12) || gp.axes[1] < -.6, D: b(13) || gp.axes[1] > .6, A: b(0), B: b(1), PL: b(4), PR: b(5), Y: b(3), X: b(2) };
    for (const k in now) if (now[k] && !last[k]) press(k);
    last = now;
  }
  addEventListener('gamepadconnected', () => { if (!padT) padT = setInterval(poll, 90); });
  addEventListener('gamepaddisconnected', () => { clearInterval(padT); padT = null; });

  /* ------------------------------------------------------------ barra de ferramentas e início */
  function bindTools() {
    const th = $('#theme'); th.innerHTML = themes.list().map(x => `<option value="${x.id}">${x.name}</option>`).join('');
    th.onchange = () => { env.theme = th.value; applyTheme(); };
    const r = $('#res'); r.value = env.res; r.onchange = () => { env.res = r.value; save('res', env.res); applyRes(); };
    const w = $('#dwifi'), b = $('#dbt');
    w.checked = env.wifi; b.checked = env.bt;
    w.onchange = () => { env.wifi = w.checked; save('dwifi', env.wifi); renderAll(); };
    b.onchange = () => { env.bt = b.checked; save('dbt', env.bt); renderAll(); };
    const dm = $('#demo'); dm.checked = env.demo; dm.onchange = () => { env.demo = dm.checked; save('demo', env.demo); renderAll(); };
    const rl = $('#real'), pp = $('#ppi'); rl.checked = env.real; pp.value = env.ppi;
    rl.onchange = () => { env.real = rl.checked; save('real', env.real); applyRes(); };
    pp.onchange = () => { env.ppi = Math.max(50, Math.min(400, +pp.value || 96)); save('ppi', env.ppi); applyRes(); };
    /* battery review controls (charge mark and low-battery warning) */
    const bp = $('#batp'), bs = $('#bats');
    bp.value = BAT.p; bs.value = BAT.st;
    const bset = () => { BAT.p = Math.max(0, Math.min(100, parseInt(bp.value, 10) || 0)); BAT.st = bs.value; status(); checkBattery(); };
    bp.onchange = bset; bs.onchange = bset;
    $('#batw').onclick = () => { BAT.p = Math.min(BAT.p, WARN_AT); BAT.st = 'discharging'; bp.value = BAT.p; bs.value = BAT.st; status(); checkBattery(true); };
    /* 4.1 review controls: card state, brightness-limit feature (D12), Fn shortcuts */
    const cs = $('#cardst'), d12 = $('#d12');
    cs.value = CARD.run; cs.onchange = () => { CARD.run = cs.value; if (CARD.run === 'ok' || CARD.run === 'fail') CARD.out = CARD.run; renderSettings(); };
    d12.checked = BL.on; d12.onchange = () => { BL.on = d12.checked; renderAll(); if ($('#o-edge').classList.contains('on')) renderEdge(); };
    $('#fnup').onclick = () => fnVolume(1); $('#fndn').onclick = () => fnVolume(-1); $('#fnrep').onclick = () => reportFailure();
    addEventListener('resize', applyRes);
  }
  /* ?tela=<name> jumps straight to a 4.1 screen, for the ruler and for review */
  function demoScreen(n) {
    const go = (key, sub) => { openSettings(); S.si = setKeys().indexOf(key); if (sub) S.sub = { k: key, i: sub.i }; renderSettings(); };
    if (n === 'card') go('card');
    else if (n === 'card-act') go('card', { i: 0 });
    else if (n === 'card-running') { CARD.run = 'running'; go('card', { i: 0 }); }
    else if (n === 'card-ok') { CARD.run = 'ok'; CARD.trim = CARD.boot; go('card', { i: 0 }); }
    else if (n === 'card-fail') { CARD.run = 'fail'; CARD.out = 'fail'; go('card', { i: 0 }); }
    else if (n === 'card-check') { CARD.pending = true; go('card', { i: 1 }); }
    else if (n === 'sleep') go('sleep');
    else if (n === 'bri') go('bri');
    else if (n === 'bri-act') go('bri', { i: 0 });
    else if (n === 'reset') { go('bri', { i: 0 }); askReset(); }
    else if (n === 'edge' || n === 'edge-nolimit') { if (n === 'edge-nolimit') BL.limit = null; BL.stick = true; P.bri = 80; applyBri(); showEdge(); }
    else if (n === 'report') { P.bri = 80; applyBri(); reportFailure(3600000); }
    const cs = $('#cardst'); if (cs) cs.value = CARD.run;
  }

  /* imagem que não abre no visualizador (arquivo corrompido): avisa em vez de mostrar um ícone quebrado */
  $('#o-view').addEventListener('error', e => {
    const im = e.target; if (!im || im.tagName !== 'IMG') return;
    im.style.display = 'none'; const m = document.createElement('div'); m.className = 'vmsg'; m.textContent = t('badimg'); im.parentNode.insertBefore(m, im);
  }, true);
  /* a capa em destaque no menu do jogo também cai na caixa gerada se falhar */
  $('#o-menu').addEventListener('error', e => {
    const im = e.target; if (!im || im.tagName !== 'IMG' || !im.classList.contains('big') || !S.menu || !S.menu.g) return;
    im.src = art(Object.assign({}, S.menu.g, { img: null }));
  }, true);

  /* se uma capa falhar ao carregar (arquivo corrompido ou ausente), cai na caixa gerada */
  $('#grid').addEventListener('error', e => {
    const im = e.target; if (!im || im.tagName !== 'IMG' || im.dataset.fb) return;
    const g = curGames()[+im.dataset.i]; if (!g) return;
    im.dataset.fb = '1'; im.src = art(Object.assign({}, g, { img: null }));
  }, true);

  buildDock(); bindTools(); applyBri(); applyTheme(); applyRes(); checkBattery();
  demoScreen(QS.get('tela'));
})();
