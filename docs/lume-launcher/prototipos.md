# Protótipos do lume-launcher

Protótipos em HTML, só para validar telas, navegação e temas. O app real será em Rust + SDL2 ([Opções de tecnologia](opcoes-de-tecnologia.md)).

## Versões
Cada versão é uma pasta com o timestamp de criação (`AAAAMMDD-HHMMSS`). A mais recente é a que vale; as anteriores ficam como histórico.

| Pasta | O que tem |
| :--- | :--- |
| `20261114-015430` | Pasta original. Foi editada no lugar durante o desenvolvimento, então hoje tem o mesmo conteúdo da versão abaixo; não é um retrato da primeira versão |
| `20261114-022116` | Snapshot: Material 3 (escuro e claro), catálogo real da coleção, layout para 3,5″, save states reais com miniatura |
| `20261114-022442` | Logos de marca chapados (branco no escuro, preto no claro), bateria horizontal, sem relógio, Dock com ícones maiores, Configurações compacta e sem modo desempenho, nova tela **Capturas** (imagens do RetroArch) |
| `20261114-033157` | **CANDIDATO** (ver `CANDIDATO.md` na pasta). Igual à 032837, mas com os botões de letra (A, B, X, Y) de volta à cor de destaque do tema e as setas (◀▶ ▲▼) em chip tonal do tema, sem inverter. |
| `20261114-032837` | Baseada na 030031: Dock sem os pontinhos e com ícones maiores (foco 10,8em, antes 9,3em) e efeito de ampliação melhorado; botões do rodapé brancos no tema escuro e escuros no claro. Cores do rodapé ajustadas na 033157. |
| `20261114-030031` | Busca por nome na lista de jogos (teclado na tela) e L1/R1 com salto grande que acelera |
| `20261114-025342` | Anterior. Emulador/core, aspecto e shader em 3 camadas (jogo → console → padrão do sistema), opções do console (tecla Y), selo ⚙ nos jogos com exceção e save states por core. Ver [Emuladores por console e por jogo](emuladores-por-console-e-por-jogo.md) |
| `20261114-024403` | Anterior. Tema escolhido nas Configurações, menu do jogo com emulador/core, aspecto e shader, Dock com ampliação estilo macOS, Configurações com texto menor, 3 idiomas conferidos por script, layout responsivo a qualquer tela |
| `20261114-023109` | Só com os 2 temas Material. Navegador de **Arquivos** (abre imagens e .txt), capa em destaque no menu do jogo, save states de demonstração, Sistema com estatísticas ao selecionar, **Desligar o aparelho** no lugar de "desligar tela" |

A partir daqui, mudanças novas vão numa pasta nova com timestamp, sem editar as anteriores.

> **Candidato oficial: `20261114-033157`.** É a referência para o app real; o que falta verificar está em `prototipo/CANDIDATO.md`.

## Como abrir
Abrir no navegador: `prototipo/index.html` (o candidato; as versões anteriores não foram copiadas para o repositório).
Trocar de tema na barra superior ou com a tecla **T**. Também aceita `index.html?tema=material-claro`.

## Controles
| Ação | Teclado | Gamepad |
| :--- | :--- | :--- |
| Navegar | Setas | D-pad |
| A (selecionar) | Enter ou Z | A |
| B (voltar) | Esc, Backspace ou X | B |
| Próximo tema | T | |

A barra superior também tem: resolução simulada (640x480, 480x320, 720x720…), liga/desliga dos dongles Wi-Fi e Bluetooth (os menus somem sem dongle) e modo lite forçado.

## O que está implementado
- Dock de ícones quadrados com rotação infinita; Favoritos no início e Configurações no último item ([Design das telas](design-das-telas.md))
- Grade de jogos com quadrados semitransparentes e caixas geradas
- Menu do jogo: Iniciar, Iniciar de um save state (lista de slots; desabilitado se não há saves) e Favoritar
- Configurações: Wi-Fi e Bluetooth (condicionais), idioma (muda de verdade), volume, brilho, Sistema com CPU e memória simulados e desligar tela ([Configurações](configuracoes.md)); o modo desempenho foi removido
- 5 temas: Aurora, Neon, Papel, Game Boy e Lite

