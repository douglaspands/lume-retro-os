# Emulador/core por console e por jogo

> Decisão de 2026-11-14, implementada no protótipo `20261114-025342` ([Protótipos](prototipos.md)).

## Problema
Alguns jogos rodam melhor em um core específico, então o emulador precisa ser trocável **por jogo**. Mas escolher jogo a jogo é inviável para centenas de ROMs, então também precisa de um **padrão por console**.

## Solução: 3 camadas, da mais específica para a mais geral
1. **Jogo**: o que foi mudado naquele jogo.
2. **Console**: o padrão do console inteiro.
3. **Padrão do sistema**: o 1º core da lista do console.

O jogo só guarda o que foi alterado. O resto **herda**, então trocar o padrão do console vale para todos os jogos que não têm exceção, e quem tem exceção continua como está.

Vale para as três opções: **emulador/core**, **aspecto** (do core ou 4:3) e **shader** (só em core do RetroArch).

## Como se usa
- **Console:** na lista de jogos, tecla **Y** (no teclado, `Y`) abre as "Opções do console", com logo em destaque. ◀▶ troca o valor. Há também "Limpar opções dos jogos", que apaga todas as exceções daquele console (mostra quantas são).
- **Jogo:** A no jogo abre o menu. Cada opção mostra **"Padrão (valor herdado)"** ou o valor próprio, **em destaque**. ◀▶ percorre `Padrão, valor 1, valor 2…`; voltar a "Padrão" apaga a exceção.
- **Selo ⚙** no canto da capa marca na grade os jogos com opção própria, para saber o que foi customizado.
- A tela de abertura mostra o que o runner receberia (core, aspecto, shader).

## Save state é do core (achado nos seus dados)
Os seus `savestates/` já estão organizados por core (`savestates/snes/Snes9x 2005 Plus/…`, `savestates/gba/gpSP/…`), além de cópias soltas na raiz. Um save de um core **não funciona em outro**, então:
- "Iniciar de um save state" lista **só os saves do core efetivo**.
- Se o jogo tem saves em outro core, a linha fica indisponível e diz **"N em outro core"**, em vez de sumir sem explicação.
- Saves soltos na raiz são tratados como do **core padrão** do console (suposição). Se o mesmo slot existe na raiz e na pasta do core, vale o da pasta.
- Saves inventados (demonstração) também são por core.

Exemplo: um jogo de SNES com saves só no Snes9x; com o Snes9x 2010 ativo, o menu mostra "2 em outro core".

## A confirmar no dArkOS (não verificado)
- Como o dArkOS guarda a escolha de core **por jogo** (hoje o protótipo guarda no navegador). O ES tem o conceito de emulador alternativo por jogo; falta ver onde isso é gravado e se o runner o respeita.
- O RetroArch tem overrides de configuração por **jogo**, por **núcleo** e por **pasta de conteúdo**. Candidato natural: exceção do jogo = override do jogo; padrão do console = override da pasta do sistema. Aspecto e shader caberiam aí. Precisa testar no aparelho.
- A lista de cores de cada console: só os **confirmados** vêm dos seus `savestates/`; as alternativas com `*` em `src/data.js` são prováveis.
- Os saves da raiz são mesmo do core padrão? Vale conferir qual core os gerou.

## Alternativas consideradas
- **Só por jogo:** inviável em coleção grande.
- **Só por console:** não resolve o jogo que precisa de outro core.
- **Perfis nomeados** (ex.: "Performance", "Precisão"): mais flexível, mas mais telas e mais conceitos. Fica como evolução se as 3 camadas não bastarem.

Voltar: [Visão geral](visao-geral.md)
