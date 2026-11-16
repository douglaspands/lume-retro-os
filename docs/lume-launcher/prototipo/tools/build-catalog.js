#!/usr/bin/env node
/* lume-launcher · gerador de catálogo (roda no PC, nunca no aparelho).
   Lê a pasta de ROMs no formato do dArkOS/EmulationStation e gera catalog.js:
     - jogos e títulos de <sistema>/gamelist.xml
     - capas em <sistema>/img/
     - save states reais em savestates/<sistema>/  (<rom>.state, .stateN, .state.auto e miniatura .png)
   É o embrião do "scanner de ROMs + índice em cache" do app real: o launcher lê um índice
   pronto em vez de varrer o cartão SD a cada abertura.

   Uso:  node tools/build-catalog.js <pasta-das-roms> [--base=URL] [--logos=<pasta>]
   Por padrão as imagens são referenciadas por file:// apontando para a pasta de ROMs.
   Para servir por http, passe --base=http://localhost:8000/ */
'use strict';
const fs = require('fs'), path = require('path');

const args = process.argv.slice(2);
const rootArg = args.find(a => !a.startsWith('--'));
if (!rootArg) { console.error('usage: node tools/build-catalog.js <roms-dir> [--base=URL] [--logos=<dir>]'); process.exit(2); }
const root = path.resolve(rootArg);
const baseArg = (args.find(a => a.startsWith('--base=')) || '').slice(7);
const base = baseArg || ('file://' + root.split(path.sep).map(encodeURIComponent).join('/') + '/');
const out = path.resolve(__dirname, '..', 'catalog.js');

/* id da pasta → [sigla, nome]. Sistemas fora da lista usam o id em maiúsculas. */
const NAMES = {
  nes: ['NES', 'Nintendo'], snes: ['SNES', 'Super Nintendo'], gb: ['GB', 'Game Boy'], gbc: ['GBC', 'Game Boy Color'],
  gba: ['GBA', 'Game Boy Advance'], megadrive: ['MD', 'Mega Drive'], pcengine: ['PCE', 'PC Engine'], psx: ['PS1', 'PlayStation'],
  n64: ['N64', 'Nintendo 64'], neogeo: ['NEO', 'Neo Geo'], cps1: ['CPS1', 'Capcom CPS-1'], cps2: ['CPS2', 'Capcom CPS-2'],
  sega32x: ['32X', 'Sega 32X'], fbneo: ['ARC', 'Arcade'], psp: ['PSP', 'PlayStation Portable'], nds: ['NDS', 'Nintendo DS'], love: ['LÖVE', 'LÖVE']
};
const ORDER = ['nes', 'snes', 'gb', 'gbc', 'gba', 'megadrive', 'pcengine', 'psx', 'n64', 'neogeo', 'cps1', 'cps2', 'sega32x', 'fbneo'];
const SKIP = new Set(['ports_scripts']);
const SAVE_DIR = { psp: 'PPSSPPSDL' };