## Arquitetura modular (pensada para trocar de tema)
```
index.html          carrega os módulos e os temas
base.css            estrutura; só lê variáveis CSS, nunca cores fixas
src/themes.js       registro de temas: register, resolve (com herança), apply
src/engine.js       UI e navegação; não conhece nenhum tema, dado ou ferramenta do sistema
src/data.js         consoles, jogos e caixas (no app real: scanner de ROMs)
src/system.js       fronteira com o aparelho, simulada (no app real: Wi-Fi, Bluetooth, /proc, /sys)
src/i18n.js         idiomas
temas/<id>.js       um arquivo por tema, só dados
```
Regras que mantêm isso trocável:
1. O motor só chama `Lume.themes.apply(elemento, id)`; nunca menciona um tema pelo nome.
2. Um tema é um objeto de dados (tokens + flags), sem código. Tema novo = arquivo novo + uma linha no `index.html`.
3. Tokens ausentes herdam de `DEFAULTS` ou do tema indicado em `extends`. Token desconhecido gera aviso no console.
4. A fronteira com o aparelho fica em `system.js`; trocar o simulado pelo real não mexe nas telas.

## Relação com o formato de tema
O objeto de `temas/*.js` e a lista de tokens em `src/themes.js` (`DEFAULTS`) são o rascunho do [Formato de tema](formato-de-tema.md). Quando o formato virar arquivo (TOML ou JSON), um carregador chama `register()` com o conteúdo lido.

## Dados reais da sua coleção
`tools/build-catalog.js` lê a pasta de ROMs (`gamelist.xml`, `img/`, `savestates/`) e gera `catalog.js`. É o embrião do scanner de ROMs com índice em cache.
```
asdf exec node tools/build-catalog.js <pasta-das-roms> [--logos=<pasta-de-logos>]
```
- Resultado atual: 17 sistemas, 5.383 jogos, capas reais e save states reais (com miniatura e data).
- O build valida a assinatura das capas: **186 arquivos `.png` não são imagem** (180 no SNES; são arquivos de texto com extensão `.png`). O launcher usa uma caixa gerada no lugar. Vale refazer o scraping desses jogos.
- Save states: lê `<rom>.state`, `.stateN` e `.state.auto`. Os de subpastas por núcleo (ex.: `savestates/snes/Snes9x/`) não são lidos; falta decidir se importam.
- O Chrome bloqueia `file://` em automações; para ver pelo servidor, gerar com `--base=http://127.0.0.1:8001/` e servir as ROMs nessa porta.

## Logos, bateria e Capturas (versão 022442)
- **Logos de marca:** o gerador copia os SVG de um tema de EmulationStation (`--logos=<pasta>`, com subpastas `white_logo/` e `color_logo/`) para `assets/logos/`, que fica fora do git. 16 dos 17 sistemas têm logo; o `love` usa a sigla. Esses são logos de marcas registradas (Nintendo, Sega, Sony…), úteis para uso pessoal; para distribuir o launcher seria preciso rever a licença.
- **Ícones chapados:** token de tema `logo-filter`. O Material escuro usa `brightness(0) invert(1)` (branco puro) e o claro `brightness(0)` (preto puro). Vale para qualquer tema, e `logo-set` escolhe o arquivo (`white` ou `color`).
- **Bateria:** SVG horizontal desenhado com `currentColor`, na cor do texto principal do tema. O relógio foi removido, porque esses aparelhos não guardam a hora. Wi-Fi e Bluetooth só aparecem no topo quando conectados.
- **Capturas:** novo item no Dock, antes de Configurações, que mostra as imagens que o RetroArch salvou em `screenshots/` (hoje 2). Grade 2×2, A abre em tela cheia, ◀▶ troca de imagem. A data vem do nome do arquivo e é a hora do aparelho.

