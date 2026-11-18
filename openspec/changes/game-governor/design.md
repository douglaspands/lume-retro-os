# Design

## Context

Motivação em `proposal.md`; requisitos em `specs/power-profiles` e nos deltas de
`device-support`, `boot-runtime` e `game-launcher`.

Estado atual (kernel 6.18, configurações em `.cache/kbuild/<arch>/.config`):

```
                 GA36 (A33, armv7)               R36S (RK3326, aarch64)
governor         schedutil (padrão)              schedutil (padrão)
outros           só performance                  performance, ondemand, userspace
                                                 (powersave e conservative como módulo)
OPP da CPU       120 .. 1008 MHz                 600/816/1008/1200/1296 MHz
cpuidle          não (CPU_IDLE off)              sim (PSCI, governor menu)
hotplug          sim                             sim
GPU devfreq      simple_ondemand                 simple_ondemand, userspace
```

- **Medido no GA36 (P-60):** o `logd` e os processos que ele dispara gastam ~30% de um núcleo,
  e a thread `sugov:0` mais ~40%; hipótese: os picos do `logd` a cada 5 s mudam o clock, e no
  A33 cada mudança passa pelo regulador do AXP pelo RSB.
- **Fábrica do GA36** (`docs/referencia/ga36-emuelec/sistema/cpu-ondemand-tune`): `ondemand`
  com `up_threshold 30`, `sampling_down_factor 10` e piso de 600 MHz no jogo.
- **Medições que já existem**: as métricas do `logd` têm clock e ocupação por núcleo, `bat_ma`,
  `fps` (pelo patch 0004 do RetroArch) e os eventos `game FAIL slow`/`full speed again`.
- **Pontos de aviso**: o `lume-run` sabe o início e o fim do jogo, o sistema e o core; o
  `lume-ui` sabe quando está na tela e quando está parado.
- **Bateria no launcher** (`lume/lume-ui/src/system.rs:91-100`, `main.rs:133-146`): o `lume-ui`
  já lê `capacity` e se está carregando, mas a cada 30 s, e o desenho da bateria ignora a carga
  ("no charging mark: the prototype has none", `app.rs:1460`). É a causa do P-78.
- **Desligamento**: o `session` grava os dados e chama `poweroff`; parar o frontend faz o
  `lume-run` pedir a saída ao jogo pela política do runner (fim `session`), o que grava a SRAM.
- **Teste que hoje trava a decisão do kernel**: `tests/unit/test_ga36_kernel_config.py:31-34`
  exige que o fragmento não toque em `CPU_FREQ_GOV_*`.

## Goals / Non-Goals

**Goals:**
- Valores de perfil escolhidos por medição, com a regra de nunca perder quadros em relação ao
  padrão de hoje.
- Troca de perfil só nas fronteiras de cenário, num serviço que não custa nada parado.
- Medições confiáveis: o coletor deixa de pesar antes de medir qualquer perfil.

- Achar o recurso que limita cada jogo (CPU, GPU, ritmo, térmico, memória) e subir só ele,
  descendo o que sobra (D17), com cada recurso ajustável à mão por sistema e por jogo (D18).

**Non-Goals:**
- A tela de ajustes (P-85, P-91): esta change deixa o arquivo, o editor e o estado prontos.
- Variar o clock da DRAM (D19, P-23 etapa 4).
- Modo escolhido pelo usuário (Desempenho, Equilibrado, Economia).
- Otimizar os cores (flags por CPU, PGO; P-10): adiado de propósito pelo usuário (2026-11-17).
  Todos os cores ficam no build padrão do upstream, inclusive o `snes9x2005_plus` (D15), para a
  medição desta change isolar o ganho do sistema; as tabelas do D5 viram a linha de base do P-10.
- Overclock, clock da DRAM variável, mudar a tabela de OPPs ou as zonas térmicas.

## Decisions

### D1. Cenários e quem avisa

```
 boot --(serviço sobe: perfil boot)--> menu <--(lume-ui na tela)
                                        |  ^
       (lume-ui sem botão N min) idle <-+  |  (primeiro botão)
                                        |  |
       (lume-run: game <sistema> <core>)v  | (lume-run: end)
                                       jogo
```

| Cenário | Quem avisa | Mensagem |
|---|---|---|
| boot | o próprio serviço ao subir | — |
| menu | `lume-ui` ao mostrar a primeira tela e ao voltar do ocioso | `menu` |
| idle | `lume-ui` depois de N minutos sem botão (o mesmo prazo de escurecer) | `idle` |
| jogo | `lume-run` antes do `exec` do jogo | `game <sistema> <core>` |
| fim do jogo | `lume-run` depois de o cgroup esvaziar | `end` |

