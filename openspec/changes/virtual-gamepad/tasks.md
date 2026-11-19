# Tasks

Verificação desta change: testes de unidade no PC (Python), testes do `lume-evrec` com
dispositivos de entrada falsos e provas pelo cabo no GA36 e depois no R36S (um cartão, um
console por vez, o R36S por último). As gravações e os replays de jogo ficam no cartão ou em
`cache/`, nunca no repositório.

## Grafo de execução

Regras do projeto em `openspec/config.yaml` (`rules.tasks`, `operations.apply`).

**Recursos exclusivos:** `CPU` (um build pesado por vez, sob a proteção de calor),
`ARCH:armv7` e `ARCH:aarch64` (um `lume pkg` por arquitetura), `GA36`, `R36S`, `USUARIO`
(ação física ou olho humano), `MERGE` (um merge por vez em `feature/virtual-gamepad`, seguido de
`pytest tests/unit`, `cargo test` do `lume/` e das suítes de shell).

**Executores:** `AG` = subagente em `out/worktrees/<nó>` (código e teste de unidade); `PR` =
sessão principal (merge, build, aparelho, aprovação do usuário).

| Nó | Depende de | Recursos | Executor | Modelo | Onda | Janela |
|---|---|---|---|---|---|---|
| 1.1 | — | — | AG | sonnet | 0 | |
| 2.1 | 1.1 | — | AG | opus | 1 | V1 |
| 2.2 | 1.1 | — | AG | sonnet | 1 | V1 |
| 2.3 | — | — | AG | sonnet | 0 | V1 |
| 3.1 | 1.1 | — | AG | sonnet | 1 | V1 |
| 3.2 | 3.1 | — | AG | sonnet | 2 | V1 |
| 3.3 | — | — | AG | opus | 3 | VM |
| 3.4 | 2.1, 2.2, 3.2 | — | AG | sonnet | 3 | VM |
| 3.5 | 3.3, 3.4 | CPU | PR | — | 4 | VM |
| 3.6 | 3.3 | — | AG | sonnet | 5 | V1 |
| 4.1 | 2.1, 2.2, 2.3, 3.1, 3.2 | CPU, ARCH:armv7, ARCH:aarch64 | PR | — | 3 | |
| 4.2 | 4.1 | GA36, USUARIO | PR | — | 4 | V1 |
| 4.3 | 4.2 | R36S, USUARIO | PR | — | 5 | V2 |

Modelos aprovados pelo usuário em 2026-11-17 ("crie e execute", como na tabela, ondas em
paralelo). Nós 3.3 a 3.5 (suporte à vm) acrescentados e aprovados em 2026-11-17: o usuário
pediu o teste do controle virtual no emulador x86 enquanto o GA36 está fora (só o controle
virtual; a prova na vm vale só para a vm, e as V1/V2 continuam). Nó 3.6 (SSH multiplexado)
acrescentado e aprovado pelo usuário em 2026-11-17, sonnet.

**Trilhas e caminho crítico:**

```
  1.1 (formatos: gravação e roteiro) --+--> 2.1 (lume-evrec, C) ------+
                                       +--> 2.2 (dev record/play) ----+
                                       +--> 3.1 (dev run) --> 3.2 (roteiros e open_game) --+--> 4.1 build --> 4.2 GA36 (V1) --> 4.3 R36S (V2)
  2.3 (dev replay, RetroArch) ------------------------------------------------------------+

  caminho crítico: 1.1 -> 3.1 -> 3.2 -> 4.1 -> 4.2 -> 4.3
```

**Ondas:**
- Onda 0: 1.1, 2.3. Onda 1: 2.1, 2.2, 3.1. Onda 2: 3.2. Onda 3: 4.1 (build). Onda 4: 4.2 (V1,
  GA36). Onda 5: 4.3 (V2, R36S).

**Janelas de aparelho:**
- **V1** (GA36 no cabo, junto da J1 da `game-governor` se o mesmo cartão servir às duas): o
  usuário só liga o cabo e confere de olho a primeira repetição; o resto roda sozinho.
