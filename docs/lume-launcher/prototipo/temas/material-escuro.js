/* Tema Material 3 (escuro), baseado em m3.material.io com o esquema de cores de referência (baseline).
   Mapeamento dos papéis de cor M3 para os tokens do lume-launcher:
     surface                    → bg
     surface-container(-high)   → tile-bg, icon-bg, panel-bg          (elevação por TOM, não por sombra)
     primary                    → accent        on-primary → accent-fg
     primary-container          → icon-sel-bg   on-primary-container → icon-sel-fg
     secondary-container        → sel-bg        on-secondary-container → sel-fg
     on-surface / on-surface-variant → fg / muted
     inverse-surface            → toast-bg      inverse-on-surface → toast-fg
   Formas M3: extra-large 28dp (painéis e ícones), medium 12dp (capas), full (itens de lista).
   Ajustes para 3,5": rótulos grandes, só 2 linhas de capas, só 5 ícones visíveis no Dock. */
Lume.themes.register({
  id: 'material-escuro', name: 'Material 3 · Escuro',
  description: 'Material Design 3: cores por papel (primary, surface-container…), formas arredondadas e elevação por tom. Sem desfoque nem transparência, barato para o aparelho.',
  tokens: {
    'bg': '#141218', 'fg': '#E6E0E9', 'muted': '#CAC4D0',
    'accent': '#D0BCFF', 'accent-fg': '#381E72',
    'font': 'Roboto, "Segoe UI", system-ui, sans-serif', 'label-weight': 400,
    'radius': '1.75em', 'radius-icon': '1.75em', 'radius-tile': '.75em', 'radius-panel': '1.75em', 'radius-item': '2em',
    'overlay': '#000000a8',
    'logo-set': 'white', 'logo-filter': 'brightness(0) invert(1)',          /* ícones chapados, brancos */
    /* ampliação estilo macOS: foco ~10,8em (era ~9,3), vizinhos ~8em, 2º vizinho ~5em; cabem 5 ícones inteiros na tela de 40em */
    'icon': '6em', 'dock-gap': .5, 'mag-peak': 1.8, 'mag-base': .72, 'mag-spread': .97, 'dock-top': '38%',
    'icon-bg': '#2B2930', 'icon-fg': '#E6E0E9', 'icon-border': '0', 'icon-shadow': 'none',
    'icon-sel-bg': '#4F378B', 'icon-sel-fg': '#EADDFF', 'icon-sel-border': '0', 'icon-sel-shadow': 'none',
    'tile-bg': '#211F26', 'tile-bg-sel': '#2B2930', 'tile-bg-opaque': '#211F26', 'tile-border': '0',
    'panel-bg': '#2B2930', 'panel-bg-opaque': '#2B2930', 'panel-border': '0',
    'sel-bg': '#4A4458', 'sel-fg': '#E8DEF8',
    'toast-bg': '#E6E0E9', 'toast-fg': '#322F35',
    'cols': 4, 'rows': 2, 'blur': 'none', 't': '.2s'
  }
});
