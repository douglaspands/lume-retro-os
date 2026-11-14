/* lume-launcher · registro de temas.
   Um tema é DADO, não código: um objeto com tokens (cores, formas, posições) e flags de recurso.
   O motor nunca conhece um tema específico; só chama Lume.themes.apply(elemento, id).
   Este é o rascunho do futuro formato de tema (ver nota "Formato de tema"): quando o formato virar
   arquivo (TOML/JSON), basta um carregador que chame register() com o conteúdo lido.

   Definição:
     { id, name, description, extends?: 'outro-id',
       tokens:   { ...só o que muda... },
       features: { lite?: true }   // força o modo lite (sem transparência e sem animação)
     }
*/
(function () {
  'use strict';
  const Lume = (window.Lume = window.Lume || {});

  /* Todos os tokens existentes, com valores padrão. Todo tema herda isto (e/ou de outro tema),
     então um tema pode declarar só o que muda. Unidades "em": 1em = 1/40 da largura de 640x480. */
  const DEFAULTS = {
    /* cenário */
    'bg': '#14161a', 'bg-image': 'none', 'fg': '#f0f0f0', 'muted': '#9aa0aa',
    'accent': '#4cc2ff', 'accent-fg': '#001018', 'font': 'system-ui, sans-serif',
    'radius': '.8em', 'label-case': 'none', 'label-weight': 700, 'overlay': '#000a',
    /* formas (por padrão derivam de 'radius'; um tema pode fixar cada uma) */
    'radius-icon': 'var(--radius)', 'radius-tile': 'calc(var(--radius) * .6)', 'radius-panel': 'var(--radius)', 'radius-item': 'calc(var(--radius) / 2.5)',
    /* grade de jogos: poucas capas e grandes, por causa dos 3,5" */
    'cols': 4, 'rows': 2,
    /* logos de console: 'white' (monocromático, para fundos escuros) ou 'color' (marca original, para fundos claros) */
    'logo-set': 'white',
    /* filtro aplicado aos logos. 'none' mantém o arquivo como está; 'brightness(0) invert(1)' achata tudo em branco puro;
       'brightness(0)' achata em preto puro. Dá ícones chapados de uma cor só, sem depender do arquivo original. */
    'logo-filter': 'none',
    /* seleção em listas e avisos */
    /* rodapé: botões de letra (A, B, X, Y) na cor de destaque; setas (◀▶ ▲▼) na cor tonal do tema, sem inverter */
    'hint-bg': 'var(--accent)', 'hint-fg': 'var(--accent-fg)',
    'nav-bg': 'var(--sel-bg)', 'nav-fg': 'var(--sel-fg)',
    'sel-bg': 'var(--accent)', 'sel-fg': 'var(--accent-fg)', 'toast-bg': 'var(--accent)', 'toast-fg': 'var(--accent-fg)',
    /* dock (números sem unidade são multiplicadores) */
    /* efeito de ampliação do Dock (como o do macOS): o ícone em foco cresce 'mag-peak' vezes, os vizinhos crescem menos
       (curva gaussiana de largura 'mag-spread', em ícones) e os distantes ficam em 'mag-base'. 'icon' é o tamanho de repouso. */
    'icon': '5.8em', 'dock-gap': .6, 'mag-peak': 1.5, 'mag-base': .8, 'mag-spread': .8, 'dock-top': '45%',
    'icon-bg': '#2a2f38', 'icon-fg': '#fff', 'icon-border': '0', 'icon-shadow': 'none',
    'icon-sel-bg': 'var(--icon-bg)', 'icon-sel-fg': 'var(--icon-fg)',
    'icon-sel-border': '0', 'icon-sel-shadow': '0 0 0 .18em var(--accent)',
    /* grade de jogos e painéis */
    'tile-bg': '#ffffff18', 'tile-bg-sel': '#ffffff30', 'tile-bg-opaque': '#22262c', 'tile-border': '0',
    'panel-bg': '#1b1f25e6', 'panel-bg-opaque': '#1b1f25', 'panel-border': '0',
    /* efeitos (desligados no modo lite) */
    'blur': 'none', 't': '.2s'
  };

  const registry = new Map();

  function register(def) {
    if (!def || !def.id || !def.name) { console.warn('[lume] tema inválido: precisa de id e name', def); return; }
    const unknown = Object.keys(def.tokens || {}).filter(k => !(k in DEFAULTS));
    if (unknown.length) console.warn(`[lume] tema "${def.id}": tokens desconhecidos ignorados:`, unknown.join(', '));
    registry.set(def.id, def);
  }

  /* resolve a cadeia de herança: DEFAULTS ← pai ← tema */
  function resolve(id, depth) {
    const def = registry.get(id); if (!def) return null;
    if ((depth || 0) > 8) { console.warn('[lume] herança circular em', id); return { ...def, tokens: { ...DEFAULTS }, features: {} }; }
    const parent = def.extends ? resolve(def.extends, (depth || 0) + 1) : null;
    const base = parent ? parent.tokens : DEFAULTS;
    const tokens = { ...base };
    for (const k in (def.tokens || {})) if (k in DEFAULTS) tokens[k] = def.tokens[k];
    return { id: def.id, name: def.name, description: def.description || '', tokens, features: { ...(parent ? parent.features : {}), ...(def.features || {}) } };
  }

  /* aplica os tokens como variáveis CSS (--nome) no elemento raiz da tela */
  function apply(el, id) {
    const th = resolve(id) || resolve([...registry.keys()][0]); if (!th) return null;
    for (const k in DEFAULTS) el.style.setProperty('--' + k, String(th.tokens[k]));
    return th;
  }

  Lume.themes = {
    DEFAULTS, register, resolve, apply,
    list: () => [...registry.values()].map(d => ({ id: d.id, name: d.name, description: d.description || '' }))
  };
})();
