# Tasks

Verificação desta change: testes de unidade (Python, Rust e shell, com árvores falsas do
sysfs), o protótipo do launcher no navegador (marca de carga e aviso de bateria) e muitas
sessões de jogo medidas no aparelho (GA36 e R36S, com um único cartão passado de um console ao
outro: nunca os dois ligados ao mesmo tempo), sempre com os jogos de teste do usuário e só com
números agregados nos artefatos. A imagem `vm` segue fora do ciclo (P-81).

## Grafo de execução

Regras do projeto em `openspec/config.yaml` (`rules.tasks`, `operations.apply`).

**Recursos exclusivos:** `CPU` (um build pesado por vez, sob a proteção de calor),
`ARCH:armv7` e `ARCH:aarch64` (um `lume pkg` por arquitetura), `GA36`, `R36S`, `USUARIO`
(ação física ou olho humano), `MERGE` (um merge por vez em `feature/game-governor`, seguido de
`pytest tests/unit`, `cargo test` do `lume/` e das suítes de shell).

**Executores:** `AG` = subagente em `out/worktrees/<nó>` (código e teste de unidade); `PR` =
sessão principal (merge, build, aparelho, aprovação do usuário).

**Ordem que importa:** as medições (5.2 e 5.3) só começam com o `logd` barato (1.2) no cartão:
antes disso a corrente e a ocupação medidas são falsas. Os arquivos de perfil da imagem levam
perfis iguais ao padrão do kernel até a 5.4.

| Nó | Depende de | Recursos | Executor | Modelo | Onda | Janela |
|---|---|---|---|---|---|---|
| 1.1 | — | — | AG | sonnet | 0 | |
| 1.2 | — | — | AG | opus | 0 | J1 |
| 1.3 | — | — | AG | sonnet | 0 | J1 |
| 2.1 | — | — | AG | opus | 0 | J1 |
| 2.2 | 1.1 | — | AG | opus | 1 | J1 |
| 2.3 | 2.2 | — | AG | opus | 2 | J1 |
| 2.4 | 2.2 | — | AG | sonnet | 2 | J3 |
| 3.0 | — | USUARIO | AG+PR | sonnet | 0 | |
| 3.1 | 1.1 | — | AG | sonnet | 1 | J1 |
| 3.2 | 1.1, 3.0 | — | AG | sonnet | 1 | J1 |
| 4.1 | — | — | AG | sonnet | 0 | J1 |
| 4.2 | — | — | AG | sonnet | 0 | J1 |
| 2.5 | 2.3 | — | PR | opus | 2b | J1 |
| 2.6 | 2.2 | — | PR | opus | 2b | J1 |
| 5.1 | 1.2, 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 3.1, 3.2, 4.1, 4.2 | CPU, ARCH:armv7, ARCH:aarch64 | PR | — | 3 | |
| 5.2 | 1.3, 5.1 | GA36, USUARIO | PR | — | 4 | J1 |
| 5.3 | 5.2 | — | AG | sonnet | 5 | |
| 5.4 | 5.3 | CPU, ARCH:armv7 | PR | — | 6 | |
| 5.5 | 5.4 | GA36, USUARIO | PR | — | 7 | J3 |
| 6.1 | 5.1 | R36S, USUARIO | PR | — | 8 | J2 |
| 6.2 | 6.1, 5.3 | — | AG | sonnet | 9 | |
| 6.3 | 6.2, 5.4 | CPU, ARCH:aarch64 | PR | — | 10 | |
| 6.4 | 6.3, 5.5 | R36S, USUARIO | PR | — | 11 | J4 |
| 7.1 | — | — | PR | opus (a aprovar: o laço mantém o SSH e o MTP pelo cabo) | 12 | |
| 7.2 | — | — | PR | sonnet (a aprovar) | 12 | |
| 7.3 | — | — | PR | sonnet (a aprovar) | 12 | |
| 7.4 | — | — | PR | sonnet (a aprovar) | 12 | |
| 7.5 | 7.1, 7.2, 7.3, 7.4 | CPU, ARCH:armv7, ARCH:aarch64 | PR | — | 13 | |
| 7.6 | 7.5 | GA36 ou R36S | PR | — | 14 | pelo cabo |

Modelos: ondas 0, 1 e 2 aprovadas pelo usuário em 2026-11-17 (como na tabela, em paralelo); as
outras ondas aguardam aprovação antes de começar.

**Revisão de 2026-11-18 (pedido do usuário):** controlador por gargalo (D17) e ajuste manual por
recurso e por jogo (D18) entram como a onda 2b (2.5 e 2.6). O usuário autorizou ir até o fim
sem pedir aprovação ("vá até o final sem solicitar permissão", 2026-11-18): a onda 2b e as
seguintes do GA36 rodam na sessão principal, e o GA36 fecha o ciclo com o R36S para o fim. As
partes da J1 e da J3 que precisam de mão ou de bateria descarregando ficam anotadas como
pendentes do usuário.