## Navegador de arquivos e outras mudanças (versão 023109)
- **Arquivos** (item do Dock, antes de Capturas): navega pelas pastas de `roms/`. Abre **imagens** e **.txt**; os outros tipos aparecem esmaecidos e mostram um aviso. A abre, B sobe uma pasta (e volta já selecionando a pasta de onde veio), PgUp/PgDn pula uma página. Na imagem, ◀▶ troca entre as imagens da pasta.
- `.txt` acima de 256 KB não é embutido e mostra um aviso (o `gamecontrollerdb.txt` tem 543 KB). Imagens corrompidas mostram "Não foi possível abrir esta imagem".
- A árvore vem de `fs.js` (759 pastas, 14.762 arquivos), gerado pelo mesmo `build-catalog.js`. No app real isto é um `readdir` sob demanda, não um índice em memória.
- **Capa em destaque:** ao abrir um jogo, a capa aparece grande à esquerda do menu e as opções à direita.
- **Save states de demonstração:** inventados para avaliar a tela (cerca de 1 em cada 3 jogos, 1 a 4 slots, com data e miniatura gerada). Marcados como "demo" e desligáveis pela caixa **Save states de demonstração** da barra. Os save states reais continuam valendo quando existem.
- **Sistema:** as estatísticas aparecem só de selecionar o item, sem apertar A, e a leitura para ao sair dele.
- **Desligar o aparelho:** substitui "desligar tela", com confirmação (Cancelar é o padrão).
- **Só os 2 temas Material:** os temas Aurora, Neon, Papel, Game Boy e Lite não estão nesta versão (continuam nas pastas anteriores).

## Versão 024403: opções por jogo, tema, idiomas e responsividade
- **Tema nas Configurações:** item **Tema** (Escuro/Claro), troca na hora com ◀▶ e fica salvo.
- **Menu do jogo** (A num jogo): Iniciar, Iniciar de um save state, **Emulador**, **Aspecto** (Do core ou 4:3), **Shader** e Favoritos. ◀▶ (ou A) troca o valor. As escolhas são **por jogo** e ficam salvas; a tela de abertura mostra o que o runner receberia (core, aspecto e shader).
  - O **Shader** só aparece quando o core é do RetroArch. O PPSSPP, por exemplo, é standalone (a pasta `PPSSPPSDL` dos seus savestates indica isso) e não mostra a opção. A lista de shaders (Nenhum, Scanlines, CRT, LCD, Pixel nítido) é de exemplo; no app real vem dos shaders instalados no RetroArch.
  - **Emuladores:** a lista vem dos cores que aparecem nos seus `savestates/<sistema>/` (confirmados). As **alternativas além disso são prováveis, não confirmadas** no dArkOS (mGBA, PicoDrive, ParaLLEl N64, FinalBurn Neo, melonDS, DeSmuME). Estão marcadas com `*` em `src/data.js`. No app real, a lista vem da configuração de emuladores do sistema.
- **Dock com ampliação estilo macOS:** o ícone em foco cresce 1,5×, os vizinhos crescem menos (curva gaussiana) e empurram os demais, e o foco sobe um pouco. Controlado por tokens do tema (`mag-peak`, `mag-base`, `mag-spread`, `dock-gap`). Quantos ícones aparecem sai da largura da tela.
- **Configurações com texto menor**, para caber nos 3 idiomas. Corrigi também um defeito em que o texto de valores (datas, tamanhos) saía maior do que devia por multiplicação de `em`.
- **Idiomas (pt-BR, en, es):** os 3 dicionários têm as mesmas chaves, conferidas por `node tools/check-i18n.js`, que também verifica se toda chave usada no motor existe. Textos curtos para caber na tela (o espanhol é o mais comprido; testei as Configurações nele).
- **Responsivo:** a interface se adapta ao tamanho e à proporção da tela, não só escala. A grade ganha colunas em telas largas (5 colunas em 854x480) e linhas em telas altas (4×3 em 720x720); o Dock mostra mais ou menos ícones; a lista de arquivos ajusta o número de linhas. A opção **Janela (responsivo)** da barra faz a interface acompanhar o tamanho da janela do navegador em tempo real.

## Versão 030031: busca e navegação rápida na lista de jogos
- **Busca:** botão **X** (mostrado na barra de atalhos; no teclado do PC, `/`) abre um **teclado na tela** (o aparelho só tem gamepad). D-pad escolhe a tecla, A digita, B fecha e aplica. Teclas: letras, números, Espaço, ⌫, Limpar e OK. A contagem de jogos encontrados atualiza a cada letra.
  - O filtro ignora maiúsculas e acentos e exige **todas** as palavras digitadas (ex.: "super mario" acha "Super Mario Bros.").
  - Com busca ativa, o cabeçalho mostra o termo (`Nintendo · "MARIO"`) e o contador passa a valer para o resultado. **B limpa o filtro** antes de sair da lista. Vale também na lista de Favoritos.
  - No protótipo, dá para digitar direto no teclado do PC enquanto o teclado na tela está aberto.
