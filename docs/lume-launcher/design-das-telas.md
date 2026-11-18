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

## Cartão, menu do sistema pelo Fn, brilho e relato da falha (change `device-fixes`, tarefa 4.1; D5, D8, D11, D12, D19)

Protótipo: `prototipo/index.html`. Parâmetros da URL (somados aos de cima): `&tela=sys|sys-grid|sys-sheet|sys-reboot|sys-power|hold|set|set-games|card|card-act|card-running|card-ok|card-fail|card-check|bri|bri-act|reset|edge|report` e `&cartao=idle|running|ok|fail`. Na barra de ferramentas: "Cartão" (estado do Otimizar), Fn toque, Fn segurar (segure o botão do mouse), Fn+Vol ▲▼ e Fn+Select. Teclas: F1 (toque curto = menu do sistema; segurar 500 ms = dica), F2/F3 = Fn+Volume, F4 = Fn+Select.
- **Menu do sistema (D19):** um toque no Fn abre, por cima de qualquer tela ou folha (Dock, grade, Configurações, folha de jogo aberta); outro toque no Fn ou B fecha e volta exatamente onde estava. Itens: Configurações, Suspender, Reiniciar, Desligar, foco inicial em Configurações. Configurações abre as Configurações e B volta à tela de origem (com a folha, se havia uma); Suspender suspende sem confirmação (qualquer tecla acorda no mesmo lugar); Reiniciar e Desligar abrem a confirmação vertical (a ação em cima, Cancelar embaixo com o foco; só ▲▼ mudam a escolha, ◀▶ não fazem nada, D8).
- **Configurações (D19):** Wi-Fi e Bluetooth (com adaptador), Idioma, Tema, Tela, Volume, Brilho, Sistema, Cartão e Games ("Atualizar listas"), dando a volta em Games; sem Desligar, Suspender e RetroArch. Cartão: A (ou ▶) entra nas duas ações, ▲▼ movem, A executa, B volta; "Verificar no próximo boot" é um pedido, e A de novo o cancela. Brilho: A entra na linha "Recomeçar o aprendizado" e A abre a confirmação (Sim em cima, Cancelar com o foco).
- **Brilho (D12, usuário 2026-11-18):** sem pontinho vermelho; o limite aprendido não aparece na tela, só no registro. Brilho acima do antigo limite continua permitido.

Medido no protótipo a 640x480, escala 1:1, em 2026-11-18, pelos retângulos do DOM (origem no canto superior esquerdo da tela; 1em = 16 px). Quando não diz o idioma, vale para os três.

