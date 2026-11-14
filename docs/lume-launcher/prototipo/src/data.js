/* lume-launcher · módulo de dados (consoles, jogos, capas, save states).
   Fonte preferida: Lume.catalog, gerado por tools/build-catalog.js a partir da pasta de ROMs real
   (gamelist.xml + img/ + savestates/). Sem catálogo, gera dados de demonstração.
   No app real isto é o índice em cache produzido pelo scanner de ROMs. */
(function () {
  'use strict';
  const Lume = (window.Lume = window.Lume || {});
  const hash = s => { let h = 5381; for (let i = 0; i < s.length; i++) h = ((h << 5) + h + s.charCodeAt(i)) | 0; return Math.abs(h); };
  const cat = Lume.catalog;
  const pad = n => String(n).padStart(2, '0');
  const fmtDate = sec => { const d = new Date(sec * 1000); return pad(d.getDate()) + '/' + pad(d.getMonth() + 1) + ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes()); };

  /* Emuladores/cores por console. O 1º de cada lista é o padrão.
     CONFIRMADOS pelos seus savestates/<sistema>/<core>/: snes (Snes9x, Snes9x 2010, Snes9x 2005 Plus), nes (FCEUmm, Nestopia),
     gb/gbc (Gambatte), gba (gpSP), megadrive (Genesis Plus GX), n64 (Mupen64Plus GLES2), neogeo/cps2 (FB Alpha 2012),
     cps1 (FinalBurn Neo), pcengine (Beetle PCE Fast), psx (PCSX-ReARMed), sega32x (PicoDrive), psp (PPSSPP).
     As ALTERNATIVAS marcadas com * são prováveis, mas não foram confirmadas no dArkOS: no app real a lista vem da configuração
     de emuladores do sistema (es_systems), não daqui. */
  const CORES = {
    snes: ['Snes9x', 'Snes9x 2010', 'Snes9x 2005 Plus'], nes: ['FCEUmm', 'Nestopia'],
    gb: ['Gambatte', 'mGBA*'], gbc: ['Gambatte', 'mGBA*'], gba: ['gpSP', 'mGBA*'],
    megadrive: ['Genesis Plus GX', 'PicoDrive*'], pcengine: ['Beetle PCE Fast'], psx: ['PCSX-ReARMed'],
    n64: ['Mupen64Plus GLES2', 'ParaLLEl N64*'], neogeo: ['FB Alpha 2012', 'FinalBurn Neo*'],
    cps1: ['FinalBurn Neo', 'FB Alpha 2012*'], cps2: ['FB Alpha 2012', 'FinalBurn Neo*'], fbneo: ['FinalBurn Neo', 'FB Alpha 2012*'],
    sega32x: ['PicoDrive'], psp: ['PPSSPP'], nds: ['melonDS*', 'DeSmuME*'], love: ['LÖVE']
  };
  let CONSOLES, gamesOf;

  if (cat) {
    /* ---------- catálogo real ---------- */
    const enc = p => p.split('/').map(encodeURIComponent).join('/');
    const stemOf = f => f.replace(/\.[^.]+$/, '');
    CONSOLES = cat.systems.map(s => ({ id: s.id, abbr: s.abbr, sub: s.name, hue: hash(s.id) % 360, logo: !!s.logo, cores: CORES[s.id] || ['Padrão'] }));
    const cache = {};
    gamesOf = cid => {
      if (cache[cid]) return cache[cid];
      const sys = cat.systems.find(s => s.id === cid), abbr = sys.abbr, stateDir = cid === 'psp' ? 'PPSSPPSDL' : cid;
      return (cache[cid] = sys.games.map(g => ({
        id: cid + ':' + g.f, cid, abbr, title: g.t, file: g.f,
        img: g.i ? cat.base + enc(cid + '/' + g.i) : null,
        // core: pasta do core onde o save está ('' = arquivo solto na raiz, tratado como do core padrão do console)
        saves: (g.s || []).map(([k, mt, th, core]) => {
          const name = stemOf(g.f) + '.state' + (k === 'a' ? '.auto' : (k === '0' ? '' : k));
          return { k, core: core || '', d: fmtDate(mt), th: th ? cat.base + enc('savestates/' + stateDir + '/' + (core ? core + '/' : '') + name + '.png') : null };
        })
      })));
    };
  } else {
    /* ---------- demonstração (sem catálogo) ---------- */
    CONSOLES = [
      { id: 'snes', abbr: 'SNES', sub: 'Super Nintendo', hue: 265 }, { id: 'gba', abbr: 'GBA', sub: 'Game Boy Advance', hue: 235 },
      { id: 'psx', abbr: 'PS1', sub: 'PlayStation', hue: 205 }, { id: 'megadrive', abbr: 'MD', sub: 'Mega Drive', hue: 15 }
    ].map(c => Object.assign(c, { cores: CORES[c.id] || ['Padrão'] }));
    const WA = ['Super', 'Turbo', 'Mega', 'Astro', 'Pixel', 'Ninja', 'Cosmic', 'Dragon', 'Shadow', 'Rocket', 'Golden', 'Crystal'];
    const WB = ['Runner', 'Quest', 'Fighters', 'Racer', 'Kingdom', 'Blaster', 'Legends', 'Adventure', 'Island', 'Warriors', 'Odyssey', 'Heroes'];
    const cache = {};
    gamesOf = cid => cache[cid] || (cache[cid] = Array.from({ length: 24 }, (_, i) => {
      const h = hash(cid + i), c = CONSOLES.find(x => x.id === cid);
      return { id: cid + ':' + i, cid, abbr: c.abbr, title: WA[h % 12] + ' ' + WB[(h >> 3) % 12], img: null,
        saves: h % 4 === 0 ? [] : [{ k: '1', core: '', d: '12/11 21:40', th: null }, { k: 'a', core: '', d: '13/11 09:05', th: null }] };
    }));
  }

  /* capa: usa a imagem real; sem ela, gera uma caixa (cache com teto fixo para a RAM não crescer) */
  const artCache = new Map(), ART_MAX = 40;
  function art(g) {
    if (g.img) return g.img;
    if (artCache.has(g.id)) return artCache.get(g.id);
    const h = hash(g.id), c1 = `hsl(${h % 360},70%,45%)`, c2 = `hsl(${(h + 40) % 360},70%,22%)`;
    const w = g.title.split(' '), half = Math.ceil(w.length / 2), l1 = w.slice(0, half).join(' '), l2 = w.slice(half).join(' ');
    const esc = s => s.replace(/&/g, '&amp;').replace(/</g, '&lt;');
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 168"><defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="${c1}"/><stop offset="1" stop-color="${c2}"/></linearGradient></defs><rect width="120" height="168" rx="4" fill="url(#g)"/><circle cx="${30 + h % 60}" cy="68" r="${18 + h % 22}" fill="#fff" fill-opacity=".2"/><path d="M0 122 L38 82 L68 112 L94 86 L120 116 L120 168 L0 168Z" fill="#000" fill-opacity=".28"/><rect width="120" height="16" fill="#000" fill-opacity=".5"/><text x="60" y="11.5" text-anchor="middle" font-family="sans-serif" font-weight="700" font-size="9" fill="#fff">${esc(g.abbr)}</text><text x="60" y="142" text-anchor="middle" font-family="sans-serif" font-weight="800" font-size="13" fill="#fff">${esc(l1.slice(0, 14))}</text><text x="60" y="158" text-anchor="middle" font-family="sans-serif" font-weight="800" font-size="13" fill="#fff">${esc(l2.slice(0, 14))}</text></svg>`;
    const uri = 'data:image/svg+xml;utf8,' + encodeURIComponent(svg);
    artCache.set(g.id, uri);
    if (artCache.size > ART_MAX) artCache.delete(artCache.keys().next().value);
    return uri;
  }

  /* capturas de tela salvas pelo RetroArch (mais recentes primeiro). A data vem do nome do arquivo e é a hora do aparelho. */
  const fmtUTC = sec => { const d = new Date(sec * 1000); return pad(d.getUTCDate()) + '/' + pad(d.getUTCMonth() + 1) + ' ' + pad(d.getUTCHours()) + ':' + pad(d.getUTCMinutes()); };
  const shots = ((cat && cat.shots) || []).map(s => ({ id: 'shot:' + s.f, title: s.g, d: fmtUTC(s.t), url: cat.base + 'screenshots/' + encodeURIComponent(s.f) }));

  /* SAVE STATES INVENTADOS, só para avaliar a tela (não existem no disco): cerca de 1 em cada 3 jogos ganha de 1 a 4
     slots, sempre com o automático, com data e miniatura gerada. Os jogos restantes ficam sem save, para ver os dois casos. */
  const demoCache = new Map();
  function demoThumb(g, h) {
    const hue = h % 360, hue2 = (hue + 50) % 360;
    const blocks = [0, 1, 2].map(i => `<rect x="${8 + ((h >> (i + 3)) % 50)}" y="${26 + ((h >> (i + 6)) % 10)}" width="10" height="10" fill="hsl(${hue2},70%,45%)"/>`).join('');
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 80 60"><defs><linearGradient id="s" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="hsl(${hue},65%,62%)"/><stop offset="1" stop-color="hsl(${hue},55%,35%)"/></linearGradient></defs><rect width="80" height="60" fill="url(#s)"/><circle cx="${15 + (h % 50)}" cy="14" r="6" fill="#fff" fill-opacity=".55"/>${blocks}<rect y="46" width="80" height="14" fill="hsl(${hue2},45%,22%)"/><rect x="${20 + (h % 30)}" y="34" width="8" height="12" rx="1.5" fill="#fff"/><text x="3" y="9" font-family="sans-serif" font-size="6" font-weight="700" fill="#fff" fill-opacity=".85">${g.abbr}</text></svg>`;
    return 'data:image/svg+xml;utf8,' + encodeURIComponent(svg);
  }
  function demoSaves(g, core) {                          // inventados POR CORE: cada core tem os seus (save de um core não serve em outro)
    const key = g.id + '|' + (core || '');
    if (demoCache.has(key)) return demoCache.get(key);
    const h = hash('demo:' + key); let out = [];
    if (h % 3 === 0) {
      out = ['0', '1', '2', 'a'].filter((k, i) => k === 'a' || (h >> (i + 2)) % 2 === 0).map((k, i) => ({
        k, core: core || '', demo: true, th: demoThumb(g, h + i * 97),
        d: pad(1 + (h >> (i + 1)) % 28) + '/' + pad(1 + (h >> (i + 4)) % 12) + ' ' + pad((h >> (i + 5)) % 24) + ':' + pad((h >> (i + 7)) % 60)
      }));
    }
    demoCache.set(key, out); return out;
  }

  /* saves REAIS válidos para um core: os da pasta desse core e, se for o core padrão do console, também os soltos na raiz.
     Se o mesmo slot existir nos dois lugares, vale o da pasta do core. Os de outro core não servem e ficam de fora. */
  function savesFor(g, core) {
    const dflt = consoleOf(g.cid).cores.map(coreName)[0], byKey = new Map();
    g.saves.filter(s => s.core === core || (s.core === '' && core === dflt))
      .sort((a, b) => (a.core === '') - (b.core === ''))
      .forEach(s => { if (!byKey.has(s.k)) byKey.set(s.k, s); });
    return [...byKey.values()].sort((a, b) => (a.k === 'a') - (b.k === 'a') || a.k.localeCompare(b.k));
  }

  /* cores fora do RetroArch (standalone): não têm shader do RetroArch. PPSSPP: a pasta "PPSSPPSDL" nos seus savestates indica o standalone. */
  const STANDALONE = new Set(['PPSSPP', 'LÖVE']);
  const coreName = c => c.replace(/\*$/, '');                 // tira a marca de "alternativa não confirmada"
  const isRetroarch = c => !STANDALONE.has(coreName(c));
  const consoleOf = id => CONSOLES.find(c => c.id === id);

  Lume.data = { CONSOLES, gamesOf, art, shots, demoSaves, savesFor, coreName, isRetroarch, consoleOf, real: !!cat };
})();
