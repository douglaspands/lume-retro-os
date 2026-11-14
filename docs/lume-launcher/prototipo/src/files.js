/* lume-launcher · módulo do navegador de arquivos.
   Só lê e classifica: pastas e arquivos de TEXTO (.txt) ou IMAGEM abrem; o resto aparece, mas não abre.
   Fonte: Lume.fsroot, gerado por tools/build-catalog.js. No app real, list() vira um readdir sob demanda
   (nada de índice em memória) e o conteúdo do .txt é lido do disco, com teto de tamanho. */
(function () {
  'use strict';
  const Lume = (window.Lume = window.Lume || {});
  const raw = Lume.fsroot;
  const IMG = /\.(png|jpe?g|gif|webp|bmp)$/i, TXT = /\.txt$/i;
  const enc = segs => segs.map(encodeURIComponent).join('/');
  const cmp = (a, b) => (a.kind === 'dir') !== (b.kind === 'dir') ? (a.kind === 'dir' ? -1 : 1)
    : a.name.localeCompare(b.name, 'pt', { sensitivity: 'base', numeric: true });

  const cache = new Map();                                  // listagens já ordenadas, por caminho
  function list(path) {
    const key = path.join('/');
    if (cache.has(key)) return cache.get(key);
    let cur = raw.tree;
    for (const seg of path) { const d = cur.find(n => Array.isArray(n[1]) && n[0] === seg); if (!d) { cur = []; break; } cur = d[1]; }
    const out = cur.map(n => {
      const dir = Array.isArray(n[1]);
      const kind = dir ? 'dir' : IMG.test(n[0]) ? 'image' : TXT.test(n[0]) ? 'text' : 'file';
      return { name: n[0], kind, size: dir ? n[1].length : n[1], text: dir ? null : (n[2] === undefined ? null : n[2]),
               url: kind === 'image' ? raw.base + enc([...path, n[0]]) : null };
    }).sort(cmp);
    cache.set(key, out);
    return out;
  }
  const fmtSize = n => n < 1024 ? n + ' B' : n < 1048576 ? (n / 1024).toFixed(n < 10240 ? 1 : 0) + ' KB' : (n / 1048576).toFixed(1) + ' MB';

  Lume.files = { available: !!raw, rootName: raw ? raw.name : '', list, fmtSize };
})();