- **V2** (R36S, o mesmo cartão, no fim): as mesmas provas.

## 1. Formatos

- [x] 1.1 Congelar os dois formatos (D2, D4): o arquivo de gravação (`# r36os-evrec 1 <console>`, uma linha `<ms> <tipo> <código> <valor>` por evento, fim marcado) com leitor e escritor em Python no `lume` (`src/lume_tool/evrec.py`), e o esquema do roteiro TOML (`consoles`, passos `keys`, `play`, `wait_event`, `wait_process`, `shot`, `sh`, `open_game`, `close_game`, cada um com `name` e `timeout`) com validação em `src/lume_tool/scripts.py`; o documento do teste no aparelho (`docs/BUILD.md`, seção do `lume dev`) com os dois formatos. Verificação: testes de unidade (ida e volta de uma gravação, console errado recusado, roteiro com tipo desconhecido ou campo de nome de jogo recusado) e um teste que falha se um `.evrec` estiver no repositório ou se um roteiro de `tests/device/scripts/` tiver `name`/`path` de ROM.

## 2. Gravar, repetir e replay

- [ ] 2.1 `lume-evrec` em C no aport `lume-input` (D2): `record` lê o controle virtual sem agarrar e grava o formato da 1.1; `play` acha os nós por nome, toca no tempo com `clock_nanosleep` absoluto, solta todo botão apertado no fim, no `SIGTERM` e em erro, recusa gravação de outro console, recusa sem permissão de escrita (usuário sem root) e imprime o atraso máximo e médio. Verificação: testes com nós falsos (um par de pipes ou um `uinput` de teste quando o PC permitir, senão arquivos) e relógio injetável: tempos fiéis, botões soltos na interrupção, console errado, sem permissão; no GA36 (V1), uma gravação de 60 s repetida com atraso máximo ≤ 10 ms.
- [ ] 2.2 `lume dev record` / `record --stop` / `play` (D3): liga e para o `lume-evrec` no console, traz a gravação para `cache/recordings/`, envia e toca uma gravação mostrando o atraso medido; gravação vazia é erro. Verificação: testes de unidade com o `ssh` falso (comandos remotos montados, gravação vazia, arquivo de outro console); na V1, gravar 60 s no launcher e repetir com o launcher chegando à mesma tela (captura comparada).
- [ ] 2.3 `lume dev replay record|stop|play <slot>` (D3): `GET_STATUS` antes (sem jogo do RetroArch = erro), depois `RECORD_REPLAY`, `HALT_REPLAY` ou `PLAY_REPLAY_SLOT <slot>` pelo `nc -u` do console. Verificação: testes de unidade com o console falso (comandos, erro sem jogo); na V1, um replay de 60 s de um jogo de GBA gravado e repetido duas vezes, com o mesmo trecho nas duas (conferido pela captura no mesmo instante do replay).

## 3. Roteiros de prova

- [ ] 3.1 `lume dev run <roteiro>` (D4): executa os passos em ordem, cada um com tempo limite, imprime `passo <n> <nome>: ok|FALHOU (<motivo>)`, recusa um console fora de `consoles` antes do primeiro botão, lê o `events.log` só a partir do começo do roteiro e corta as linhas no `content=` (o nome do jogo nunca sai do console). Verificação: testes de unidade com o console falso (passo que falha pelo tempo, console errado, linha com `content=` cortada na saída, código de saída).
- [ ] 3.2 `open_game` e `close_game` (D5) e os primeiros roteiros em `tests/device/scripts/`: um comando no console que imprime só a posição do sistema no Dock e o número de jogos (pelo índice do launcher), a sequência de botões montada no PC, `close_game` por Fn+Start; roteiros `open-close-<sistema>.toml` (um jogo de cada sistema com jogos no cartão, pela posição 1) e `launcher-screens.toml` (as telas de referência do `dev shot`). Verificação: testes de unidade da montagem da sequência (sistema no começo, no meio e no fim do Dock, sistema sem jogos falha sem apertar botões) e do comando do console com um índice falso; na V1, os roteiros passam no GA36.