O serviço registra cada troca no `events.log`: `power OK profile: <cenário> -> <perfil>`.

### D2. Serviço `lume-power` sem laço caro

Shell no pacote `lume-power`, como root (escreve no sysfs de cpufreq, de hotplug e do devfreq),
no runlevel `boot`, logo cedo, aplicando o perfil `boot`. Lê as mensagens de um FIFO
`/run/lume/power` (grupo `game`, gravável pelo `lume-ui` e pelo `lume-run`) com `read -t 60`:
dorme até chegar mensagem, e acorda no máximo a cada 60 s para a bateria (D7). Os escritores
abrem o FIFO sem bloquear e ignoram a falha se o serviço não estiver rodando: o jogo e o
launcher nunca esperam por ele.

*Alternativas descartadas:* o `lume-run` aplicar o perfil (não roda como root e não está vivo no
launcher); udev dando escrita no cpufreq ao grupo `game` (espalharia a política em dois
programas e o hotplug ficaria aberto a qualquer processo do usuário); o GameMode (P-83:
polkit, ganhos pensados para GPU de PC, preso ao RetroArch).

### D3. Arquivo de perfis

`/usr/share/lume/power/<console>.conf` (`ga36`, `r36s`), em linhas lidas com `read` do shell,
sem `awk` por mensagem:

```
# profile <nome> chave=valor...   (khz; cores = núcleos ligados; gpu_max em Hz)
profile boot    governor=performance
profile menu    governor=schedutil min=120000 max=648000 cores=2 gpu_max=144000000
profile idle    governor=schedutil min=120000 max=480000 cores=1 gpu_max=144000000
profile light   governor=schedutil min=600000 max=1008000 cores=2
profile medium  governor=ondemand  min=600000 max=1008000 cores=4 up_threshold=30 sampling_down_factor=10
profile heavy   governor=performance cores=4
profile game    governor=schedutil min=600000 cores=4      # sistema sem classe
limit game_min=600000                                      # piso dos perfis de jogo (só no ga36.conf)
class nes light
class psx heavy
core  snes9x2005_plus heavy                                # exceção por core
```

Os números acima são só o formato: os valores saem da medição (D5). Validação ao subir: cada
clock tem de estar em `scaling_available_frequencies` (ou entre `cpuinfo_min_freq` e
`cpuinfo_max_freq` e num OPP do devfreq), cada governor em `scaling_available_governors`,
`cores` entre 1 e o número de núcleos. Um perfil inválido é recusado inteiro (log) e o cenário
usa o padrão do kernel, com a exceção do piso abaixo. Um `ROMS/system/lume/power.conf` opcional
sobrescreve linhas (avançado, documentado, validado igual; é também o arquivo que a interface
vai escrever, D16) e aceita mais duas linhas:

```
enabled 0          # desliga os perfis: o serviço devolve o padrão do kernel e só registra
idle after=300     # segundos sem botão até o launcher parado (padrão 120; 0 desliga)
```

O `lume-ui` lê a linha `idle` do mesmo arquivo para o prazo de escurecer (D9). Um perfil pode
ter `controller=load` (D12).

**Piso dos jogos no GA36 (pedido do usuário, 2026-11-17):** em jogo, o mínimo da CPU do GA36
nunca é o menor clock da tabela. A linha `limit game_min=<khz>` do arquivo do console vale para
todo perfil usado em jogo (as classes, as exceções por core, o `game` e o que vier do
`power.conf`): um perfil de jogo sem `min` recebe o `game_min`; um `min` abaixo dele recusa o
perfil (log); o perfil de jogo recusado cai no governor padrão do kernel **com**
`scaling_min_freq` no `game_min`; com `enabled 0` o piso dos jogos continua (só ele). O
`game_min` tem de estar na tabela de OPP, senão o arquivo inteiro é recusado e o serviço usa o
maior OPP que não passe de 600 MHz. O `game_min` não vale para o `power.conf` mudar: ele fica
só no arquivo da imagem. Valor inicial: **600 MHz**, o piso já avaliado no GA36 com o EmuELEC
(`R36S GA36-MB V1.2-20260416`, feature `44-cpu-ondemand` e change arquivada
`2026-10-16-cps2-fbalpha2012-ondemand-afinado`): o ondemand de fábrica descia a 240–504 MHz no
jogo, com quedas de FPS e som picotado em CPS2, PSX e SNES; o afinamento usado lá era
`ondemand`, `up_threshold` 30, `sampling_down_factor` 10 e `scaling_min_freq` 600000. A
medição (D5) pode subir o piso de uma classe (o `min` do perfil acima do `game_min`), nunca
descer. O R36S não tem `limit` até a medição dele (6.1) mostrar se precisa.

