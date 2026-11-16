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

## Pontos técnicos a verificar
- **Save states**: dependem do emulador. No RetroArch os estados ficam em slots; é preciso confirmar como iniciar já carregando um slot (opção de linha de comando ou configuração) e como o dArkOS organiza os arquivos. Emuladores standalone podem não ter isso.
- **Capas**: vêm do `gamelist.xml` do ES (`<image>`), não do formato do RetroArch. Detalhes em [Gamelist e capas](gamelist-e-capas.md).
- **Configurações do aparelho**: o que existe no dArkOS (Wi-Fi, volume, brilho, bateria) e como o launcher chama essas funções.
- **Ícones de console**: pacote de logos quadrados, com licença livre ou criado por nós.

## Decisões em aberto
- Favoritos guardam o caminho da ROM. Se a ROM for movida, o favorito quebra; definir como tratar.
- A tela de Configurações é do launcher ou chama a do dArkOS?

Voltar: [Visão geral](visao-geral.md)
