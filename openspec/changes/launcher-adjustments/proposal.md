# Proposal

## Why

A change `lume-launcher` foi arquivada em 2026-11-15 com o código pronto e testado no host e
na VM, mas sem a conferência no aparelho (P-70), e com pedidos do usuário que ficaram para
depois: o menu do sistema pelo Fn (P-74), o Reiniciar (P-72) e as cores oficiais dos logos
dos consoles (P-84). A `lume-hud-actions` transforma o Fn no botão do sistema, à moda do
botão Steam (toque abre menu, segurar mostra os atalhos), mas só durante o jogo. Esta change
leva o mesmo gesto ao launcher e fecha a conferência no aparelho, para o launcher ficar
coerente dentro e fora do jogo. Ela vem **depois** da `lume-hud-actions`, que entrega os
eventos `fn_tap`, `fn_hold` e `fn_release` do `r36os-input`.

## What Changes

- **Menu do sistema pelo toque no Fn (P-74)**: em qualquer tela do launcher (Dock, grade,
  busca, Configurações, menu do jogo), o toque no Fn abre o menu do sistema com Desligar,
  Reiniciar e Configurações; outro toque ou B fecha. Desligar e Reiniciar pedem confirmação,
  com Cancelar em foco. O rodapé do Dock ganha a dica do Fn (glifo + "Menu").
- **Dica dos atalhos ao segurar o Fn no launcher**: o mesmo gesto do jogo, com os acordes que
  valem no launcher (no mínimo Fn+Vol, o brilho), lidos da tabela que o `r36os-input` manda
  no `fn_hold`.
- **Reiniciar (P-72)**: o `lume-ui` diz ao `session` se o fim é desligar ou reiniciar; os dois
  gravam os dados (`persist flush`, `sync`) antes. Um código de erro continua reabrindo o
  frontend.
- **BREAKING (Configurações)**: o item Desligar sai da lista das Configurações; desligar passa
  a ser só pelo menu do sistema.
- **Cores oficiais dos logos dos consoles (P-84)**: o tema pode declarar, por sistema, a cor do
  ícone e do fundo do item do Dock (e da sigla, quando não há logo), com herança como os outros
  tokens; o tema sem essas cores continua como hoje. Primeiro no protótipo, medido com a régua
  a 640x480. A forma exata (tokens por sistema, logo colorido RGBA, ou os dois) fica para o
  design.
- **Conferência no aparelho (P-70, P-71)**: GA36 e R36S, com o mesmo cartão, um de cada vez:
  as telas contra o protótipo (com as telas novas desta change), Fn+Vol e a linha por cima do
  jogo, o tempo até o primeiro quadro, as medições do R36S (9.6 da `lume-launcher`), o sensor de
  temperatura, e o Desligar do r27 no GA36 (fecha o P-71). O que falhar vira tarefa aqui.

Fora do escopo: Wi-Fi completo (P-66) e Bluetooth (P-67) nas Configurações, tema Lume próprio
(P-13), miniaturas e wallpaper por sistema (P-17), e tudo o que acontece com o jogo aberto
(change `lume-hud-actions`).

## Capabilities

### New Capabilities
<!-- nenhuma: o menu do sistema e as cores por sistema são comportamento do launcher -->

### Modified Capabilities
- `game-launcher`: menu do sistema pelo toque no Fn e dica ao segurar; Desligar sai das
  Configurações e vai para o menu do sistema, com Reiniciar ao lado; cores por sistema nos
  ícones do Dock pelo tema.
- `frontend-session`: o fim normal do frontend pode pedir desligar ou reiniciar; o item
  Desligar das Configurações deixa de ser a ação que desliga.

## Impact

- `lume/lume-ui` (menu do sistema, dica, Configurações sem Desligar, cores por sistema, testes
  de tela em `tests/ui.rs`), `lume/lume-core` (tema: tokens por sistema e validação; textos en,
  pt e es) e os temas da imagem (`themes/`).
- `rootfs/.../session` e o `lume-run` (código de saída ou aviso para reiniciar).
- Protótipo do launcher (`docs/lume-launcher/prototipo/`): o menu do sistema, a dica no
  launcher e as cores por sistema, antes do código.
- Documentação: `docs/LAUNCHER.md`, `docs/lume-launcher/formato-de-tema.md`,
  `docs/lume-launcher/design-das-telas.md`, guias de bring-up; pendências P-70, P-71, P-72,
  P-74 e P-84 atualizadas no `docs/PENDENCIAS.md`.
- Depende da `lume-hud-actions` (eventos do Fn no `r36os-input`).
- Provas no GA36 e no R36S (o mesmo cartão, um console de cada vez).