**Revisão pelo GBA (usuário, 2026-11-17: "a resposta desse clock é o emulador de GBA"):** o
ondemand de fábrica já tinha sido descartado no GBA porque o desempenho mudava a cada curva (o
governor seguia a carga sempre atrasado). O log do EmuELEC no GA36
(`docs/referencia/ga36-emuelec/medicoes/r36-thermal*.csv`, já com o piso de 600 MHz, amostra a
cada 5 s, agregado por core e sem nome de jogo) mostra que 600 MHz não basta para o GBA:

| Sistema (core), ondemand com piso 600 | Amostras | Clock médio | Abaixo de 1000 MHz | Em 1200 MHz | Núcleo mais ocupado (média / p90) | Corrente média |
|---|---|---|---|---|---|---|
| GBA (gpsp) | 1903 | 1093 MHz | 25% (600 a 912) | 66% | 27% / 34% | 598 mA |
| GBA (gpsp), performance | 6 | — | — | — | 25% / 35% | 573 mA |
| N64 (mupen64plus) | 182 | 992 MHz | 34% (62 amostras em 600) | 63% | 55% / 100% | — |
| PSP (PPSSPP) | 2350 | 1027 MHz | 28% (625 em 600) | 63% | 64% / 80% | 752 mA |
| PC Engine (mednafen_pce_fast) | 99 | 726 MHz | 80% (75 em 600) | 16% | 29% / 32% | — |
| NES (fceumm) | 64 | 1143 MHz | 19% | 78% | 25% / 27% | 561 mA |

Leitura: no GBA o clock fica dois terços do tempo no máximo e o resto oscila entre 600 e
1104 MHz; é essa oscilação que o usuário sentiu, e a economia dela é pequena (a corrente com o
`performance` não foi maior nas poucas amostras). N64 e PSP chegam a ficar em 600 MHz com o
núcleo cheio. Já o PC Engine roda em 600 MHz quase sempre, sem queixa: o piso geral de 600 MHz
serve aos leves. Valores iniciais do `ga36.conf` (antes da medição, D5):
- `limit game_min=600000` para todos os jogos;
- classe própria `gba` com `min=1008000` (o degrau abaixo do clock médio medido), sem descer
  a 600–912 MHz no meio do jogo;
- classe `heavy` (N64, PSP, NDS) com `min=1008000`.

**Correção (2.2, 2026-11-17):** no kernel mainline a tabela de OPP do A33
(`sun8i-a33.dtsi`) vai de 120 a **1008 MHz**; os 1104 e 1200 MHz eram do kernel 4.9 do
EmuELEC. Logo `min=1008000` é o clock travado no máximo do mainline (o mesmo que
`performance`), e o GA36 no mainline joga o GBA com no máximo 84% do clock que o EmuELEC usava
nos 66% das amostras em 1200 MHz. A medição da J1 compara no GBA os pisos de 816, 912 e
1008 MHz (este o máximo) e o padrão do kernel como referência; vence pela regra do D5, com a
ressalva de que um `slow` a mais que o travado em 1008 MHz desclassifica o candidato. Se o GBA
tiver `slow` mesmo travado em 1008 MHz, o limite é a tabela de OPP (P-20/P-23, overclock fora
desta change). A cena 0 da DRAM
que o EmuELEC usava em jogo não existe no kernel mainline (sem devfreq da DRAM do A33): o P-23
só mede.

**Decisão do usuário (2026-11-18), bateria primeiro:** "se o game roda com o clock mais baixo,
então mantém". A classe `gba` (mínimo de 1008 MHz) saiu do `ga36.conf`: a oscilação sentida no
GBA era o ritmo dos quadros no painel de 55,7 Hz (P-93), resolvido com o vídeo em thread, e o
controlador por gargalo rodou uma corrida de GBA a 912 MHz na velocidade cheia. O GBA usa o
perfil `game` (controlador a partir do piso de 600 MHz). A classe `heavy` continua travada em
1008 MHz porque nunca foi medida no GA36 (os sistemas dela não estão no catálogo dele).

### D4. Como um perfil é aplicado

Ordem, para nunca passar do limite: liga os núcleos que faltam, ajusta `scaling_min_freq` e
`scaling_max_freq` (descendo primeiro o mínimo, subindo primeiro o máximo), troca o governor,
aplica os parâmetros do governor, desliga os núcleos a mais (nunca o `cpu0`), ajusta o
`min_freq` e o `max_freq` do devfreq da GPU (`gpu_min`, `gpu_max`). O perfil muda a GPU só nas
fronteiras; dentro do jogo, só o controlador por gargalo (D17) mexe no piso da GPU. O RetroArch
com vídeo em thread e o áudio não são afetados por desligar núcleos porque a troca acontece
antes do `exec` do jogo.

