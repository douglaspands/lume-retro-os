# Design

## Context

Ver `proposal.md` (Why). O que já existe e molda o caminho:

- O `r36os-input` (`aports/r36os-input/input.c`) agarra os controles do kernel (`EVIOCGRAB`)
  e publica por `uinput` o controle virtual ("GA36-MB Gamepad" / "R36S Gamepad", barramento
  virtual) que o launcher e o RetroArch leem. Os atalhos do Fn (Fn+Start, Fn+Vol) ele monta só
  a partir dos controles do kernel.
- O `r36os dev keys` (`src/r36os/dev.py`) aperta botões escrevendo `struct input_event` no nó
  `/dev/input/eventN` pelo `ssh`: botões simples no controle virtual, acordes com Fn no
  controle do kernel; os números dos nós vêm do `/proc/bus/input/devices`. Cada botão custa um
  `printf` e um `sleep` no shell do console: bom para navegar, impreciso para repetir uma
  sessão (o `sleep` do busybox e o `fork` no A33 custam dezenas de ms).
- O RetroArch 1.22.2 aceita pela rede (`127.0.0.1:55355`, patch 0009) `RECORD_REPLAY`,
  `HALT_REPLAY` e `PLAY_REPLAY_SLOT <n>`: o replay grava a entrada a partir de um estado salvo
  embutido e a repete quadro a quadro.
- O `events.log` traz as linhas de jogo do `lume-run` (`game OK <sistema> <runner> <core> start`
  e `... exit=<..> end=<..> secs=<n>`; corrigido em 2026-11-17, antes constava o antigo
  `game OK opened: core=... content=<nome>` do frontend RetroArch). Um `content=<nome>` pode
  aparecer em linhas do `logd`: o nome do jogo pode estar na linha, e o PC não pode copiá-la
  para a saída nem para o repositório. Os eventos entram primeiro em `events.pending` (RAM) e
  só depois no `events.log`: o leitor olha os dois.
- Os nós `/dev/input/event*` pertencem ao root e ao grupo `input`; o usuário dos jogos não
  escreve neles.

## Goals / Non-Goals

**Goals:**
- Repetir uma gravação com erro de tempo de no máximo 10 ms por evento no GA36.
- Roteiros de prova que rodam do começo ao fim pelo cabo e dizem passou ou falhou.
- Replay do RetroArch como a forma de carga igual nas medições de energia.

**Non-Goals:**
- Analógicos: os dois consoles não têm sticks em uso pelo launcher; a gravação guarda eventos
  `EV_ABS` se aparecerem, mas os roteiros não os geram.
- Controle pela rede sem fio ou por outro usuário que não o root pelo cabo.
- Mudar o protocolo do `/run/r36os/input.sock` (é da change `lume-hud-actions`).
- Imagem de debug (P-22).

## Decisions

### D1. Injeção pelos nós de evento, sem socket novo

A injeção continua como o `dev keys` já faz: escrever eventos no nó do controle virtual (e no
do kernel para os acordes com Fn). Isso já exige root, não muda o `r36os-input` e funciona nos
dois consoles. *Alternativa descartada:* um socket de injeção no `r36os-input` (o pedido
original): mais código no daemon de entrada, um protocolo a manter junto com o da
`lume-hud-actions`, e nada que o nó de evento não dê.

**Correção (prova na vm, 2026-11-17):** as permissões dos nós não bastam para "só root": o
usuário dos jogos (`game`) está no grupo `input`, e os `/dev/input/event*` são graváveis pelo
grupo (`crw-rw---- root input`), então ele conseguiu tocar uma gravação. Decisão do usuário: o
`r36os-evrec` recusa quem não é root (sai com 3, `root only`); o nó gravável pelo grupo
`input`, que já existia antes desta change, vira a P-87 (avaliar com rumble e LEDs de
controles USB, que precisam de escrita).

### D2. `r36os-evrec`: gravar e repetir no console, em C

Um binário pequeno no pacote `r36os-input` (mesma arquitetura, mesmo aport, sem dependência):

- `r36os-evrec record <saída>`: lê o controle virtual (sem `EVIOCGRAB`, então o launcher e o
  jogo continuam recebendo tudo), ou seja, exatamente o que o launcher e os jogos recebem. Os
  atalhos com Fn não entram: o `r36os-input` agarra o controle do kernel e os transforma em
  ações, então nenhum leitor de fora os vê; nos roteiros eles são passos `keys` (D4). Grava
  texto, uma linha por evento: `<ms desde o início> <tipo> <código> <valor>`, com cabeçalho
  `# r36os-evrec 1 <console>`. Termina no `SIGTERM`/`SIGINT` e grava o fim.
- `r36os-evrec play <arquivo>`: abre os nós por nome (como o `dev keys`), toca cada linha no
  tempo com `clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME)` e `SYN_REPORT` por grupo; no fim,
  no `SIGTERM` ou num erro, solta todo botão ainda apertado. Recusa um arquivo de outro
  console. Mede e imprime o atraso máximo e médio de cada evento.

*Por que C:* tempo preciso sem `fork` por evento no A33 e o mesmo jeito do `r36os-input`; um
roteiro em shell não chega a 10 ms. *Alternativa descartada:* tocar pelo PC com `ssh` por
evento (latência do cabo).

### D3. PC: `record`, `play`, `replay` e `run`

