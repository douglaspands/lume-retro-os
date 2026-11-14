# lume-launcher: interface (launcher) para o R36S

> **Candidato oficial do protótipo: `20261114-033157`** ([Protótipos](prototipos.md)).

> Nome do app: **lume-launcher**. Funcionalidade futura: troca de temas, por isso o código é modular ([Protótipos](prototipos.md)).

> Reconstruído do zero em 2026-11-14. O histórico da conversa anterior foi perdido no `/clear`.

## Decisões já tomadas
- **Tipo:** frontend de launcher (listar e abrir jogos/emuladores)
- **Firmware:** ArkOS / dArkOS
- **Planejamento:** notas + Canvas (formato Obsidian) nesta pasta (ver [Arquitetura](arquitetura.canvas))

- **Integração:** complementar o EmulationStation, como item no menu Ports (não substitui o ES)
- **Requisito principal:** baixo consumo de recursos em clones fracos, com tema versátil ([Orçamento de performance](orcamento-de-performance.md))
- **Tema:** criar do zero, com motor próprio e formato declarativo ([Formato de tema](formato-de-tema.md)); não refatorar o do ES ([Decisão - refatorar ou criar do zero](decisao-refatorar-ou-criar-do-zero.md))
- **Tecnologia recomendada:** Rust + SDL2 ([Opções de tecnologia](opcoes-de-tecnologia.md))

## Premissas a confirmar
- Tela do R36S: 640x480 (4:3). Confirmar no aparelho.
- Entrada: só o gamepad (D-pad, A/B/X/Y, L/R, Start/Select, sticks). Sem teclado nem toque.
- O dArkOS já traz EmulationStation como frontend padrão. O nosso launcher substitui ou complementa esse frontend.

## Perguntas em aberto
1. ~~Substituir ou complementar o ES?~~ Decidido: complementar via Ports.
2. **Tecnologia:** ver [Opções de tecnologia](opcoes-de-tecnologia.md).
3. **Escopo da v1:** ver [Escopo v1](escopo-v1.md).
4. **Como desenvolver:** no PC com emulação de tela 640x480 e copiar para o SD, ou direto no aparelho via SSH?

## Notas relacionadas
- [Opções de tecnologia](opcoes-de-tecnologia.md)
- [Decisão - refatorar ou criar do zero](decisao-refatorar-ou-criar-do-zero.md)
- [Orçamento de performance](orcamento-de-performance.md)
- [Formato de tema](formato-de-tema.md)
- [Protótipos](prototipos.md)
- [Emuladores por console e por jogo](emuladores-por-console-e-por-jogo.md)
- [Design das telas](design-das-telas.md)
- [Gamelist e capas](gamelist-e-capas.md)
- [Configurações](configuracoes.md)
- [Pesquisa de interfaces](pesquisa-de-interfaces.md)
- [Escopo v1](escopo-v1.md)
- [Arquitetura](arquitetura.canvas)