**GA36 primeiro (pedido do usuário, 2026-11-17):** o usuário vai levar o GA36 e ficar fora;
o GA36 fecha o ciclo inteiro (J1, perfis, build, J3) antes de qualquer janela do R36S, que
fica para o fim (J2, perfis, build, J4). O cartão único segue passando de um console ao outro
só depois que o GA36 terminar.

**Trilhas e caminho crítico:**

```
  1.1 (FIFO e arquivo de perfis) --+--> 2.2 (serviço lume-power) --+--> 2.3 (controlador) --+
                                   |                                +--> 2.4 (prioridade) ----+
                                   +--> 3.1 (lume-run avisa) ---------------------------------+
  3.0 (protótipo, USUARIO) --------+--> 3.2 (lume-ui) ----------------------------------------+
  1.2 (logd barato, P-60) --------------------------------------------------------------------+--> 5.1 build de medição
  2.1 (kernel GA36: governors) ---------------------------------------------------------------+         |
  4.1 (DRAM no hwinfo, P-23) -----------------------------------------------------------------+         |
  4.2 (core do SNES: snes9x2005_plus do upstream) --------------------------------------------+         v
  1.3 (lume power report) ---------------------------------------------> 5.2 medir GA36 (J1)
                                                                                |
        GA36: 5.3 ga36.conf --> 5.4 build armv7 --> 5.5 provas GA36 (J3) -------+
                                                                                v
        R36S: 6.1 medir R36S (J2) --> 6.2 r36s.conf --> 6.3 build aarch64 --> 6.4 provas R36S (J4)

  caminho crítico: 1.1 -> 2.2 -> 2.3 -> 5.1 -> 5.2 -> 5.3 -> 5.4 -> 5.5 -> 6.1 -> 6.2 -> 6.3 -> 6.4
```

**Ondas:**
- Onda 0: 1.1, 1.2, 1.3, 2.1, 3.0, 4.1, 4.2 (AG, em paralelo; a 3.0 termina com a aprovação do usuário).
- Onda 1: 2.2, 3.1, 3.2.
- Onda 2: 2.3, 2.4 (os dois mexem no `lume-power`: em worktrees separadas, mesclados um por vez).
- Onda 3: 5.1 (build de medição, as duas arquiteturas, fila única de CPU, com o kernel do GA36).
- GA36: Onda 4: 5.2 (J1). Onda 5: 5.3. Onda 6: 5.4. Onda 7: 5.5 (J3).
- R36S, depois do GA36: Onda 8: 6.1 (J2). Onda 9: 6.2. Onda 10: 6.3. Onda 11: 6.4 (J4).
- Revisão de 2026-11-19 (D20, P-112): Onda 12: 7.1, 7.2, 7.3, 7.4 (sessão principal, um de
  cada vez; a 7.1 primeiro, por ser a de risco). Onda 13: 7.5 (build). Onda 14: 7.6 (medição
  pelo cabo).

**Janelas de aparelho** (depois das provas da `build-speed` e da `card-health`, na fila única do
cartão; ordem J1, J3, J2, J4):
- **J1** (GA36, build de medição): primeiro o custo do `logd` e do `sugov:0` e a DRAM no
  retrato; depois as sessões de 10 minutos por candidato e por classe (D5), sem carregador,
  com a bateria entre 40% e 90%. O usuário joga as sessões e liga o carregador entre elas.
  Várias sessões, em dias diferentes se preciso.
- **J2** (R36S, o mesmo cartão): o mesmo da J1.
- **J3** (GA36, build final): cenários, tela escura, marca de carga, aviso e desligamento com a
  bateria acabando de verdade numa sessão longa; o controlador num jogo pesado e o Fn+Start com
  um jogo travado.
- **J4** (R36S): o mesmo da J3.

**Estado em 2026-11-18 (noite, GA36 no cabo e no carregador; detalhes no
`docs/BRINGUP-GA36.md`, "Governor por gargalo"):**
- Provado no GA36 e marcado: 2.1, 2.4, 2.5, 2.6, 3.1, 4.1.
- Provado no GA36, falta o R36S (J2/J4): 2.2 (cenários, `reload`, `power.state`, `enabled 0`
  com o piso, modo manual), 2.3 (o modo `load`, provado num perfil de teste do cartão: num jogo
  de NES desceu de 1008 a 816 MHz, `1008000=7.7s 912000=3.0s 816000=39.4s up=0 down=2 end=stop`;
  os perfis do GA36 usam o `auto`),
  3.2 (escurece em 2 min, primeiro botão só devolve a luz e o perfil `menu`), 4.2 (SNES no
  `snes9x2005_plus` novo a 60,1 quadros/s; o cartão não tem save state antigo de SNES, só os
  saves internos `.srm`: a prova do save state antigo precisa de um state do core de 2022 ou
  fica dispensada pelo usuário), 5.1 (só armv7).
