#!/usr/bin/env node
/* Confere que pt-BR, en e es têm exatamente as mesmas chaves e que nenhuma tradução está vazia.
   Uso: node tools/check-i18n.js */
'use strict';
const fs = require('fs'), path = require('path'), vm = require('vm');
global.window = global;
vm.runInThisContext(fs.readFileSync(path.join(__dirname, '..', 'src', 'i18n.js'), 'utf8'));
const dict = Lume.i18n.dict, langs = Object.keys(dict), all = new Set(langs.flatMap(l => Object.keys(dict[l])));
let bad = 0;
for (const l of langs) {
  const missing = [...all].filter(k => !(k in dict[l])), empty = Object.keys(dict[l]).filter(k => !String(dict[l][k]).trim());
  if (missing.length || empty.length) { bad++; console.log(`${l}: faltando [${missing.join(', ')}] vazias [${empty.join(', ')}]`); }
}
/* chaves usadas no motor, no formato t('chave'), precisam existir (as dinâmicas, como t('sh_' + x), são conferidas por prefixo) */
const src = fs.readFileSync(path.join(__dirname, '..', 'src', 'engine.js'), 'utf8');
const used = new Set([...src.matchAll(/\bt\('([A-Za-z_-]+)'\)/g)].map(m => m[1]));
const unknown = [...used].filter(k => !all.has(k));
if (unknown.length) { bad++; console.log('chaves usadas no engine.js e ausentes no dicionário: ' + unknown.join(', ')); }
for (const pre of ['sh_', 'th_']) if (![...all].some(k => k.startsWith(pre))) { bad++; console.log('nenhuma chave com prefixo ' + pre); }
console.log(bad ? 'FALHOU' : `ok: ${langs.length} idiomas, ${all.size} chaves em cada um, ${used.size} chaves usadas no motor`);
process.exit(bad ? 1 : 0);