| Elemento | x | y | largura | altura | Fonte / cor |
| :--- | ---: | ---: | ---: | ---: | :--- |
| Item da lista das Configurações em foco (Cartão y 270,6; Brilho y 214; Games y 299) | 16 | 270,6 | 255,4 | 26,7 | 16,8 px (`1.05em`), `sel-bg` / `sel-fg`; a lista tem 10 itens com Wi-Fi e Bluetooth, passo de 28,5 px |
| Ação "Atualizar listas" (painel Games) | 298,5 | 81,6 | 311,1 | 23,8 | 16 px |
| Menu do sistema: folha (4 itens, pt) | 190,2 | 129,7 | 259,6 | 220,5 | `panel-bg`, raio `radius-panel`, largura mínima 16em, máxima 20em; fundo `overlay` |
| Menu do sistema: título "Menu do sistema" | 204,6 | 144,1 | 230,8 | 32,2 | 22,4 px peso 600 |
| Menu do sistema: item em foco (Configurações) | 204,6 | 179,1 | 230,8 | 39,2 | 20 px, `sel-bg` / `sel-fg`; os demais (Suspender, Reiniciar, Desligar) em y 218,3, 257,5 e 296,7 (passo 39,2) |
| Confirmação de Reiniciar ou Desligar (folha) | 32 | 151,2 | 576 | 177,7 | como a de Desligar de antes: título 22,4 px, pergunta 19,2 px |
| Confirmação: título | 46,4 | 165,6 | 547,2 | 32,2 | "Reiniciar o aparelho" / "Desligar o aparelho" |
| Confirmação: pergunta | 46,4 | 200,5 | 547,2 | 24 | `muted`, 19,2 px |
| Confirmação: a ação ("Reiniciar" ou "Desligar") em cima | 46,4 | 236,1 | 547,2 | 39,2 | 20 px, `fg` |
| Confirmação: "Cancelar" embaixo, com o foco | 46,4 | 275,3 | 547,2 | 39,2 | 20 px, `sel-bg` |
| Rodapé do Dock: dica "Fn Menu" (pt; es "Fn Menú", mesma largura) | 424,2 | 448,5 | 84,5 | 24,8 | 19,2 px `muted`; glifo "Fn" no círculo `hint-bg` / `hint-fg` como o A; terceira dica, depois de ◀▶ e A (rodapé 0 / 441,7, 640 x 38,3) |
| Dica ao segurar o Fn: painel (pt) | 130 | 193,4 | 380 | 93,2 | `panel-bg-opaque`, centrado na tela, 22,4 px; **largura pelo texto** com a fonte do launcher: a linha mais larga mais 2 × 1,1 em (49,28 px); es pela mesma regra (decisão do usuário, 2026-11-18; o navegador media 352,5 em pt e 358,3 em es com a fonte dele) |
| Dica: linha "Fn (toque): Menu do sistema" | 154,6 | 209,1 | 330,7 | 27 | "Fn" em `accent` negrito; x = painel + 1,1 em |
| Dica: linha "Fn+Vol: Brilho" | 154,6 | 243,9 | 330,7 | 27 | "Fn+Vol" em `accent` negrito |
| Painel Cartão | 284,2 | 44,1 | 339,8 | 391,2 | `panel-bg`, padding 9,6 / 14,4 px |
| Título "Cartão" | 298,5 | 53,7 | 311,1 | 22,1 | 19,2 px peso 600 |
| Linha "Espaço livre" (idem "Última otimização" +23,8, "Última verificação" +47,6) | 298,5 | 81,6 | 311,1 | 23,8 | 16 px; rótulo `muted`, valor `fg`; "boot N" ou "nunca" (en "boot N"/"never", es "arranque N"/"nunca") |
| Ação "Otimizar agora" | 298,5 | 155,4 | 311,1 | 23,8 | 16 px, em foco `sel-bg`; estado à direita: vazio (ocioso), "Otimizando…", "✓ 1,2 GB liberados", "Cartão sem suporte" (falha, `#ff8a80` fora do foco) |
| Ação "Verificar no próximo boot" (es "Verificar al arrancar") | 298,5 | 181,6 | 311,1 | 23,8 | 16 px; "✓ Agendada" (en "✓ Scheduled", es "✓ Pedida") depois de A; uma linha nos três idiomas |
| Painel Brilho: valor "80%" | 298,5 | 81,6 | 311,1 | 28,1 | 25,6 px negrito |
| Barra do Brilho | 298,5 | 112,1 | 311,1 | 8,8 | 8,8 px de altura, trilho `muted` a 30%, preenchimento `accent` |
| Linha "Recomeçar o aprendizado" (a barra não tem marca) | 298,5 | 126,5 | 311,1 | 23,8 | 16 px, em foco `sel-bg` |
| Confirmação de recomeçar (folha) | 32 | 151,2 | 576 | 177,7 | título 22,4 px, pergunta 19,2 px |
| "Sim" (em cima) | 46,4 | 236,1 | 547,2 | 39,2 | 20 px, `fg` |
| "Cancelar" (embaixo, com o foco) | 46,4 | 275,3 | 547,2 | 39,2 | 20 px, `sel-bg` |
| Linha de brilho da borda (Fn+Volume), nível 8: caixa | 11,2 | 120,8 | 31,6 | 238,4 | `panel-bg-opaque`, some depois de 1,6 s |
| Número do nível | 20,8 | 128,8 | 12,4 | 24 | 19,2 px negrito |
| Trilho da linha | 21,4 | 159,2 | 11,2 | 192 | `muted` a 30%; preenchimento `accent` de baixo para cima (nível 8 = 153,6 px) |
| Linha curta do relato (Fn+Select), pt "Falha registrada" | 212,5 | 365,7 | 215 | 47,2 | toast do tema (22,4 px, `toast-bg` / `toast-fg`), como o aviso de bateria fraca |
| Relato, es "Fallo registrado" | 215,3 | 365,7 | 209,3 | 47,2 | idem |

Regras desenhadas:
- **Menu do sistema:** a camada fica acima de tudo (menos do aviso curto), com a entrada antes do resto; ao fechar, a tela de baixo está como estava (a grade com o mesmo jogo, a folha do jogo aberta). A dica de segurar o Fn é ignorada com o menu aberto, some ao soltar o Fn e quando chega um evento de brilho.
- **Recomeçar:** confirmada, aparece o aviso "Aprendizado recomeçado"; o limite só mexe no registro (D12 sem pontinho). Se a revisão pós-E4 tirar o limite, a linha "Recomeçar o aprendizado" sai junto (`resetLearn`, `resetAsk`, `yesNo`, `resetDone` no `i18n.js` e `briPanel`/`askReset` no `engine.js`).
- **Suspender:** só no menu do sistema, sem confirmação.

| Aprovação do usuário no navegador a 640x480 | aprovado em 2026-11-18 (menu do sistema pelo Fn, dicas do Fn, Configurações sem Desligar, Suspender e RetroArch, Brilho sem pontinho, Cartão, relato) |
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