- 1.2, provado no GA36 (falta o R36S): o laço de amostras virou o `lume-logd` em C (APK
  próprio, pedido do usuário; o `logd` em shell faz o resto e o chama), com o mesmo formato.
  Medido em 120 s: **0,8%** de um núcleo no launcher parado e **0,9%** num jogo, ~550 KB de
  memória (era ~30%; 5,5 a 7,3% com o shell barato e o `logs.conf` do cartão em 2 s / 5 s, que
  voltou ao padrão 5 s / 60 s; 1,8% com o shell no padrão). O `sugov:0` caiu de 30% para 4,4%
  com o `rate_limit_us` de 100 ms no menu.
- 5.2: as sessões do D5 com corrente da bateria precisam do usuário jogando sem carregador. Pelo
  cabo saíram a medição de quadros e de clock (tabela no bring-up) e o achado do P-93 (vídeo em
  thread). 5.3/5.4: o `ga36.conf` já leva o controlador por gargalo e os `rate_limit_us`; o piso
  do GBA (1008 MHz, decisão do usuário) ficou, mas com o vídeo em thread o controlador rodou uma
  corrida de GBA a 912 MHz sem perder velocidade: decidir com o usuário.
- 5.5: as provas à mão do usuário passaram (2026-11-18): o menu do sistema (Fn) abre no jogo com
  o vídeo em thread, a marca de carga aparece e some, e os jogos de CPS-1 e de GBA que tinham
  queda rodam lisos. **O GA36 está fechado**; falta o ciclo do R36S (6.1 a 6.4, J2 e J4), que
  também marca os itens provados só no GA36 (1.2, 2.2, 2.3, 3.2, 4.2, 5.x).
- **Bateria fora desta change (decisão do usuário, 2026-11-18):** as sessões sem carregador da
  5.2 (corrente por classe e candidato) e o aviso e o desligamento com a bateria acabando de
  verdade da 5.5 e da J4 ficam para a change futura de aprendizado da bateria (P-98). Aqui vale
  o que já está provado: as colunas `bat_*` nas métricas do `lume-logd` a cada amostra e a lógica
  de aviso e de crítico nos testes com sysfs falso (2.2). A escolha de perfis da 5.3 usa os
  quadros e os clocks medidos pelo cabo.

## 1. Interfaces e coletor

- [x] 1.1 Congelar o protocolo do FIFO `/run/lume/power` (D1: `menu`, `idle`, `game <sistema> <core>`, `end`, uma por linha; escritor sem bloquear, que ignora a ausência do serviço) e o formato do arquivo de perfis (D3: `profile`, `class`, `core`, `battery`, `controller=load`, comentários, sobrescrita pelo `ROMS/system/lume/power.conf` com `enabled 0` e `idle after=`), com o validador em shell (clocks na tabela, governor disponível, `cores` no intervalo, piso `limit game_min=` dos perfis de jogo, D3) e o escritor do FIFO em Rust no `lume-core`; para a interface (D16): a mensagem `reload`, o formato do `/run/lume/power.state` e o editor do `power.conf` em Rust no `lume-core` (lê, valida contra o estado, muda uma linha, mantém comentários e linhas desconhecidas, grava atômico); `docs/LOGS.md` com os eventos `power`. Verificação: testes do shell com árvores falsas do sysfs (arquivo válido, clock fora da tabela recusa o perfil, governor ausente, sobrescrita do cartão, linha desconhecida, perfil de jogo sem `min` recebe o piso, `min` abaixo do piso recusado, `limit` no `power.conf` ignorado) e testes Rust do escritor (FIFO sem leitor não bloqueia nem falha o chamador) e do editor (ida e volta sem mudar o arquivo, comentários mantidos, valor fora do estado recusado, gravação atômica).
- [ ] 1.2 (GA36 medido em 2026-11-19: o `lume-logd` em C com os filhos 0,85% de um núcleo parado e 0,94% num jogo de SNES, meta cumprida; fecha com a medição da 7.6, que também mede o R36S quando ele estiver no cabo, ou fica no P-110.) `logd` barato (D8, P-60): cada amostra sem processos externos (leituras com `read`, `/dev/kmsg` no lugar do `dmesg`, um `pidof` por amostra, data sem processo por linha); se não chegar a 1% de um núcleo, o coletor da amostra vira um binário em C com o mesmo formato. Verificação: `tests/logs/test_logs.sh` com as mesmas colunas e eventos de antes (formato congelado antes da troca); no GA36 e no R36S, o `logd` com os filhos abaixo de 1% de um núcleo em 60 s no launcher parado e num jogo, e o `sugov:0` antes e depois anotados no P-60 (J1, J2); spec `boot-runtime`.

