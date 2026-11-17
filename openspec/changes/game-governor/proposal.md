# Proposal

## Why

O usuário quer mais bateria sem perder qualidade de jogo (roadmap decidido em 2026-11-16). Hoje
a CPU dos dois consoles usa só o `schedutil` padrão do kernel, que olha a carga e não o quadro:
um emulador termina o quadro e espera a próxima tela, o `schedutil` vê essa espera como pouca
carga, desce o clock e perde o quadro seguinte (a fábrica do GA36 contornava isso com `ondemand`
e piso de 600 MHz no jogo). Ao mesmo tempo, o próprio coletor de métricas gasta ~30% de um
núcleo no GA36, e a thread `sugov:0` do `schedutil` mais ~40% (P-60), o que gasta bateria e
falseia qualquer medição. O launcher não mostra quando está carregando (P-78), e nada desliga o
console com a bateria acabando, o que pode corromper o cartão (P-64, item 3). Tema 6 das
pendências (P-20, P-83, P-23), com o P-60, o P-78 e o item 3 do P-64.

## What Changes

- **Perfis de energia automáticos por cenário**, sem escolha do usuário: boot, menu do
  launcher, launcher ocioso, jogo (por classe de sistema, com exceção por core) e volta ao menu.
  Cada perfil define o governor, o clock mínimo e máximo, os núcleos ligados e o clock da GPU,
  aplicados só nas fronteiras entre cenários. Os valores vêm de medições nos dois consoles, com
  a regra de nunca perder quadros em relação ao padrão de hoje.
- **Serviço do sistema que aplica os perfis**, avisado pelo supervisor do jogo e pelo launcher
  (o "modo jogo" do P-83, sem GameMode nem polkit), com os perfis num arquivo de dados por
  console.
- **Controlador pela carga do jogo** (P-20, etapa 2), ligado por perfil: dentro da faixa do
  perfil, sobe o clock quando a thread principal do jogo passa de ~85% de um núcleo e desce
  abaixo de ~50%, sempre sob o teto térmico do kernel.
- **Prioridade do jogo**: os processos do jogo acima dos serviços de fundo (índice, playlists,
  saves, logs), sem tempo real; o daemon de entrada acima do jogo, para o Fn+Start encerrar até
  um jogo travado.
- **Ajustes pelo cartão** no `ROMS/system/lume/power.conf`: além de sobrescrever perfis, o tempo
  do launcher parado e `enabled = 0`, que desliga os perfis e devolve o padrão do kernel.
- **Relatório de energia no PC** (`r36os power report`): resume as métricas e os eventos do
  cartão por cenário e por sistema (corrente média, FPS contra o nominal, eventos `slow`, CPU
  por núcleo, clock médio, temperatura máxima, custo do `logd` e da `sugov`), sem nome de jogo,
  para comparar antes e depois.
- **Coletor de métricas barato** (P-60): o `logd` sem processos externos por amostra, abaixo de
  1% de um núcleo no GA36, antes de qualquer medição de perfil.
- **Bateria fraca**: aviso no launcher e por cima do jogo num nível baixo, e desligamento limpo
  (o jogo grava a SRAM, os logs descarregam) num nível crítico, só descarregando.
- **Launcher**: indicador de carga na bateria da barra de status, atualizado em poucos segundos
  ao ligar o carregador (P-78), e a tela escurece depois de alguns minutos parada no launcher,
  voltando ao primeiro botão.
- **Kernel do GA36**: os governors `ondemand` e `conservative` passam a ser compilados, para os
  perfis poderem escolhê-los como no R36S.
- **Medição da DRAM do A33** (P-23, só medir): o clock real da memória no retrato de hardware,
  sem mudar o clock.
- **BREAKING (spec `device-support`):** a CPU deixa de usar só o governor padrão do kernel sem
  valores próprios; passa a usar os perfis, sempre dentro da tabela de frequências e tensões e
  das proteções térmicas do device tree mainline.

Fora do escopo: overclock do GA36 (P-11), flags de compilação por CPU e userland armv7 (P-10 e
P-82, reservados para a change de cores, P-80), Mesa sem LLVM (P-59, vai para o P-58), modo de
energia escolhido pelo usuário (fica para depois de medido), o controlador por FPS real (P-20,
etapa 3, exige patch no RetroArch) e a barra de status sobre o jogo
(`lume-hud-actions`, parada).

## Capabilities

### New Capabilities
- `power-profiles`: os cenários de uso, o perfil de energia de cada um, quem avisa a troca de
  cenário, a regra de não perder quadros e o comportamento com bateria fraca.

### Modified Capabilities
- `device-support`: o requisito "Frequência da CPU e proteção térmica" passa a admitir perfis
  próprios dentro da tabela e das proteções do device tree.
- `boot-runtime`: requisito novo de custo máximo da coleta de métricas.
- `game-launcher`: indicador de carga na barra de status e tela escurecida com o launcher parado.
- `game-runners`: o supervisor avisa o sistema no início e no fim de cada jogo, sem atrasar nem
  impedir o jogo, e os processos do jogo têm prioridade acima dos serviços de fundo.

## Impact

- Serviço novo no pacote `lume-power`, com os perfis em `/usr/share/lume/power/<console>.toml`;
  testes do shell com árvores falsas do sysfs.
- `lume/lume-run` (avisos de início e fim de jogo com sistema e core) e `lume/lume-ui` (menu,
  ocioso, escurecer a tela, indicador de carga; telas no protótipo com a régua).
- `aports/lume-core/.../logd` (P-60) e `aports/lume-diag/.../hwinfo` (DRAM do A33, P-23).
- Binário pequeno em C do controlador pela carga (`r36os-powerctl`, um aport por arquitetura,
  como o `r36os-input`) e o init do `r36os-input` (prioridade acima do jogo).
- `src/r36os/power_report.py` e o comando `r36os power report` no PC.
- `board/ga36/kernel.config` (governors) e o build do kernel do GA36.
- `docs/LOGS.md`, `docs/BRINGUP-GA36.md`, `docs/BRINGUP-R36S.md`, `docs/PENDENCIAS.md` (P-20,
  P-23, P-60, P-64, P-78, P-83).
- Muitas horas de jogo medidas nos dois consoles, com os jogos de teste do usuário (só números
  agregados nos artefatos, nunca nomes de jogo).
