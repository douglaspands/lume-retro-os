# Design das telas

> Requisitos do usuário, 2026-11-14.

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

| Aprovação do usuário no navegador a 640x480 | pendente |
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