- [x] 1.3 `lume power report [--since <boot>] [--console ga36|r36s]` (D14): lê pelo cabo as métricas e o `events.log` da `ROMS/logs/` e resume por cenário e por sistema (corrente média, FPS contra o nominal, eventos `game FAIL slow`, CPU por núcleo, clock médio, temperatura máxima, custo do `logd` e da `sugov`), sem nome de jogo; tabela no terminal e CSV em `cache/`. Verificação: testes de unidade com métricas e eventos de exemplo (amostras antigas sem as colunas novas, eventos `power`, nenhum nome de jogo na saída); comando documentado no `docs/BUILD.md`.

## 2. Kernel e serviço

- [x] 2.1 Kernel do GA36 (D10): `CONFIG_CPU_FREQ_GOV_ONDEMAND=y` e `CONFIG_CPU_FREQ_GOV_CONSERVATIVE=y` no `board/ga36/kernel.config`, o padrão continua `schedutil`; `tests/unit/test_ga36_kernel_config.py` passa a exigir os dois e a proibir `CPU_FREQ_DEFAULT_GOV_*` e `THERMAL_DEFAULT_GOV_*`. Verificação: teste de unidade; no GA36, `scaling_available_governors` com os dois e o `scaling_governor` ainda `schedutil` no boot (J1).
- [x] 2.2 (Provado em 2026-11-19: eventos `power` de boot, menu, jogo e ocioso nos dois consoles; `reload` de `idle after=300` aparece no `power.state` sem reboot (R36S).) Serviço `lume-power` no `lume-power` (D2, D4, D6, D7): runlevel `boot`, perfil `boot` ao subir; laço com `read -t 60` no FIFO; aplicação na ordem do D4 (núcleos, mínimo e máximo, governor, parâmetros, núcleos a mais, GPU), nunca o `cpu0`; evento `power OK profile` a cada troca; perfil recusado deixa o padrão do kernel (no jogo do GA36, com o `scaling_min_freq` no piso, também com `enabled 0`); `reload` relê os arquivos e reaplica o cenário em curso; `/run/lume/power.state` gravado a cada carga e troca (D16); bateria a cada mensagem e a cada 60 s, aviso uma vez por descarga (`SHOW_MSG` no jogo, texto pelo `ui_lang`) e desligamento com duas leituras críticas seguidas (`power OK shutdown: battery critical` e `poweroff`); modo manual `lume-power set <perfil>` para a medição; arquivos de perfil iniciais iguais ao padrão do kernel, exceto no `ga36.conf` o piso de jogo e os valores iniciais do D3 (`game_min` 600 MHz, GBA e `heavy` com mínimo de 1008 MHz). Verificação: testes do shell com sysfs falso (ordem das escritas, `cpu0` nunca desligado, perfil recusado com o piso mantido no jogo, `reload` muda o perfil do próximo jogo, conteúdo do `power.state`, aviso uma vez só, crítico só com duas leituras e só descarregando, carregando não avisa) e um RetroArch falso por UDP recebendo o `SHOW_MSG`; no aparelho, J1 a J4.

- [x] 2.3 (Provado no GA36 em 2026-11-18: `power OK controller` com o tempo por degrau num jogo de NES e no CPS-1 com o vídeo em thread (`docs/BRINGUP-GA36.md`).) Controlador pela carga `lume-powerctl` (D12): aport em C por arquitetura, governor `userspace`, amostra de 250 ms da thread mais ocupada do processo principal do cgroup do jogo, sobe um degrau acima de 85% por 1 s e desce abaixo de 50% por 3 s, dentro do `min`/`max` do perfil e sob o `scaling_max_freq` atual; o `lume-power` o liga nos perfis com `controller=load`, mata no `end`, reaplica o perfil sem ele se ele cair, e registra `power OK controller` com o tempo por degrau. Verificação: testes com `/proc` e sysfs falsos e relógio falso (sobe, desce, respeita o teto térmico, para no fim do jogo, queda do controlador volta ao perfil); no GA36, um jogo pesado com o controlador mostra a frequência variando nas métricas (J1, J3).
- [x] 2.4 Prioridade do jogo (D13): o `lume-power`, 2 s depois do `game` e de novo 2 s depois, aplica `nice -5` e `ioprio` best-effort 2 a todos os processos e threads do cgroup mais novo em `/sys/fs/cgroup/lume/game-*`; o init do `lume-input` passa a `nice -10`; spec `game-runners`. Verificação: teste do shell com um cgroup e um `/proc` falsos (todos os pids recebem a prioridade, nada em tempo real, cgroup vazio não falha) e o init do `lume-input` conferido em teste; no GA36, Fn+Start encerra um jogo travado (J3).