- **L1/R1 (PgUp/PgDn):** o salto é **proporcional ao tamanho da lista** (cerca de 1/16 dela, mínimo uma página) e **acelera** se o botão for repetido em sequência (até 4×). Na lista do NES (979 jogos), um toque salta 64 jogos, e dois toques rápidos saltam 64 + 128. Sem dica na tela, como pedido.

## Versão 032837: Dock maior e rodapé invertido (sobre a 030031)
- **Sem pontinhos** na tela inicial. O espaço foi para o Dock: o ícone em foco cresce de 9,3em para **10,8em** e os 5 ícones visíveis ocupam quase toda a largura (0,4em a 39,6em de 40em).
- **Ampliação estilo macOS melhorada:** tokens do tema `mag-peak` 1,8 (era 1,5), `mag-base` 0,72 e `mag-spread` 0,97, calibrados para os vizinhos ficarem em 8,1em e o 2º vizinho em 5,1em, todos inteiros na tela. A transição ganhou uma leve "mola" (passa um pouco e assenta) e o rótulo do console acompanha o tamanho do foco.
- **Botões do rodapé** (A, B, X, Y, ◀▶, ▲▼) com tokens `hint-bg` e `hint-fg`, por padrão invertidos em relação ao tema: brancos no escuro, escuros no claro. Vale para o Dock, a lista de jogos, as Configurações e as demais telas.

## Versão 033157: cores do rodapé ajustadas
- **Botões de letra** (A, B, X, Y): voltam à cor de destaque do tema, como na 030031 (tokens `hint-bg` e `hint-fg`, agora `accent` e `accent-fg` por padrão).
- **Setas** (◀▶ e ▲▼, como em "Navegar" e "para ajustar"): chip na cor tonal do tema, **sem inverter**: no escuro, chip escuro com símbolo claro; no claro, chip claro com símbolo escuro (tokens `nav-bg` e `nav-fg`, que seguem `sel-bg` e `sel-fg`).
- Mantém o resto da 032837: Dock sem pontinhos, ícones maiores e ampliação melhorada.
- **Modo lite nas Configurações** (adicionado ao candidato depois da oficialização, a pedido): Ligado/Desligado, salvo. Desliga animações, desfoque e fundos translúcidos. Corrigi junto um defeito: o lite não desligava as animações. Detalhes no `CANDIDATO.md`.

## Tema Material 3
`temas/material-escuro.js` e `temas/material-claro.js` (o claro estende o escuro e só troca as cores). Mapeamento dos papéis de cor M3 para tokens está comentado no topo do arquivo. Base: [m3.material.io](https://m3.material.io/). Usa elevação por tom, não sombra nem desfoque, então é barato. Fonte Roboto com fallback do sistema; no aparelho a fonte precisa ser empacotada.

## Tela de 3,5″ (regras que guiam o layout)
640x480 em 3,5″ são cerca de 229 ppi (~71 x 53 mm). Texto de 16 px tem ~1,8 mm de altura e não lê a distância de braço.
- Escala tipográfica com piso de ~19 px (`--fs-s` 1,2em, `--fs-m` 1,4em, `--fs-l` 1,75em, `--fs-xl` 2,1em).
- Grade de **4 colunas x 2 linhas** (8 capas grandes), definida pelo tema (`cols`, `rows`).
- Dock com **5 ícones visíveis**, sem texto pequeno dentro do ícone; o nome vai no rótulo grande abaixo.
- Telas de lista/grade sem barra superior separada: relógio e contador no cabeçalho.
- Painel Sistema com poucas linhas (modelo, CPU, memória, RSS do launcher, cartão SD).
- Salto de página (PgUp/PgDn, ou L1/R1) para listas de centenas de jogos.
- A barra do protótipo tem **Tamanho real 3,5″** com o ppi do seu monitor, para avaliar a legibilidade no tamanho físico aproximado.

## Limites do protótipo
- Os valores de CPU e memória são simulados.
- Sem capa válida, a caixa é gerada (SVG).
- Não foi medido consumo real: o navegador não representa o R36S. Serve para decidir visual e fluxo.
- Não verifiquei o tema claro, os outros temas, nem a tela de Configurações no navegador depois da mudança de escala.

Voltar: [Visão geral](visao-geral.md)