const decode = s => s.replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"').replace(/&apos;/g, "'");
const tag = (xml, t) => { const m = xml.match(new RegExp('<' + t + '>([\\s\\S]*?)</' + t + '>')); return m ? decode(m[1].trim()) : ''; };
/* título de exibição: tira (U), [!], [E], (ENG), "# SNES" etc. */
const clean = n => { const s = n.replace(/\s*[\(\[][^\)\]]*[\)\]]/g, '').replace(/\s*#\s*\w+\s*$/, '').replace(/\s+/g, ' ').trim(); return s || n; };
const stemOf = f => f.replace(/\.[^.]+$/, '');
/* capa válida = existe e tem assinatura de PNG, JPEG ou WebP (há arquivos .png que são texto, de downloads que falharam) */
const badImg = [];
function isImage(p) {
  let fd; try { fd = fs.openSync(p, 'r'); } catch (e) { return false; }
  try {
    const b = Buffer.alloc(12); if (fs.readSync(fd, b, 0, 12, 0) < 12) return false;
    return (b[0] === 0x89 && b.toString('latin1', 1, 4) === 'PNG') || (b[0] === 0xFF && b[1] === 0xD8) || (b.toString('latin1', 0, 4) === 'RIFF' && b.toString('latin1', 8, 12) === 'WEBP');
  } finally { fs.closeSync(fd); }
}
const norm = p => p.replace(/^\.\//, '');

/* mapa stem → [[slot, mtime, temMiniatura, core]] a partir de savestates/<sistema>/.
   Save state é específico do core: o RetroArch pode guardá-los em savestates/<sistema>/<Core>/ (core = nome da pasta)
   e há também arquivos soltos na raiz (core = ''), que o launcher trata como do core padrão do console. */
function scanStates(sys) {
  const base = path.join(root, 'savestates', SAVE_DIR[sys] || sys), map = new Map();
  let top; try { top = fs.readdirSync(base, { withFileTypes: true }); } catch (e) { return map; }
  const places = [['', base], ...top.filter(e => e.isDirectory()).map(e => [e.name, path.join(base, e.name)])];
  for (const [core, dir] of places) {
    let entries; try { entries = fs.readdirSync(dir, { withFileTypes: true }).filter(e => e.isFile()).map(e => e.name); } catch (e) { continue; }
    const set = new Set(entries);
    for (const name of entries) {
      const m = name.match(/^(.+)\.state(\d*)(\.auto)?$/); if (!m) continue;
      const k = m[3] ? 'a' : (m[2] === '' ? '0' : m[2]);
      const mt = Math.floor(fs.statSync(path.join(dir, name)).mtimeMs / 1000);
      if (!map.has(m[1])) map.set(m[1], []);
      map.get(m[1]).push([k, mt, set.has(name + '.png') ? 1 : 0, core]);
    }
  }
  for (const list of map.values()) list.sort((a, b) => (a[0] === 'a') - (b[0] === 'a') || a[0].localeCompare(b[0], 'en', { numeric: true }));
  return map;
}

const systems = [];
const dirs = fs.readdirSync(root, { withFileTypes: true }).filter(e => e.isDirectory() && !SKIP.has(e.name)).map(e => e.name);
for (const id of dirs) {
  const gl = path.join(root, id, 'gamelist.xml'); if (!fs.existsSync(gl)) continue;
  const xml = fs.readFileSync(gl, 'utf8'), present = new Set(fs.readdirSync(path.join(root, id)));
  const states = scanStates(id), games = []; let withImg = 0, withSave = 0, missing = 0;
  for (const m of xml.matchAll(/<game>([\s\S]*?)<\/game>/g)) {
    const p = tag(m[1], 'path'); if (!p) continue;
    const rel = norm(p), f = rel.split('/').pop();
    if (!(rel.includes('/') ? fs.existsSync(path.join(root, id, rel)) : present.has(f))) { missing++; continue; }   // ROM listada mas ausente
    const g = { t: clean(tag(m[1], 'name') || stemOf(f)), f };
    const img = norm(tag(m[1], 'image'));
    if (img && isImage(path.join(root, id, img))) { g.i = img; withImg++; } else if (img && fs.existsSync(path.join(root, id, img))) badImg.push(id + '/' + img);
    const s = states.get(stemOf(f)); if (s) { g.s = s; withSave++; }
    games.push(g);
  }
  if (!games.length) continue;
  games.sort((a, b) => a.t.localeCompare(b.t, 'pt', { sensitivity: 'base', numeric: true }));
  const [abbr, name] = NAMES[id] || [id.toUpperCase().slice(0, 4), id];
  systems.push({ id, abbr, name, games });
  console.log(`${id.padEnd(10)} ${String(games.length).padStart(5)} jogos  ${String(withImg).padStart(5)} capas  ${String(withSave).padStart(3)} com save  ${missing ? missing + ' ROMs ausentes' : ''}`);
}
systems.sort((a, b) => { const x = ORDER.indexOf(a.id), y = ORDER.indexOf(b.id); return (x < 0 ? 99 : x) - (y < 0 ? 99 : y) || a.id.localeCompare(b.id); });

/* logos de marca (do tema de ES que você já tem): copia as versões branca e colorida de cada sistema
   para assets/logos/, para o protótipo não depender da pasta de ROMs. Sem logo, o Dock usa a sigla. */
const logosArg = (args.find(a => a.startsWith('--logos=')) || '').slice(8);
const logosDir = logosArg || path.join(root, 'themes', 'Crystal', 'assets', 'logos');
const noLogo = [];
for (const s of systems) {
  let ok = true;
  for (const set of ['white', 'color']) {
    const src = path.join(logosDir, set + '_logo', s.id + '.svg');
    if (!fs.existsSync(src)) { ok = false; continue; }
    const dst = path.resolve(__dirname, '..', 'assets', 'logos', set, s.id + '.svg');
    fs.mkdirSync(path.dirname(dst), { recursive: true }); fs.copyFileSync(src, dst);
  }
  if (ok) s.logo = 1; else noLogo.push(s.id);
}
console.log(`\nlogos: ${systems.length - noLogo.length}/${systems.length} sistemas` + (noLogo.length ? ` (sem logo: ${noLogo.join(', ')})` : ''));

/* capturas de tela do RetroArch: <rom>-<aammdd>-<hhmmss>.png em screenshots/ (a data do nome é a hora do aparelho) */
const shots = [], shotDir = path.join(root, 'screenshots');
try {
  for (const e of fs.readdirSync(shotDir, { withFileTypes: true })) {
    if (!e.isFile() || !/\.(png|jpe?g|webp)$/i.test(e.name) || !isImage(path.join(shotDir, e.name))) continue;
    const m = e.name.match(/^(.*)-(\d{2})(\d{2})(\d{2})-(\d{2})(\d{2})(\d{2})\.\w+$/);
    let t, g;
    if (m) { g = clean(m[1]); t = Date.UTC(2000 + +m[2], +m[3] - 1, +m[4], +m[5], +m[6], +m[7]) / 1000; }
    else { const d = new Date(fs.statSync(path.join(shotDir, e.name)).mtimeMs); g = clean(stemOf(e.name)); t = Date.UTC(d.getFullYear(), d.getMonth(), d.getDate(), d.getHours(), d.getMinutes(), d.getSeconds()) / 1000; }
    shots.push({ f: e.name, t, g });
  }
} catch (e) { /* sem pasta de capturas */ }
shots.sort((a, b) => b.t - a.t);
console.log(`capturas: ${shots.length}`);

/* árvore de pastas para o navegador de arquivos (fs.js, separado do catálogo por ser maior).
   Cada pasta é [nome, [filhos]] e cada arquivo é [nome, tamanho] ou [nome, tamanho, conteúdo] (só .txt pequenos,
   embutidos para abrir mesmo em file://). No app real isto é um readdir sob demanda, não um índice. */
const FS_SKIP = new Set(['System Volume Information', 'node_modules', '$RECYCLE.BIN', 'lost+found']);
const TXT_MAX = 256 * 1024, fsCount = { dirs: 0, files: 0, txt: 0 };
function walk(dir) {
  const out = []; let ents;
  try { ents = fs.readdirSync(dir, { withFileTypes: true }); } catch (e) { return out; }
  for (const e of ents) {
    if (e.name.startsWith('.') || FS_SKIP.has(e.name)) continue;
    const p = path.join(dir, e.name);
    if (e.isDirectory()) { fsCount.dirs++; out.push([e.name, walk(p)]); }
    else if (e.isFile()) {
      let size = 0; try { size = fs.statSync(p).size; } catch (err) { /* segue com 0 */ }
      const node = [e.name, size]; fsCount.files++;
      if (/\.txt$/i.test(e.name) && size <= TXT_MAX) { try { node.push(fs.readFileSync(p, 'utf8')); fsCount.txt++; } catch (err) { /* sem permissão */ } }
      out.push(node);
    }
  }
  return out;
}
const fsOut = path.resolve(__dirname, '..', 'fs.js');
fs.writeFileSync(fsOut, '/* gerado por tools/build-catalog.js; não editar */\nwindow.Lume = window.Lume || {};\nLume.fsroot = ' + JSON.stringify({ name: path.basename(root), base, tree: walk(root) }) + ';\n');
console.log(`arquivos: ${fsCount.dirs} pastas, ${fsCount.files} arquivos, ${fsCount.txt} .txt embutidos → fs.js (${(fs.statSync(fsOut).size / 1024).toFixed(0)} KB)`);

const payload = { generated: new Date().toISOString(), base, systems, shots };
fs.writeFileSync(out, '/* gerado por tools/build-catalog.js; não editar */\nwindow.Lume = window.Lume || {};\nLume.catalog = ' + JSON.stringify(payload) + ';\n');
if (badImg.length) console.log(`\n${badImg.length} capas inválidas (não são imagem) ignoradas; o launcher usa uma caixa gerada no lugar:\n  ` + badImg.slice(0, 8).join('\n  ') + (badImg.length > 8 ? `\n  … e mais ${badImg.length - 8}` : ''));
const total = systems.reduce((n, s) => n + s.games.length, 0);
console.log(`\n${systems.length} sistemas, ${total} jogos → ${out} (${(fs.statSync(out).size / 1024).toFixed(0)} KB)`);