*Revisão (2026-11-18):* a restrição antiga "GPU nunca no jogo" vinha do P-20 (Mali sem
refrigeração). A tarefa 9.10 ligou o `CONFIG_DEVFREQ_THERMAL` (a Mali do GA36 é dispositivo de
refrigeração da zona `cpu-thermal`), e o próprio `simple_ondemand` já troca o clock da GPU no
meio do jogo, dentro do `[min_freq, max_freq]`. Mudar o piso no jogo não cria nenhuma troca
de clock que o kernel já não faça; a J1 confere (5.2) que nenhuma trava aparece.

### D5. Medição que escolhe os valores

Pré-requisito: o `logd` barato (D8), senão ele falseia a corrente e a ocupação.

- **Candidatos por classe:** `K` (governor padrão, a linha de base), `S+piso` (schedutil com
  mínimo), `O` (o afinamento do EmuELEC: ondemand, `up_threshold` 30, `sampling_down_factor` 10,
  mínimo 600 MHz), `S+rate` (schedutil com `rate_limit_us` maior, hipótese do P-60) e, no GA36,
  cada um com 2 núcleos e com 4. No GA36 todo candidato de jogo tem mínimo de pelo menos
  600 MHz (D3, piso dos jogos); o `K` sem piso é medido só como referência e não pode ser
  escolhido; no GBA e nos pesados os candidatos são os pisos de 816, 912 e 1008 MHz (o máximo
  do mainline no A33; D3, revisão pelo GBA e correção).
- **Sessão:** o mesmo ponto de cada jogo de teste por save state, 10 minutos por candidato, sem
  carregador, bateria entre 40% e 90% (a rodada 1 do `snes9x2005_plus` foi descartada por
  bateria baixa), console já aquecido.
- **Métricas:** corrente média (`bat_ma`), eventos `game FAIL slow`, temperatura máxima, clock
  médio. O serviço tem um modo manual (`lume-power set <perfil>` pelo cabo) para trocar de
  candidato sem rebuild.
- **Regra:** por classe, o candidato de menor corrente média sem mais eventos `slow` que o `K`.
  Resultados só agregados por sistema e classe, nunca por jogo (regra das ROMs de teste).
- **Linha de base dos cores:** toda sessão roda os cores no build padrão do upstream (P-10
  adiado). As tabelas de antes e depois, com a versão de cada core, ficam neste design e o CSV
  do `lume power report` em `docs/referencia/medicoes/game-governor/`, para a otimização dos
  cores (P-10, change de cores P-80) ser medida depois contra os mesmos números.

### D6. Boot

O perfil `boot` (`performance`) vale do início do serviço até a primeira tela do launcher. O
tempo do boot (`boot OK completed`) é anotado antes e depois; se o ganho não aparecer, o perfil
`boot` vira igual ao padrão e a linha fica registrada.

### D7. Bateria fraca

O serviço lê `capacity` e `status` da fonte `Battery` a cada mensagem e a cada 60 s. Com
`Discharging`:
- **aviso (5%)**, uma vez por descarga: no jogo do RetroArch, `SHOW_MSG` por UDP em
  `127.0.0.1:55355`, com o texto no idioma do sistema (`ui_lang` do `lib.sh`); no launcher, o
  próprio `lume-ui` mostra o aviso ao ler a bateria (D9), com o mesmo limite;
- **crítico (3%)** em duas leituras seguidas (uma queda de tensão sob carga não desliga): grava
  `power OK shutdown: battery critical` e chama `poweroff`. O caminho normal faz o resto: o
  OpenRC para o frontend, o `lume-run` pede a saída ao jogo (fim `session`, SRAM gravada), os
  serviços descarregam os logs e os saves.

Os limites ficam no arquivo de perfis (`battery warn=5 critical=3`).

### D8. `logd` barato (P-60)

Trocar os processos de cada amostra por leituras com `read` do shell (`/proc/stat`,
temperatura, frequência, bateria), o `trace_kernel` pelo `/dev/kmsg` sem bloquear no lugar de
dois `dmesg`, o `pidof` uma vez por amostra, a data com o `printf '%(...)T'` do shell quando
houver, senão uma vez por lote. Medir o `logd` e o `sugov:0` em 60 s, antes e depois, nos dois
consoles. Se o shell não chegar a 1%, o coletor da amostra vira um binário em C pequeno, como o
`lume-input`, mantendo o formato das métricas (`docs/LOGS.md`).

### D9. Launcher

- A thread da bateria passa de 30 s para 5 s (duas leituras pequenas do sysfs; conferir o
  requisito "Parado não consome CPU").