- [x] 2.5 Controlador por gargalo (D17): o `lume-powerctl` ganha `--mode auto` (o `load` continua): janela de 1 s com os quadros entregues (`drm-page-flips` dos fds do DRM do cgroup do jogo, achados a cada 2 s, um por `drm-client-id`), a ocupação da GPU (o maior `drm-engine-*` sobre o tempo) e a thread mais ocupada da CPU; alvo de quadros = maior ritmo dos últimos 30 s; regras 1 a 5 do D17; CPU pelo `scaling_setspeed`, GPU pelo `min_freq` do devfreq (restaurado ao parar); recurso com faixa de um degrau não é controlado; `/run/lume/powerctl.state` a cada mudança; linha final com o tempo por degrau de cada recurso e a contagem por gargalo; o `lume-power` liga o modo pelo `controller=auto` com as faixas do perfil (`--gpu-min`, `--gpu-max`) e, no R36S, liga o `profiling` do `panfrost`. Verificação: testes com `/proc`, `fdinfo` e sysfs falsos e relógio falso (GPU saturada sobe só a GPU, CPU saturada sobe só a CPU, queda de quadros sem saturação sobe o mais ocupado, folga desce, GPU travada não muda, sem `drm-page-flips` vira o D12 nos dois, teto térmico respeitado, `min_freq` da GPU devolvido ao parar, mesmo cliente em dois fds conta uma vez); no GA36, um jogo leve e um pesado mostram o gargalo e os degraus no `powerctl.state` e na linha `power OK controller` (J1).
- [x] 2.6 Ajuste manual por recurso e por jogo (D18): chaves `gpu_min` e `controller=auto` no validador do shell e no editor do `lume-core`; linha `game <chave> <perfil>` (só no cartão) com a precedência jogo > core > classe > `game` e o piso do GA36; `lume_core::power::game_key` (FNV-1a 64 do caminho relativo a `ROMS/roms/`, 16 dígitos hex) e a mensagem `game <sistema> <core> <chave>` do `lume-run`; `power.state` com as linhas `game`; `docs/LOGS.md` com a gramática, o `powerctl.state` e os eventos. Verificação: testes do shell (perfil por jogo vence core e classe, `game` na imagem recusado, `gpu_min` fora da tabela recusado, `gpu_min` acima de `gpu_max` recusado, mensagem antiga de 3 palavras continua valendo), testes Rust (chave estável e sem nome, linha do FIFO com 4 palavras, editor grava `Setting::Game` e `gpu_min`); no GA36, um perfil por jogo no `power.conf` vale com `reload` no jogo seguinte (J3).

## 3. Avisos do supervisor e launcher

- [x] 3.0 Protótipo (`docs/lume-launcher/prototipo/`, D9): a marca de carga na bateria da barra de status e o aviso de bateria fraca, nos temas e nos três idiomas; medidas a 640x480 no `docs/lume-launcher/design-das-telas.md`. Verificação: o usuário aprova no navegador a 640x480 (aprovação anotada com a data).
- [x] 3.1 `lume-run` (D1): `game <sistema> <core>` antes do `exec` do jogo e `end` depois de o cgroup esvaziar, pelo escritor da 1.1. Verificação: testes em `lume/lume-run/tests/run.rs` com um FIFO de teste (ordem das mensagens; sem leitor, o jogo abre igual) e o RSS do supervisor sem mudança (requisito do `game-runners`); no aparelho, os eventos `power` no `events.log` (J1).
- [x] 3.2 (Provado: a tela escurece de 80 para 16 em 2 min e o primeiro botão só devolve a luz (R36S, 2026-11-19); a marca de carga aparecendo e sumindo (usuário, GA36, 2026-11-18).) `lume-ui` (D9): `menu` na primeira tela e ao voltar do ocioso; depois de 2 minutos sem botão (ou do `idle after=` do `power.conf`; `0` desliga), `idle` e luz em `min(10%, brilho do usuário)` sem gravar, o primeiro botão devolve o brilho e é consumido; bateria lida a cada 5 s, marca de carga desenhada pela régua da 3.0, aviso de bateria fraca no mesmo limite do serviço, textos en/pt/es. Verificação: testes de tela em `lume/lume-ui/tests/ui.rs` (escurecer, botão consumido, brilho salvo intacto, marca de carga, aviso uma vez por descarga) e o teste de régua da marca; o uso de CPU do launcher parado continua abaixo de 1% (requisito "Parado não consome CPU"); no aparelho, J3 e J4.

## 4. DRAM do A33 e core do SNES

