# Design das telas

> Requisitos do usuário, 2026-11-14.

## Regra de toda confirmação (usuário, 2026-11-17)
- Em todo pedido de confirmação do sistema (launcher, menu do Lume, e o que vier), a opção
  afirmativa (Sim, Desligar, ...) fica **em cima**, ou **à esquerda** quando as opções ficam lado
  a lado. A opção segura (Não, Cancelar) fica embaixo ou à direita e **começa com o foco**.

## Tela principal: Dock de consoles
- Ícones **quadrados** com o logo de cada console.
- **Rotação infinita**: depois do último volta ao primeiro, e vice-versa.
- O **último item do anel é Configurações** do aparelho.
- **Favoritos** também é um item do Dock, funcionando como um "console" que reúne os jogos favoritos de todos os sistemas.
- Navegação: D-pad esquerda/direita gira o Dock, A entra no item.

## Tela de jogos
- Grade de **quadrados semitransparentes** com a **imagem da caixa** do jogo.
- A grade deixa o fundo (do tema) aparecer por trás.
- Navegação pelo D-pad, B volta ao Dock.

## Ao selecionar um jogo (A)
Menu sobre o jogo, com:
1. **Iniciar**
2. **Iniciar a partir de um save state** (lista os slots existentes)
3. **Incluir em favoritos** (ou remover)

## Impactos de performance (ver [Orçamento de performance](orcamento-de-performance.md))
- **Transparência** exige mistura de pixels (alpha blending) em toda a grade, o que pesa em GPUs fracas. Mitigar: transparência só no fundo do quadrado, caixas pré-compostas em tamanho final, e opção de desligar no nível "lite" do tema.
- **Caixas de jogo**: miniaturas pré-escaladas para o tamanho do quadrado, geradas pela ferramenta de build/scraper. Só as visíveis ficam na RAM (cache LRU).
- **Rotação infinita**: só desenha os itens visíveis, sem criar elementos extras para o loop.

## Barra de status: marca de carga e aviso de bateria fraca (change `game-governor`, D9, P-78)

Medido no protótipo (`prototipo/index.html`) a 640x480, escala 1:1 (px da tela do aparelho), em 2026-11-17, pelos retângulos do DOM (`getBoundingClientRect` dividido pela escala do palco). Origem no canto superior esquerdo da tela. A régua da `lume-ui` (tarefa 3.2) usa estes valores.

**Como ver os estados** (servir a pasta `prototipo/` por HTTP local, por exemplo `python -m http.server --directory docs/lume-launcher/prototipo`, ou abrir o `index.html`): parâmetros da URL `?bat=<0-100>&carga=charging|discharging|full&idioma=pt-BR|en|es&tema=<id>&res=640x480`, ou os controles "Bateria" da barra de ferramentas (nível, estado e o botão "Aviso 5%", que força o aviso).

| Elemento | x | y | largura | altura | Fonte / cor |
| :--- | ---: | ---: | ---: | ---: | :--- |
| Barra de status | 0 | 0 | 640 | 37,4 | 19,2 px (`--fs-s`), padding 6,7 / 17,3 px |
| Grupo da bateria (ícone + texto), 82% | 533,2 | 6,7 | 89,5 | 24,0 | cor `--fg` do tema, espaço entre os dois 6,7 px |
| Ícone da bateria | 533,2 | 9,6 | 39,1 | 18,2 | viewBox 30x14, 1 unidade = 1,3 px |
| Texto da porcentagem, 82% | 579,0 | 6,7 | 43,7 | 24,0 | 19,2 px, números tabulares |
| Marca de carga (raio) dentro do ícone | 546,8 | 13,0 | 9,5 | 11,5 | cor `--fg`, contorno de 1,1 unidade na cor `--bg` do tema |
| Aviso de bateria fraca (toast), en | 214,0 | 365,7 | 212,0 | 47,2 | 22,4 px (`--fs-m`), fundo `toast-bg` e texto `toast-fg` do tema, 4 s |
| Aviso, pt-BR ("Bateria fraca 5%") | centrado | 365,7 | 221,5 | 47,2 | idem |
| Aviso, es ("Batería baja 5%") | centrado | 365,7 | 211,2 | 47,2 | idem |

Regras desenhadas e conferidas:
- **A marca não desloca o texto:** o raio é desenhado dentro do corpo do ícone; a largura do texto e a do grupo são iguais carregando, descarregando e cheia (82%: 43,7 e 89,5 px; 100%: 56,2 e 102,0 px; 5%: 31,3 e 77,1 px).
- **Legível nos temas claro e escuro:** o raio usa a cor do texto e um contorno na cor do fundo do tema, então aparece sobre a parte cheia e sobre a vazia (escuro: raio `#E6E0E9` com contorno `#141218`; claro: raio `#1D1B20` com contorno `#FEF7FF`). O seletor do protótipo lista só os dois temas Material; o mecanismo usa `--fg` e `--bg`, que todo tema define.
- **Cheia (100% com `full`):** sem raio, só o ícone cheio; o protótipo e o tema não têm um desenho próprio para "cheia".
- **Aviso:** o toast curto que o tema já tem (posição, fonte e cores dos outros avisos), uma vez por descarga em 5% ou menos (`Descarregando`), de novo só depois de carregar ou subir acima de 5%. Textos: "Bateria fraca N%", "Low battery N%", "Batería baja N%".

