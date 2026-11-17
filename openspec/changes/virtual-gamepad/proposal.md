# Proposal

## Why

As provas no aparelho ainda precisam de alguém segurando o console: as sessões de medição da
`game-governor` (10 minutos por classe e candidato), abrir um jogo pelo launcher, conferir uma
tela. O usuário pediu (2026-11-17, P-86) autonomia para os testes no console: que as provas
rodem pelo cabo, com o usuário só para o que exige mão ou olho (carregador, cartão, julgar imagem
e som).

O caminho é curto porque metade já existe: o `r36os dev keys` (change `build-speed`, D12) aperta
botões escrevendo eventos no controle virtual publicado pelo `r36os-input` (ou no controle do
kernel, para os acordes com Fn), e os dois kernels têm `uinput` e `evdev`. Faltam a repetição
com tempo preciso, a gravação de uma sessão real, os roteiros de prova e o replay exato do
RetroArch.

## What Changes

- **Gravar e repetir botões:** um binário pequeno no console (`r36os-evrec`, no pacote
  `r36os-input`) grava os eventos do controle virtual com os tempos e repete uma gravação no
  mesmo controle com o tempo preciso do console (sem `ssh` nem `sleep` por botão), soltando
  todos os botões no fim ou na interrupção. No PC: `r36os dev record` e `r36os dev play`.
- **Roteiros de prova:** `r36os dev run <roteiro>` executa um roteiro de
  `tests/device/scripts/` (botões, esperar um evento do `events.log` ou um processo, captura
  comparada com a referência, comando como root, abrir um jogo de um sistema pelo launcher sem
  nome de jogo) e termina com passou ou falhou. Os primeiros roteiros abrem e fecham um jogo de
  cada sistema pelo launcher e conferem as telas de referência.
- **Replay do RetroArch:** `r36os dev replay record|stop|play <slot>` usa os comandos de rede
  do RetroArch 1.22.2 (`RECORD_REPLAY`, `HALT_REPLAY`, `PLAY_REPLAY_SLOT`), que gravam a
  entrada desde um save state e a repetem quadro a quadro: a carga igual para comparar
  candidatos de energia.
- **Só root:** nada novo exposto ao jogador; os nós de entrada e o comando de rede do RetroArch
  (só `127.0.0.1`) já pedem root pelo cabo. Quando a imagem de debug existir (P-22), as
  ferramentas passam a ir só nela.
- **Privacidade:** gravações, replays e capturas com jogo ficam no cartão ou em `cache/` do PC;
  os roteiros do repositório escolhem jogos por sistema e posição, nunca por nome.

## Capabilities

### New Capabilities

Nenhuma.

### Modified Capabilities

- `device-testing`: ganha gravar e repetir botões, roteiros de prova com resultado de passou ou
  falhou, replay do RetroArch e a regra de que gravações e roteiros não levam nome de jogo.

## Impact

- `aports/r36os-input/`: o binário `r36os-evrec` (C, por arquitetura), no mesmo pacote.
- `src/r36os/dev.py` e `src/r36os/cli.py`: os subcomandos `record`, `play`, `run` e `replay`;
  um módulo novo para os roteiros.
- `tests/device/scripts/` (roteiros), `tests/unit/` (testes do PC), testes do `r36os-evrec` com
  dispositivos falsos.
- `docs/BUILD.md` (ou o guia de teste no aparelho) e `docs/PENDENCIAS.md` (P-86).
- Nenhuma mudança no kernel, no launcher nem no RetroArch (os comandos de replay já existem).
- Branch `feature/virtual-gamepad`, criada da `feature/game-governor`: o cartão de medição da
  J1 pode levar as ferramentas; mescla na `main` depois da `game-governor`.