- Marca de carga na bateria: primeiro no protótipo, depois no `lume-ui` com a régua.
- Ocioso: depois de 2 minutos sem botão no launcher (`idle after=` do `power.conf`, D3), o `lume-ui` manda `idle` e baixa a luz
  para `min(10%, brilho do usuário)` sem gravar o valor; o primeiro botão devolve o brilho,
  manda `menu` e é consumido.
- Aviso de bateria fraca: o aviso curto (toast) que o tema já tem, em en/pt/es.

### D10. Kernel do GA36

`board/ga36/kernel.config` ganha `CONFIG_CPU_FREQ_GOV_ONDEMAND=y` e
`CONFIG_CPU_FREQ_GOV_CONSERVATIVE=y`, sem mudar o padrão (`schedutil`). Também
`CONFIG_CPU_FREQ_GOV_USERSPACE=y` (faltava no GA36 e o controlador do D12 precisa dele) e
`CONFIG_CPU_FREQ_STAT=y` (o `stats/time_in_state` dá o tempo exato em cada clock para a
medição do D5). No R36S, ondemand e userspace já vêm no kernel e o conservative é módulo. O teste
`test_fragment_keeps_mainline_cpufreq_and_thermal` passa a exigir esses dois e a proibir
`CPU_FREQ_DEFAULT_GOV_*` e `THERMAL_DEFAULT_GOV_*`.

### D16. Ajustes prontos para a interface (pedido do usuário, 2026-11-17)

Mais tarde estes ajustes vão ser mudados pela interface (tela de Energia nas Configurações,
P-85); esta change não faz a tela, mas deixa tudo o que ela precisa:
- **Um arquivo só do usuário:** o `ROMS/system/lume/power.conf` (D3), escrito à mão pelo PC ou
  pela interface, com a mesma gramática. A imagem nunca o traz; as camadas são o arquivo do
  console (imagem) e, por cima, o `power.conf`.
- **Editor no `lume-core`:** módulo Rust que lê, valida, muda uma linha (`profile`, `class`,
  `core`, `battery`, `idle`, `enabled`) e grava o `power.conf` mantendo os comentários, a ordem
  e as linhas que ele não conhece, com gravação atômica (arquivo temporário, `fsync`,
  `rename`). Ele valida contra o estado publicado pelo serviço (abaixo), então a interface só
  oferece valores que o serviço aceita.
- **Recarregar sem reiniciar:** a mensagem `reload` no FIFO faz o serviço ler os arquivos de
  novo e reaplicar o perfil do cenário em curso (no jogo, só na próxima fronteira, como
  qualquer troca de perfil).
- **Estado publicado:** o serviço grava `/run/lume/power.state` (legível pelo grupo `game`, uma
  chave por linha) a cada carga e troca: console, `enabled`, clocks e governors disponíveis,
  número de núcleos, `game_min`, os perfis em vigor com a origem de cada um (`image` ou
  `card`), as classes e exceções, o cenário e o perfil atuais e os perfis recusados com o
  motivo.

*Alternativa descartada:* um segundo arquivo só da interface por cima do `power.conf`: duas
fontes de verdade para o usuário, e uma mudança feita no PC sumiria sob a da tela.

### D11. DRAM do A33 (P-23, só medir)

O `hwinfo` lê com o `lume-devmem` os registradores do P-23 (`PLL_DDR1_CTRL_REG`,
`PLL_DDR1_PAT_CTRL_REG0/1`, `DRAM_CFG_REG`) e grava o clock efetivo no `hw/boot-<n>.txt` do
GA36. Nada muda no clock.

### D12. Controlador pela carga (P-20, etapa 2)

Um binário pequeno em C, `lume-powerctl` (aport por arquitetura, como o `lume-input`), que o
`lume-power` liga ao aplicar um perfil de jogo com `controller=load` e mata no `end`:
- põe o governor em `userspace` e escolhe a frequência pelo `scaling_setspeed`, entre o `min` e o
  `max` do perfil e nunca acima do `scaling_max_freq` atual (que o resfriamento do kernel baixa);
- a cada 250 ms lê o `utime` da thread mais ocupada do processo principal do cgroup do jogo
  (`/proc/<pid>/task/*/stat`);
- sobe um degrau da tabela acima de 85% de um núcleo por 1 s, desce um degrau abaixo de 50% por
  3 s;
- grava uma linha `power OK controller` no `events.log` ao parar, com o tempo em cada degrau.

*Por que C e não o shell do serviço:* o laço de 250 ms custaria o que o P-60 quer tirar do
`logd`. *Alternativa descartada:* mexer só no `scaling_min_freq` com outro governor ativo (os
dois brigariam pela frequência).

### D13. Prioridade do jogo