- [x] 4.1 `hwinfo` (D11, P-23): no GA36, ler com o `lume-devmem` os registradores da DRAM e gravar o clock efetivo no `hw/boot-<n>.txt`. Verificação: teste do `hwinfo` com o `lume-devmem` falso; no GA36, o clock no retrato e a conta anotada no P-23 (J1).

- [x] 4.2 (Provado: o `snes9x2005_plus` abre e roda nos dois consoles (60,1 no GA36, 2026-11-18; `open-close-snes` nos dois em 2026-11-19); o save state antigo ficou no P-110.) Core do SNES (D15, spec `game-library`): `aports/libretro-snes9x2005-plus` no commit mais novo do upstream `libretro/snes9x2005` (`a79dfe9`, `pkgver` pela data), `USE_BLARGG_APU=1`, build padrão do upstream sem flags por CPU, `arch="all"`, `sha512sums` refeito; `aports/libretro-snes9x` removido e as referências a ele em `lume/`, `docs/` (`LAUNCHER.md`, `aports/README.md`) e nos testes trocadas pelo `snes9x2005_plus` ou retiradas; o `systems.json` continua com `snes9x2005_plus` padrão, sem alternativos nem troca por arquitetura, e um teste de catálogo passa a exigir isso. Verificação: o `sha512` confere com o tarball do upstream; testes de unidade e de catálogo verdes; nenhuma referência ao `libretro-snes9x` fora do arquivo de changes; na J1, um jogo de SNES abre no `snes9x2005_plus` novo no GA36 e no R36S e um save state antigo abre.

## 5. GA36: medição, perfis, build final e provas

- [x] 5.1 (Feito em 2026-11-18 (builds `20261118-005049` a `-011308`, boots 180 a 182).) Build de medição: pacotes da onda 0 e 1 e o kernel do GA36, nas duas arquiteturas, um `lume pkg` por vez sob a proteção de calor, e `lume push`. Verificação: os `.apk` e o kernel novos no repositório local e o `push` terminando com `ok`.
- [x] 5.2 (Movida para o P-108 em 2026-11-19, decisão do usuário: teste demorado, ~3 h por console com a bateria entre 40% e 90%, fica para o futuro; já feito no GA36: custo do `logd` e do `sugov:0`, governors novos, DRAM no retrato e eventos `power`, `docs/BRINGUP-GA36.md`.) Janela J1 no GA36: custo do `logd` e do `sugov:0` (1.2), governors novos (2.1), DRAM no retrato (4.1), eventos `power` (3.1); depois as sessões do D5 por classe e por candidato com o modo manual, com e sem o controlador nos pesados. Verificação: tabela do `lume power report` (1.3) no `design.md` por classe e candidato (corrente média, eventos `slow`, temperatura máxima, clock médio), sem nome de jogo, e o candidato escolhido por classe pela regra do D5; o CSV do relatório, com a versão de cada core (build padrão, linha de base do P-10), em `docs/referencia/medicoes/game-governor/`.
- [x] 5.3 (Movida para o P-108 em 2026-11-19 com a 5.2/6.1, decisão do usuário: depende da medição longa.) Escrever `ga36.conf` com os perfis escolhidos na 5.2 (classes dos sistemas do `systems.json`, exceções por core que a medição mostrou, limites da bateria, o `game_min` e o piso do GBA conferidos pela medição, nunca abaixo de 600 MHz; os perfis de jogo com `controller=auto` se a J1 mostrar o controlador por gargalo sem quadros a mais perdidos que o perfil sem ele); o `r36s.conf` continua igual ao padrão do kernel. Verificação: os testes do validador da 1.1 com o arquivo real contra a tabela de OPP do GA36 (copiada do aparelho para os testes) e a tabela do `design.md` citada em cada perfil.
- [x] 5.4 (Movida para o P-108 em 2026-11-19 com a 5.2/6.1, decisão do usuário: depende da medição longa.) Build final do GA36 com os perfis da 5.3 (armv7) e `lume push`. Verificação: `.apk` novos e `push` com `ok`.
- [x] 5.5 (Movida para o P-110 em 2026-11-19, decisão do usuário: o resto das provas pelo cabo (controlador, Fn+Start num jogo travado, `enabled 0`, piso do GBA, tempo do boot).) (Parte à mão feita pelo usuário em 2026-11-18: o menu do sistema pelo Fn num jogo, a marca de carga aparecendo e sumindo com o carregador, CPS-1 e GBA lisos com o controlador; a sessão longa sem carregador até o desligamento crítico foi para o P-98, decisão do usuário; a comparação dos `slow` com a tabela da medição foi para o P-108 com a 5.2. O resto é pelo cabo, com os perfis atuais.) Janela J3 no GA36: os eventos `power` do boot ao menu, ao jogo de cada classe e de volta; o tempo do boot com o perfil `boot` comparado com o de antes (anotado no P-58); a tela escurece em 2 minutos parada e o primeiro botão só devolve a luz; a marca de carga aparece e some em até 5 s; numa sessão longa sem carregador, o aviso aparece uma vez no jogo e o console desliga sozinho no nível crítico com o save interno gravado e o boot seguinte com `previous clean`; numa sessão de cada classe, nenhum `slow` a mais que na tabela da 5.2; o controlador num jogo pesado (frequência variando, linha `power OK controller`); Fn+Start encerra um jogo travado (2.4); `enabled 0` no `power.conf` devolve o padrão do kernel depois do reboot, com o piso nos jogos; no GBA, nenhuma amostra abaixo do mínimo do perfil (fora do teto térmico); uma linha mudada no `power.conf` com `reload` pelo cabo vale no jogo seguinte sem reboot e aparece no `power.state`. Verificação: resultado no `docs/BRINGUP-GA36.md`, sem nome de jogo, e o `lume power report` antes e depois lado a lado no `design.md`.

