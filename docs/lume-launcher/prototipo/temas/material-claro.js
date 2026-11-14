/* Tema Material 3 (claro): herda forma, tamanho e posições do escuro e troca só os papéis de cor
   pelo esquema claro de referência (baseline). Exemplo de uso de "extends". */
Lume.themes.register({
  id: 'material-claro', name: 'Material 3 · Claro', extends: 'material-escuro',
  description: 'Material Design 3 no esquema claro. Mesmas formas e posições do escuro; só as cores mudam. Bom ao sol.',
  tokens: {
    'bg': '#FEF7FF', 'fg': '#1D1B20', 'muted': '#49454F',
    'accent': '#6750A4', 'accent-fg': '#FFFFFF',
    'overlay': '#0000005a', 'logo-set': 'white', 'logo-filter': 'brightness(0)',   /* ícones chapados, pretos */
    'icon-bg': '#ECE6F0', 'icon-fg': '#1D1B20', 'icon-sel-bg': '#EADDFF', 'icon-sel-fg': '#21005D',
    'tile-bg': '#F3EDF7', 'tile-bg-sel': '#E6E0E9', 'tile-bg-opaque': '#F3EDF7',
    'panel-bg': '#ECE6F0', 'panel-bg-opaque': '#ECE6F0',
    'sel-bg': '#E8DEF8', 'sel-fg': '#1D192B',
    'toast-bg': '#322F35', 'toast-fg': '#F5EFF7'
  }
});