O `lume-power` não recebe o pid pelo FIFO (a mensagem `game` sai antes do `exec`): 2 s depois
do `game`, ele acha o cgroup mais novo em `/sys/fs/cgroup/lume/game-*` e aplica `nice -5` e
`ioprio` best-effort 2 a todos os processos e threads dele, e repete 2 s depois para os que
nasceram no meio; os filhos herdam. O `lume-input` passa a rodar com `nice -10` (acima do
jogo), para o Fn+Start encerrar um jogo travado. Nada em tempo real. *Alternativa descartada:*
`cpu.weight` do cgroup (só compara irmãos do mesmo pai; os serviços do OpenRC não são irmãos).

### D14. Relatório de energia no PC

`lume power report [--since <boot>] [--console ga36|r36s]` (`src/lume_tool/power_report.py`) lê
pelo cabo as métricas e o `events.log` da `ROMS/logs/` e resume por cenário e por sistema:
corrente média (`bat_ma`), FPS contra o nominal, eventos `game FAIL slow`, CPU por núcleo,
clock médio, temperatura máxima e o custo do `logd` e da `sugov`. Saída em tabela e em CSV em
`cache/`, sem nome de jogo. É a ferramenta das tabelas do D5 (antes e depois).

### D15. Core do SNES

Pedido do usuário (2026-11-17): um único core de SNES, o `snes9x2005_plus`, padrão em todas as
arquiteturas, sem versão otimizada. Entra nesta change porque os perfis são medidos jogo a jogo
com o core da imagem: trocar o core depois invalidaria a classe e a exceção por core do SNES.
- **Versão:** o aport `aports/libretro-snes9x2005-plus` sai do commit de 2022 da fábrica do GA36
  (`fd45b0e`, `0_git20220725`) para o mais novo do upstream `libretro/snes9x2005` (`a79dfe9`, de
  2026-09-26; `pkgver` pela data do commit), com o `sha512sums` refeito.
- **Build:** o padrão do upstream (`make -f Makefile USE_BLARGG_APU=1`, `-O2`), em `arch="all"`;
  nenhuma flag por CPU (o build otimizado para o A33 do P-10 fica para a change de cores, P-80).
- **Repositório:** o Alpine 3.24 não tem `snes9x` (só `bsnes` e `beetle-bsnes`, pesados para o
  A33), então o pacote continua no nosso `aports/`. O aport `libretro-snes9x` (desligado desde
  2026-11-11) sai, com as referências a ele em `lume/`, `docs/` e nos testes.
- **Catálogo:** o `systems.json` já tem `snes9x2005_plus` como padrão, sem alternativos nem
  troca por arquitetura; um teste passa a garantir isso (spec `game-library`).

### D17. Controlador por gargalo (`controller=auto`, pedido do usuário, 2026-11-18)

Queixa do usuário: "alguns jogos simples estão com uma performance ruim; ora parece que a GPU
não está com a potência que deveria, ora parece que a CPU está com potência demais". Pedido:
o sistema identifica o gargalo e ajusta o recurso que está prejudicando, por exemplo subir a
GPU em vez da CPU. Isto amplia o D12 (que só olha a CPU) e cumpre a "Ampliação" do P-20.

Hipóteses para os jogos simples, todas cobertas pelos sinais abaixo: (a) o `simple_ondemand`
da GPU faz a média da carga e, num jogo leve que desenha em rajadas, fica em 144 MHz e entrega
o quadro tarde (a mesma doença do `schedutil` na CPU, D3); (b) a CPU no piso alto esquenta o A33
e a zona térmica é uma só para a CPU e a GPU, então CPU sobrando rouba teto da GPU; (c) o coletor
de métricas e a `sugov:0` (P-60, já trocados na 1.2) roubando tempo de núcleo.

**Sinais**, por janela de 1 s, todos de fora do processo do jogo e sem patch novo:

| Sinal | Fonte | Uso |
|---|---|---|
| Quadros entregues por segundo | `drm-page-flips` no `fdinfo` dos fds do DRM do jogo (patch 0036, os dois consoles) | queda de quadros |
| Ocupação da GPU | `drm-engine-*` no `fdinfo` (GA36: `gp`/`pp` do patch 0035; R36S: `fragment`/`vertex-tiler` do `panfrost`, com o `profiling` ligado pelo serviço) | gargalo de GPU |
| Ocupação da CPU | thread mais ocupada do cgroup do jogo (`/proc/<pid>/task/*/stat`, como no D12) | gargalo de CPU |
| Teto térmico | `scaling_max_freq` da CPU e `max_freq` efetivo da GPU | não brigar com o kernel |
| Memória | `MemAvailable` e `CmaFree` do `/proc/meminfo` | só diagnóstico (D19) |