## 6. R36S (depois do GA36): medição, perfis, build final e provas

- [x] 6.1 (Movida para o P-108 em 2026-11-19, decisão do usuário: teste demorado. Já medido no R36S em 2026-11-19: `logd` 0,38% de um núcleo parado, 1,25% num jogo de SNES e 0,42% num de GBA; `sugov:0` 4,4% parado e 22% no SNES.) Janela J2 no R36S, com o mesmo cartão: o mesmo da 5.2 (sem a DRAM do A33). Verificação: a tabela do R36S no `design.md` e o candidato escolhido por classe.
- [x] 6.2 (Movida para o P-108 em 2026-11-19 com a 5.2/6.1, decisão do usuário: depende da medição longa.) Escrever `r36s.conf` com os perfis escolhidos na 6.1 (mesmas regras da 5.3). Verificação: os testes do validador da 1.1 com o arquivo real contra a tabela de OPP do R36S (copiada do aparelho para os testes) e a tabela do `design.md` citada em cada perfil.
- [x] 6.3 (Movida para o P-108 em 2026-11-19 com a 5.2/6.1, decisão do usuário: depende da medição longa.) Build final do R36S com os perfis da 6.2 (aarch64) e `lume push`. Verificação: `.apk` novos e `push` com `ok`.
- [x] 6.4 (Movida para o P-110 em 2026-11-19, decisão do usuário: o resto das provas pelo cabo no R36S.) (R36S, 2026-11-19, pelo cabo: eventos `power` de menu, jogo e ocioso certos; a tela escurece de 80 para 16 em 2 min e o primeiro botão só devolve a luz; `idle after=300` com `reload` aparece no `power.state` sem reboot. A sessão longa sem carregador fica no P-98, como no GA36; a comparação dos `slow` com a tabela da medição foi para o P-108 com a 6.1; o resto, pelo cabo, com o `r36s.conf` no padrão do kernel.) Janela J4 no R36S, com o mesmo cartão: as mesmas provas da 5.5. Verificação: resultado no `docs/BRINGUP-R36S.md`; no `docs/PENDENCIAS.md`, P-20 (etapa 1), P-60, P-78 e P-83 movidos para "Concluídas", P-23 com a medição anotada e o item 3 do P-64 marcado como feito.

## 7. Laços em segundo plano sem processo por volta (P-112, D20; revisão de 2026-11-19)

Pedido do usuário (2026-11-19): corrigir nesta change o desperdício que a avaliação do coletor
achou (D20). A 1.2 fecha com a medição da 7.6. Modelos propostos na tabela do grafo; o usuário
aprova antes de aplicar.