- `r36os dev record` liga o `r36os-evrec record` no console (em segundo plano, arquivo
  em `/run/r36os/evrec/`); `r36os dev record --stop` o para e traz a gravação para
  `cache/recordings/<console>-<data>.evrec`. Uma gravação sem eventos é erro.
- `r36os dev play <arquivo>` envia a gravação para `/run/r36os/evrec/` e roda o
  `r36os-evrec play`, mostrando o atraso medido.
- `r36os dev replay record|stop|play <slot>` manda `RECORD_REPLAY`, `HALT_REPLAY` e
  `PLAY_REPLAY_SLOT <slot>` pelo `nc -u` do console e confere pelo `GET_STATUS` que há um jogo
  do RetroArch aberto antes; os arquivos de replay ficam onde o RetroArch os grava, no cartão.
- `r36os dev run <roteiro>` executa um roteiro (D4) e devolve 0 só se todos os passos passarem.

### D4. Roteiros em TOML, em `tests/device/scripts/`

Um arquivo por roteiro, com `consoles = ["ga36", "r36s"]` e uma lista de passos, cada um com um
nome e um tipo:

| Tipo | Faz | Passa quando |
|---|---|---|
| `keys` | a sequência do `dev keys` | sempre (erro de ssh falha) |
| `play` | uma gravação do `cache/` (nunca do repositório) | o `r36os-evrec` termina com 0 |
| `wait_event` | espera um padrão no `events.log` novo desde o começo do roteiro | o padrão aparece no tempo |
| `wait_process` | espera um processo existir ou sumir | idem |
| `shot` | `dev shot --compare <tela>` | a diferença fica abaixo do limiar |
| `sh` | um comando como root | sai com 0 |
| `open_game` | abre o jogo `posição` do `sistema` pelo launcher (D5) | aparece `game OK <sistema> ... start` (falha logo em `game FAIL <sistema> ... start-failed`; corrigido em 2026-11-17) |
| `close_game` | Fn+Start | aparece `game OK\|FAIL <sistema> ... end=` (corrigido em 2026-11-17) |

O `wait_event` casa o padrão na linha inteira, mas a saída do roteiro mostra só a categoria, o
resultado e o começo da mensagem até `content=` (o nome do jogo nunca sai do console). A cada
passo o roteiro imprime `passo <n> <nome>: ok|FALHOU (<motivo>)`.

### D5. Abrir um jogo sem nomeá-lo

O roteiro diz `system = "gba"` e `position = 1`. O PC pergunta ao console, por um comando que
imprime só números, a posição do sistema no Dock e quantos jogos ele tem (lidos do índice do
launcher no cartão, o mesmo que o `lume-ui` mostra), e monta a sequência de botões: voltar ao
Dock, ir ao sistema, entrar, descer até a posição, abrir. O nome do jogo nunca chega ao PC.
Sistema sem jogos falha antes de apertar botões.

O foco do Dock também vem do console (corrigido em 2026-11-17): depois de um jogo o launcher
volta ao ladrilho em que estava (na vm, `sys:snes`), e a premissa antiga de partir de
Favoritos errava. O comando lê só a linha `dock=` de `$XDG_RUNTIME_DIR/lume/state`
(`/run/user/<uid de game>/lume/state`, nunca `game_path`) e imprime `focus=<índice do Dock>`;
sem arquivo (boot novo, `/run` é tmpfs) ou com valor desconhecido, 0. O driver não guarda mais
o último sistema. Limite: se alguém mexer no Dock à mão depois de um jogo, sem abrir outro, o
arquivo fica velho.

### D6. Privacidade

Gravações e replays guardam botões e estados de jogo, não nomes, mas o arquivo de replay do
RetroArch tem o nome do jogo e fica no cartão. No PC, só `cache/` (fora do git); um teste falha
se `tests/device/scripts/` tiver um campo de nome ou caminho de ROM, ou se um `.evrec` entrar
no repositório.

## Risks / Trade-offs

- [O controle do kernel está agarrado pelo `r36os-input`, então a gravação não vê o Fn] → Os
  atalhos com Fn são passos de roteiro (`keys` com `fn+start`), mandados ao controle do kernel
  como o `dev keys`; a gravação serve aos botões de jogo e de navegação.
- [Escrever no nó de um dispositivo `uinput` pode não chegar aos leitores em algum kernel] → O
  `dev keys` já funciona assim nos dois consoles (spec `device-testing`, "Botões no R36S"); a
  primeira prova no aparelho repete isso antes do resto.
- [Um botão preso se o `r36os-evrec` morrer com `SIGKILL`] → O `dev play` manda `SIGTERM`
  primeiro; o `r36os dev keys` com a lista de botões soltos (`release-all`) desfaz o resto.
- [O jogo não é determinístico e a repetição de botões diverge] → Para medição, o replay do
  RetroArch (D3), que parte do estado salvo e repete quadro a quadro; a gravação de botões fica
  para o launcher e os jogos fora do RetroArch.
- [O índice do launcher muda de formato] → O comando do D5 usa o mesmo leitor do `lume-index`
  (lume-core), coberto pelos testes dele.

## Migration Plan

Só acréscimos: o binário novo no `r36os-input`, subcomandos novos no `r36os dev`. Reverter é
remover o binário e os subcomandos; nada muda para o jogador.