Os fds do DRM do jogo são achados a cada 2 s (`readlink` de `/proc/<pid>/fd/*` apontando para
`/dev/dri/`) e o mesmo cliente aberto duas vezes conta uma só (`drm-client-id`). O alvo de
quadros é o maior ritmo visto nos últimos 30 s (60 ou 50 Hz num jogo do RetroArch; 30 num jogo
que desenha a 30), então um jogo que roda abaixo do painel por desenho não é visto como lento.

**Regra**, um degrau por vez, cada recurso com a sua faixa e o seu teto:
1. Recurso saturado (ocupação acima de 85% por 1 s) sobe um degrau: CPU pelo `scaling_setspeed`
   (governor `userspace`, como no D12), GPU pelo piso `min_freq` do devfreq (o `simple_ondemand`
   continua livre para ir acima do piso).
2. Queda de quadros (abaixo de 90% do alvo em duas janelas seguidas: um core de 60 Hz no painel
   de 55,7 Hz do GA36 oscila sozinho entre 53 e 55) sem nenhum saturado e com o recurso
   mais ocupado em pelo menos 50%: sobe esse recurso (gargalo de ritmo, `pacing`: a carga média
   é moderada, mas o quadro chega tarde, hipótese a). Queda com os dois abaixo de 50% não é
   problema de clock (`sync`: vsync, áudio, painel mais lento que o core) e não sobe nada.