- [x] 7.1 (Feito em 2026-11-19: `tests/usb/test_usb_gadget.sh` com 60 casos verdes; nenhum processo em 10 voltas paradas, e a mutação de um `cat` por volta é pega (10 vistos); TERM e `stop` saem da espera em menos de 0,15 s. A prova no aparelho fica na 7.6.) `usb-gadget` (`aports/lume-usb/files/usr/libexec/lume/usb-gadget`, D20): `role_watch`, `net_watch`, `pc_watch` e o VBUS lidos com `read -r v < arquivo` e `case`, sem `$( )`, `cat`, `grep` nem `for` dentro do laço; o UDC, o arquivo do papel da porta, os `extcon` e as fontes de energia USB procurados na subida e de novo só quando somem; a espera por `read -t` num FIFO em `/run/lume/usb/` no lugar do `sleep`; 1 s enquanto o estado do UDC muda, 2 s sem mudança; o `stop` acorda o laço pelo FIFO. Nada muda no que o serviço faz: mesma rede, mesmo SSH e MTP pelo cabo, mesmos eventos `usb OK|FAIL`. Verificação: `tests/usb/test_usb_gadget.sh` com os casos novos (a troca de estado do UDC percebida em até 2 s, VBUS falso mantendo a rede, UDC ausente e depois presente, papel da porta trocado pelo ID, `stop` sem esperar a volta) e um teste que conta os processos criados em 10 voltas do laço com o estado parado (zero além da espera); no aparelho, a rede e o SSH pelo cabo voltam depois de tirar e pôr o cabo (7.6).
- [x] 7.2 (Feito em 2026-11-19: o `watch_tree` do `lib.sh` espera por `read -t` num FIFO que os handlers acordam (`watch_wake`), com o debounce do `persist` refeito na espera; `ssh-wifi` a cada 5 s, sem processo desligado ou com o Wi-Fi caído, e só o `ip` de cada volta ligado. Suítes novas e `test_ssh_wifi.sh` verdes (zero processos em 10 voltas paradas); `test_session.sh` e `test_card.sh` verdes; o `test_playlists.sh` falha num caso de catálogo sem relação (segacd no armv7), anterior a esta tarefa.) `persist` e `savesync` (`aports/lume-saves/files/usr/libexec/lume/`) e `ssh-wifi` (`aports/lume-net/files/usr/libexec/lume/ssh-wifi`), D20: leitura sem processo como na 7.1; `persist` e `savesync` esperando por evento (`inotifyd` nos arquivos e pastas que vigiam) no lugar do laço de 1 s, sem perder o que gravam hoje (a configuração persistida, os saves sincronizados no fim do jogo e no desligamento); `ssh-wifi` a cada 5 s com a espera por `read -t`. Verificação: suítes novas `tests/saves/test_persist.sh` e `tests/saves/test_savesync.sh` (um arquivo mudado é gravado, nada parado cria processo) e `tests/net/test_ssh_wifi.sh` com o ritmo novo; `tests/session/test_session.sh` e `tests/card/test_card.sh` verdes.
- [ ] 7.3 Hora do log (D20): o `lume-logd` (`aports/lume-logd/logd.c`) lê `/etc/timezone` a cada lote e, quando muda, `setenv("TZ", ":/usr/share/zoneinfo/<fuso>")` e `tzset()`; o `logd` em shell faz o mesmo com o `TZ` do ambiente. Verificação: `tests/unit/test_lume_logd.py` (um fuso escrito no meio da execução muda a hora das linhas seguintes) e `tests/logs/test_logs.sh`; `sha512sums` do `APKBUILD` atualizado.
- [ ] 7.4 `schedutil` do R36S (D20): `profile menu` e `profile idle` do `r36s.conf` com o `rate_limit_us` do GA36 (100000 no menu, 200000 parado); os perfis de jogo seguem o padrão até o P-108. Verificação: os testes do validador da 1.1 com o arquivo real; no R36S, o `sugov:0` parado medido antes e depois (7.6 ou P-110).
- [ ] 7.5 Build parcial dos pacotes mudados (`lume-usb`, `lume-saves`, `lume-net`, `lume-logd`, `lume-core`, `lume-power`) para os dois consoles, um por vez sob a proteção de calor, e `lume push` para o console no cabo. Verificação: `.apk` novos e o `push` terminando com `ok`; logo depois do boot, a rede e o SSH pelo cabo respondendo (se não, voltar o conjunto anterior pelo `SLOTS.old`, D20).
- [ ] 7.6 Medição pelo cabo no console que estiver no cabo (GA36 primeiro), com o mesmo método de 2026-11-19 (`cache`: ticks próprios e dos filhos em 60 s, o contador `processes` de `/proc/stat` com um script que só lê duas vezes): launcher parado e um jogo de SNES. Meta da spec `boot-runtime`: os laços somando menos de 1% de um núcleo e menos de 60 processos novos por minuto parado; o `lume-logd` continua abaixo de 1%. Também: tirar e pôr o cabo (a rede volta), um save gravado no fim de um jogo, uma mudança no volume persistida depois de reiniciar. Verificação: tabela antes e depois no D20 e no `docs/BRINGUP-<console>.md`; a 1.2 marcada; o P-112 e o P-60 movidos para "Concluídas"; o console que não estiver no cabo fica no P-110.

## Workflow follow-up

- Arquivar a change depois das provas da J3 (5.5) e da J4 (6.4).
- Com os perfis medidos, decidir se o modo escolhido pelo usuário (Desempenho, Equilibrado,
  Economia) e o controlador por FPS (P-20, etapa 3) viram pendências novas.
- As tabelas da 5.2, 5.3 e 6.2/6.3 (cores no build padrão) são a linha de base do P-10: anotar
  no P-10 onde elas estão quando a change for arquivada.