- [x] 3.3 Rede só local na imagem `vm` para o `lume dev`: `lume vm --ssh [porta]` liga a rede de usuário da QEMU com o `ssh` da vm redirecionado só para `127.0.0.1:<porta>` do PC (padrão 2222), sem rota para fora; na imagem `vm`, e só nela, a interface sobe por DHCP e o `dropbear` escuta nela com root sem senha, como no cabo dos consoles; o `lume dev` e o `lume push` aceitam `--host 127.0.0.1:<porta>`; o `test-vm` continua sem rede. Verificação: testes de unidade dos argumentos da QEMU (com e sem `--ssh`, `test-vm` sem `-nic` de usuário) e do `host:porta` no `ssh`; `lume vm --ssh` + `lume dev sh --host 127.0.0.1:2222 uname -m` responde `x86_64`.
- [x] 3.4 Console `vm` no `lume dev` e no `lume-evrec`: o controle virtual "Lume VM Keyboard" reconhecido como o console `vm` (gravação `# r36os-evrec 1 vm`, roteiros com `consoles = ["vm"]`), a tabela de botões da vm (as teclas do `vm.conf` do `lume-input`) no `dev keys`, sem controle do kernel separado (os atalhos do Fn da vm, se houver, pelo mesmo teclado), e o `open_game` com a mesma navegação. Verificação: testes de unidade (identificação do console `vm`, tabela de botões, gravação da vm recusada num console e vice-versa) e testes do `lume-evrec` com um nó falso de nome "Lume VM Keyboard".
- [x] 3.5 Prova na vm (**vale só para a vm**): build da `vm`, `test-vm` verde, e com `lume vm --ssh`: `dev keys`, `dev record`/`play` de 30 s no launcher com o atraso medido, `dev run` de um roteiro `consoles = ["vm"]` que abre e fecha um jogo de teste livre da vm, `dev replay` num jogo do RetroArch da vm. Verificação: resultados anotados neste `tasks.md` e no `docs/BUILD.md`, marcados como "só vm"; as provas da V1 e da V2 continuam pendentes.

  **Resultados na vm, 2026-11-17 (só vm; imagem com `lume-evrec` e `lume-vmnet`):**
  `test-vm` 82/82 sem rede; `lume vm --headless --ssh` + `dev --host 127.0.0.1:2222`
  responde (depois da correção do encaminhamento: `hostfwd` no loopback do PC com o container
  em `--network=host`; a vm sem rota para fora); `dev keys` ok; `dev record` com 9 toques
  injetados = 36 eventos em 8,2 s; `dev play` com atraso máximo 0,43 ms e médio 0,18 ms; `dev
  run` com 3 passos ok e o 4º falhando pelo tempo, nomeado, saída 1; o usuário `game` recusado
  pelo `lume-evrec` (saída 3, `root only`) e o root tocando (0,135 ms). **Falta na vm:** o
  `open_game` e o `dev replay` (a vm do `lume vm` não tem jogos; as ROMs livres só vão no disco
  do `test-vm`) e a captura de tela (no `--headless` o `lume-ui` não liga o vídeo: `Could not
  set videomode on CRTC`). A tarefa fica aberta até decidir como levar jogos de teste à vm.
  **Complemento (2026-11-17, usuário: "pode levar para as roms"):** as ROMs livres do
  `test-vm` (`cache/tmp/vm_test_roms.py`) entraram pelo `lume vm --roms`; como o
  compartilhamento é só leitura e o `lume-index` grava `gamelist.xml` em cada pasta, foram
  copiadas para a `ROMS` da vm pelo `ssh` e o índice refeito (8 jogos). A prova achou e
  corrigiu dois defeitos: o `open_game`/`close_game` esperavam `game OK opened|closed` (o
  `lume-run` grava `game OK <sistema> ... start` e `... end=`; o `wait_event` passou a ler
  também o `events.pending` da RAM, 74ef971) e supunham o Dock nos Favoritos (o launcher volta
  ao sistema do último jogo; a posição agora vem da linha `dock=` do estado, ce90aaf). Depois
  disso, três `dev run` seguidos (NES, GBA, NES) passaram em todos os passos: abrir pelo launcher,
  o RetroArch rodando, fechar com Fn+Start. `dev replay`: gravar, parar e repetir no slot 1
  confirmados pelo log do RetroArch (`Starting movie record`, `Stopping movie record`,
  `Starting movie playback`); a captura sai preta no `--headless` (a ROM de teste ou o modo),
  então a comparação de imagem do mesmo trecho fica para a V1. Fn+Start pela vm fecha o jogo.