3. Recurso folgado (abaixo de 50% por 3 s), sem queda de quadros por clock nesses 3 s (uma
   queda `sync` não impede) e sem subida nos últimos 5 s: desce um degrau (é a "CPU com
   potência demais" da queixa, hipótese b).

**Medido no GA36 (2026-11-18, antes do controlador):** num jogo de NES o core roda a 60,3
quadros/s, o painel faz 55,7 vblanks/s e só 42 a 47 trocas de quadro por segundo chegam ao
painel, com a thread principal em ~10% e a GPU em 5 a 8%; GPU no máximo, CPU em `performance` e
`video_vsync` desligado não mudam isso (43, 47, 43). É o caso `sync` da regra 2, e a causa vai
para o P-93 (fora desta change): subir clock nesse caso só gastaria bateria.
4. O teto térmico do kernel manda: nunca se escreve acima dele; tempo sob teto é registrado.
5. Sem sinal de quadros (kernel sem o patch 0036, ou jogo sem DRM) o controlador vira o D12 nos
   dois recursos (só as regras 1 e 3).

Um recurso só é controlado quando a faixa dele tem mais de um degrau: `min=max` trava a CPU e
`gpu_min=gpu_max` trava a GPU (D18). O controlador grava a cada mudança o
`/run/lume/powerctl.state` (degrau atual de cada recurso, ocupação, quadros, alvo e o último
gargalo: `cpu`, `gpu`, `pacing`, `thermal` ou `none`), para a barra de status e a tela futura, e
ao parar a linha `power OK controller: ...` com o tempo por degrau de cada recurso e a contagem
por gargalo. O modo `controller=load` (D12) continua aceito.

*Alternativas descartadas:* subir tudo junto (gasta bateria e esquenta, que é o contrário do
pedido); trocar o governor da GPU para `userspace` (no GA36 ele não está no kernel e o piso já
basta); controlador pelo FPS do `GET_STATUS` do RetroArch (preso ao RetroArch, D2 e memória do
projeto; os page flips valem para qualquer jogo).

### D18. Ajuste manual por recurso, por sistema e por jogo (pedido do usuário, 2026-11-18)

Para a interface futura (P-85, P-91) poder escolher o nível de cada recurso:
- **Por recurso:** chaves de perfil `min`/`max` (CPU, kHz) e `gpu_min`/`gpu_max` (GPU, Hz).
  Faixa com um degrau só = recurso travado à mão; faixa maior com `controller=auto` = o
  controlador escolhe dentro dela. Assim "subir só a GPU" é `gpu_min` alto com a CPU livre, e
  "deixar a CPU baixa" é `max` baixo, sem conceito novo no arquivo.
- **Por jogo:** linha `game <chave> <perfil>` no `power.conf` (só no cartão; a imagem não traz
  jogo nenhum). A chave é o FNV-1a de 64 bits, em 16 dígitos hexadecimais, do caminho da ROM
  relativo a `ROMS/roms/` (`lume_core::power::game_key`), então nem o `power.conf`, nem o
  `power.state`, nem o `events.log` levam nome de jogo. A mensagem do FIFO passa a
  `game <sistema> <core> <chave>` (a chave é opcional: um escritor antigo continua valendo).
- **Precedência:** jogo, depois core, depois classe, depois `game`. O piso dos jogos do GA36 (D3)
  vale também para um perfil escolhido por jogo.
- **Editor:** o `powerconf` do `lume-core` ganha `Setting::Game` e as chaves `gpu_min` e
  `controller=auto`; o `power.state` publica as linhas `game` com a origem.

### D19. "Memória da GPU" nestes consoles

O A33 (Mali-400 MP2) e o RK3326 (Mali-G31) não têm memória de vídeo própria: a GPU usa a mesma
DRAM da CPU (o `lima` e o `panfrost` alocam da memória comum; a tela usa a CMA). Não há quantidade
de memória de GPU para aumentar. O que existe:
- **Banda da memória** (clock da DRAM): fixa nos dois consoles no mainline. O A33 tem driver de
  devfreq do MBUS no kernel (`sun8i-a33-mbus`, `CONFIG_ARM_SUN8I_A33_MBUS_DEVFREQ`), mas o
  `sun8i-a33.dtsi` não declara o nó; ligá-lo é design novo e arriscado (P-23, etapa 4).
- **Falta de memória**: o controlador registra o menor `MemAvailable` e `CmaFree` da sessão e
  marca o gargalo `memory` quando o `MemAvailable` fica abaixo de 32 MiB; não há o que subir,
  então é só diagnóstico (a falta de CMA da `lume-hud-actions` foi um vazamento, já corrigido).

## Risks / Trade-offs

- [Controlador por gargalo sobe a GPU num jogo que perde quadros por outro motivo (áudio, disco)]
  → A regra 2 sobe um degrau por segundo e a regra 3 só desce sem queda de quadros, então um
  jogo que perde quadros por outro motivo acaba com o recurso mais ocupado no máximo: é o
  comportamento do `performance` de hoje (custo de bateria, nunca de quadro). O `powerctl.state` e
  a linha do `events.log` mostram o gargalo `pacing`, e o caso vira exceção por core ou por jogo.
- [Ler o `fdinfo` a cada 250 ms custa CPU] → Só os fds do DRM achados a cada 2 s, poucos
  arquivos pequenos por amostra; medido na J1 junto do custo do `logd` (meta: abaixo de 1% de um
  núcleo).

- [Desligar núcleos com o jogo esperando mais threads] → Os perfis só desligam núcleos onde a
  medição mostrar que não há `slow` a mais; `cpu0` nunca sai.
- [Perfil mais baixo perde quadros num jogo fora dos de teste] → A regra compara com o padrão
  em jogos de cada classe; o `events.log` registra o perfil junto dos `game FAIL slow`, então um
  caso novo aparece nos logs e vira exceção por core.
- [O serviço cai e o console fica no perfil do último cenário] → OpenRC reinicia o serviço, que
  volta ao `menu` (ou ao padrão do kernel se o arquivo for recusado); o pior caso é um perfil
  de jogo no menu, que só gasta mais.
- [Desligamento por bateria crítica com um leitor de `capacity` instável] → Duas leituras
  seguidas e só descarregando; o limite é configurável pelo PC.
- [Escurecer a tela consome o primeiro botão e o usuário estranha] → É o comportamento de
  celulares e consoles; o aviso não é preciso.
- [Medições longas ocupam os aparelhos] → Janelas próprias, depois das provas das changes
  `build-speed` e `card-health`, na fila única do cartão.
- [O `logd` em C muda o formato] → O formato é congelado pelos testes de `tests/logs/` antes da
  troca.
- [O commit novo do `snes9x2005` muda o comportamento de um jogo de teste ou o formato dos save
  states] → A 4.2 abre um jogo de SNES nos dois consoles antes da medição (J1), e um save state
  antigo é aberto para conferir; se não abrir, o resultado fica anotado aqui e o usuário decide
  entre manter o commit novo ou voltar ao de 2022.
- [O controlador cai com o governor em `userspace` e o clock baixo] → O `lume-power` vigia o
  filho e, se ele sair antes do `end`, reaplica o perfil do jogo sem o controlador e registra
  o evento.
- [O `nice -5` de um jogo travado rouba a CPU do daemon de entrada] → O `lume-input` roda com
  `nice -10`; prova de Fn+Start com um jogo travado na J3 e na J4.

## Migration Plan

Sem perfil (arquivo ausente ou recusado), tudo continua como hoje. Os arquivos de perfil chegam
com os valores medidos só no fim; até lá a imagem leva o serviço com perfis iguais ao padrão
do kernel, e o modo manual serve à medição. Voltar à versão anterior pelo `push` volta ao
`schedutil` puro.

## Open Questions

- Os valores de cada perfil e o `N` de núcleos por classe: saem da medição (D5) e não mudam o
  desenho.