| Aprovação do usuário no navegador a 640x480 | aprovado em 2026-11-17 (raio 9,5x11,5 px no ícone, cheia sem raio, temas Material, aviso de 4 s) |
| :--- | :--- |

## Sobre o jogo: menu do Lume, dica dos acordes e barra de status (change `lume-hud-actions`, D6, D10, D13)

Protótipo: `prototipo/jogo.html` (telas do sistema sobre um jogo de exemplo desenhado com blocos, sem arte de terceiros). Parâmetros: `?tema=lume|material-escuro|material-claro&idioma=pt|en|es&tela=menu|confirm|confirm-reset|silent|native|hint|hud|hud-charging|game&barra&foco=N&limpo` (`limpo` deixa só a tela de 640x480, para a captura). No navegador: F1 tocado abre e fecha o menu, F1 segurado 500 ms mostra a dica, setas, Enter = A, Esc = B, como a máquina de estados do `lume-run` (`menu.rs`). O tema `lume` é o da imagem (`themes/base.toml`, os `DEFAULTS` de `src/themes.js`).

Medido nas capturas de 640x480 (Chromium headless, `?limpo`), em 2026-11-17, origem no canto superior esquerdo; 1em = 16 px. O widget do RetroArch (patch 0012) usa as cores dos tokens e estas proporções; os tamanhos de fonte dele vêm das fontes de widget do RetroArch e são comparados com esta tabela pela captura (`lume dev shot`), na VM e depois no aparelho.

| Elemento | x | y | largura | altura | Fonte / cor |
| :--- | ---: | ---: | ---: | ---: | :--- |
| Fundo do menu (jogo pausado) | 0 | 0 | 640 | 480 | `overlay` (`#000000aa`) |
| Painel do menu, 4 itens (pt) | 163 | 102 | 313 | 276 | `panel-bg-opaque`, raio `radius-panel`, largura mínima 300 px, padding 0 / 8 / 20 px |
| Título (nome do jogo ou pergunta) | 175 | 102 | 290 | 58 | 22,4 px (`--fs-m`) peso 600, `fg`; linha de 1 px `muted` a 35% embaixo |
| Item em foco | 171 | 170 | 298 | 46 | 20 px, fundo `sel-bg`, texto `sel-fg`, raio `radius-item` |
| Demais itens (passo) | 171 | +47,6 | 298 | 46 | 20 px, `fg` |
| "Forçar fechamento" | idem | idem | idem | idem | texto `#ff8a80` fora do foco |
| Dicas A/B no rodapé | centrado | 443 | — | 24 | 19,2 px, como o rodapé do launcher |
| Painel da dica, 6 acordes (pt) | 176 | 104 | 287 | 272 | `panel-bg` (transparente: o jogo continua), borda de cima 3 px `accent`, padding 16 px |
| Linha da dica | 192 | +39,6 | — | 39,6 | botão 17,6 px negrito `accent`, ação 17,6 px `fg`, 20 px entre as colunas |
| Barra de status | 0 | 0 | 640 | 28 | 16 px, fundo preto a 60%, padding 8 px; por grupo (`CPU`, `GPU`, `MEM`, `BAT`): rótulo em negrito na cor `accent`, valores em `fg`, divisória de 1 px `muted` a 60% entre os grupos (escolha do usuário, 2026-11-17) |

Regras desenhadas:
- **Menu:** confirmação com Sim em cima e Não embaixo, com o foco no Não; o título vira a pergunta. App sem resposta: o título diz "RetroArch não responde" e "Forçar fechamento" entra por último, já em foco. Port: só Voltar ao jogo e Encerrar jogo.
- **Dica:** uma linha por acorde que o runner declara, mais Fn+Start; some ao soltar o Fn. O jogo segue rodando por baixo, por isso o painel é transparente e não há fundo escurecido.
- **Barra:** só texto, sem ícones, em uma linha; com o menu aberto ela continua visível por cima do fundo escurecido.

| Aprovação do usuário no navegador a 640x480 | aprovado em 2026-11-17 (capturas do protótipo e da vm; ordem do menu: Voltar ao jogo, Encerrar jogo, Reiniciar, Menu do RetroArch) |
| :--- | :--- |

## Pontos técnicos a verificar
- **Save states**: dependem do emulador. No RetroArch os estados ficam em slots; é preciso confirmar como iniciar já carregando um slot (opção de linha de comando ou configuração) e como o dArkOS organiza os arquivos. Emuladores standalone podem não ter isso.
- **Capas**: vêm do `gamelist.xml` do ES (`<image>`), não do formato do RetroArch. Detalhes em [Gamelist e capas](gamelist-e-capas.md).
- **Configurações do aparelho**: o que existe no dArkOS (Wi-Fi, volume, brilho, bateria) e como o launcher chama essas funções.
- **Ícones de console**: pacote de logos quadrados, com licença livre ou criado por nós.

## Decisões em aberto
- Favoritos guardam o caminho da ROM. Se a ROM for movida, o favorito quebra; definir como tratar.
- A tela de Configurações é do launcher ou chama a do dArkOS?

Voltar: [Visão geral](visao-geral.md)