- [ ] 3.6 SSH multiplexado no `lume` (pedido do usuário, 2026-11-17): todos os comandos que falam com o console pelo `ssh` (`lume dev`, `lume push`, o `dev run` e as consultas de 1 s dele) passam por um canal mestre do OpenSSH do PC (`ControlMaster=auto`, `ControlPath` em `cache/ssh/`, `ControlPersist` de 60 s), sem nada novo no console; o canal guarda qual console e qual boot atende e é descartado quando o console reinicia (`push`, `wait`) ou quando o console no cabo muda; uma opção (`LUME_SSH_MUX=0`) desliga. Verificação: testes de unidade dos argumentos do `ssh` com e sem a opção, do descarte do canal (boot novo, console trocado, `push`) e de que o `dev run` usa o canal; na vm (só vm), 20 `dev sh true` seguidos com e sem o canal, tempos anotados; na V1, o mesmo no GA36 e a CPU do `dropbear` num `dev run`, antes e depois.
  **Na vm (só vm, 2026-11-17, `cache/tmp/mux_bench.py`):** 20 `dev sh true` seguidos, sem o
  canal 5,19 s (260 ms cada), com o canal 1,71 s (81 ms cada; o primeiro, que abre o canal,
  178 ms). Falta a V1 no GA36 (tempos e CPU do `dropbear`).

## 4. Build e provas

- [ ] 4.1 Build com o `lume-input` novo (o `lume-evrec`) nas duas arquiteturas, um `lume pkg` por vez sob a proteção de calor, e `lume push`. Verificação: o binário no manifesto das duas camadas e o `push` terminando com `ok`.
- [ ] 4.2 Janela V1 no GA36: o `dev keys` de sempre (botão no controle virtual e Fn+Start no do kernel), uma gravação de 60 s repetida com atraso ≤ 10 ms e o launcher na mesma tela, os roteiros `open-close-*` e `launcher-screens` passando, um replay do RetroArch repetido duas vezes, e um `play` como o usuário dos jogos recusado. Verificação: resultados no `docs/BRINGUP-GA36.md`, sem nome de jogo.
- [ ] 4.3 (R36S feito em 2026-11-19, builds `20261118-234742` e `20261119-142444`: `dev keys`, gravação de 62 s com atraso máx. 0,75 ms e a mesma tela, `play` como `game` recusado, os 7 `open-close-*` e o `launcher-screens` passando também depois de mover o Dock à mão (correção no `lume-ui`: estado gravado a cada movimento; passo `home` no `dev run`; `open-close` com 10 s de jogo para o `QUIT` ser atendido; a tela `settings` com o segundo A), replay de GBA igual em duas sessões do jogo; resultados no `docs/BRINGUP-R36S.md`. Falta a V1 no GA36, com a referência `settings` dele regravada, e a P-86 ao fechar.) Janela V2 no R36S, com o mesmo cartão: as mesmas provas da 4.2. Verificação: resultados no `docs/BRINGUP-R36S.md`; no `docs/PENDENCIAS.md`, a P-86 movida para "Concluídas" com a change.

## Workflow follow-up

- Arquivar a change depois da V2, e mesclar na `main` depois da `game-governor`.
- Com a P-22 (imagem de debug), mover o `lume-evrec` para ela.
