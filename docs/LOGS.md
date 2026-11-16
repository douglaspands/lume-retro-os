# Logs de diagnóstico

Todos os logs do Lume Retro OS ficam numa única pasta da partição de jogos:
**`ROMS/logs/`** (no console, `/storage/logs/`). Eles registram o comportamento real do
sistema e do hardware, como clock, temperatura, memória, bateria e falhas. São a base
para decisões futuras, como otimizações, governor, zram e calibração da bateria.

**Idioma:** os logs são sempre em inglês: conteúdo, nomes de arquivos e pastas,
categorias, colunas e mensagens do kernel, do initramfs e dos serviços. Só as mensagens
para o usuário seguem o idioma escolhido no menu do RetroArch (`user_language`); ver
[FRONTEND.md](FRONTEND.md).

**Para limpar**, apague a pasta `ROMS/logs/` inteira pelo PC. É seguro: jogos, saves,
estados e configurações não são tocados, a pasta é recriada no próximo boot e a
numeração dos boots recomeça do 1.

## Estrutura

```
ROMS/logs/
  events.log              eventos de todos os boots (gira: events.1.log … events.3.log)
  boot/boot-<n>.log       kernel, serviços e resumo de hardware de cada boot
  hw/boot-<n>.txt         retrato do hardware de cada boot
  metrics/boot-<n>.csv    uma amostra a cada 5 s durante o uso
  trace/boot-<n>.log      rastreio do RetroArch: estado do processo, kernel e congelamentos
  frontend/boot-<n>.log   log do frontend: lume-run, lume-ui e o RetroArch aberto por eles
                          (também o log mostrado quando ele falha)
  .boot                   contador de boots (não apague só ele)
  .clean                  marcador de desligamento limpo
```

`<n>` é o número do boot e é o mesmo em todas as pastas: `boot/boot-12.log`,
`hw/boot-12.txt`, `metrics/boot-12.csv`, `trace/boot-12.log` e `frontend/boot-12.log`
são do mesmo boot.

**Cartão único (GA36 e R36S):** o mesmo cartão inicia nos dois consoles, e os dois
gravam na mesma `ROMS/logs/`. A numeração dos boots é uma só: se o cartão iniciou no
GA36 (boot 12), depois no R36S (13) e de novo no GA36 (14), os três logs ficam lado a
lado, sem um sobrescrever o outro. Para saber de qual console é cada boot:

- `boot/boot-<n>.log`: a segunda linha do cabeçalho, `== console: ga36` ou
  `== console: r36s`;
- `hw/boot-<n>.txt`: o campo `board`;
- `events.log`: o evento `boot OK started: <console> kernel <versão> ...`, gravado no
  início de cada boot. Para ver só os boots de um console:
  `grep "boot OK started: r36s" events.log`.

A arquitetura também diferencia: o campo `kernel` do `hw/boot-<n>.txt` traz a versão e
a máquina (`armv7l` no GA36, `aarch64` no R36S).

No `frontend/boot-<n>.log`, cada início do `lume-ui` grava o driver de vídeo e o renderer
do SDL, por exemplo `lume-ui: video KMSDRM, renderer opengles2, 640x480`. Um renderer
`software` indica que a GPU não foi usada.

**Sem a partição de jogos** (por exemplo, quando a partição 2 não é exFAT), os logs
ficam só na RAM, e o log de boot vai para `BOOT/logs/boot-<n>.log` (os 10 mais recentes),
porque é justamente o caso que precisa de diagnóstico. O log do frontend que falhou vai
para `BOOT/logs/frontend-error.log`.

## Como é gravado

- Os coletores escrevem na RAM (`/run/r36os/logs/`). O serviço `r36os-logd` grava no
  cartão a cada 60 s e no desligamento, em lote, para poupar o cartão e a CPU. Um corte
  de energia perde no máximo o último intervalo.
- O desligamento limpo grava o marcador `.clean`. Se o boot seguinte não o encontra,
  registra em `events.log` que o desligamento anterior foi abrupto.
- No console serial de debug: `/usr/libexec/r36os/logd flush` grava na hora.

## Configuração: `ROMS/system/etc/logs.conf`

Criado com os padrões no primeiro boot (comentários em inglês) e editável no PC:

| Chave | Padrão | Significado |
|---|---|---|
| `enable` | `1` | `0` desliga o retrato do hardware, as métricas e o rastreio. O log de boot, os eventos e o log do frontend continuam |
| `interval` | `5` | segundos entre amostras de métricas (mínimo 1) |
| `flush` | `60` | segundos entre gravações no cartão (mínimo 5) |
| `keep_boots` | `30` | quantos boots manter em `boot/`, `hw/`, `metrics/`, `trace/` e `frontend/` |
| `max_mb` | `64` | teto de `ROMS/logs/` em MiB (mínimo 8) |

Valores fora da faixa são ignorados e o padrão vale.

## Rotação

- `boot/`, `hw/`, `metrics/`, `trace/` e `frontend/`: os `keep_boots` boots mais recentes.
- `metrics/boot-<n>.csv` para de crescer em 4 MiB (cerca de 30 h a 5 s).
- `trace/boot-<n>.log` para de crescer em 2 MiB (cerca de 12 h de uso). O buffer na RAM
  entre duas gravações tem o mesmo teto, inclusive sem a ROMS.
- `frontend/boot-<n>.log`: os últimos 4 MiB do log do RetroArch. Na RAM, onde o RetroArch
  escreve, o log também é aparado: passando de 8 MiB, ficam só os últimos 1 MiB.
- `events.log` vira `events.1.log` em 1 MiB, e são mantidos 3 antigos.
- Acima de `max_mb`, apaga primeiro as métricas mais antigas, depois o rastreio, os logs do
  frontend, os retratos, os logs de boot e os eventos antigos. Os arquivos do boot atual
  nunca são apagados por esse teto.
- No pior caso, os arquivos do boot atual somam cerca de 10 MiB (métricas 4 + rastreio 2 +
  frontend 4), bem abaixo do teto padrão de 64 MiB.

## `events.log`

Uma linha por evento:

```
<time> <boot> <category> <OK|FAIL> <detail>
2026-11-09T21:14:03 12 game OK opened: core=FCEUmm content=Super Game
```

| Categoria | Quando |
|---|---|
| `boot` | boot iniciado (placa, kernel, `boot_id`); concluído com o tempo até o frontend; erros do initramfs |
| `service` | serviço do OpenRC que não iniciou (`FAIL`) |
| `frontend` | iniciado; encerrado pelo usuário ou pelo serviço; terminou com erro; parado após 3 falhas; vivo mas sem responder por 15 s (`FAIL`) e de volta a responder (`OK`); travado, sem CPU e sem vblank por 10 s (`FAIL`) e recuperado pelo `logd` (`OK`) |
| `game` | com o lume-launcher (frontend padrão), gravadas pelo `lume-run`, sem nome nem caminho do jogo: início (`OK <sistema> <runner> <core> start`, ou `menu` para o menu do RetroArch sem jogo) e fim (`<sistema> <runner> <core> exit=<código ou sigN> end=<normal, quit-combo, killed ou session> secs=<duração>`; `OK` com saída 0 ou fim por Fn+Start, `FAIL` nos outros casos; `-` no lugar do core de um runner nativo). Com o RetroArch como frontend: aberto (core e conteúdo) e fechado (core, conteúdo e duração), pelo `logd`. Nos dois: lento, duas amostras seguidas abaixo de 95% do FPS nominal do core (`FAIL slow`); de volta à velocidade cheia (`OK full speed again`) |
| `index` | fim de um scan das listas de jogos do launcher (`lume-index`): `scan systems=<n> games=<n> added=<n> failed=<n> ms=<n>` e a contagem por sistema com jogos (`nes=40 snes=12`), nunca um nome |
| `audio` | o dispositivo de som parou de consumir e o jogo segue sem som (`FAIL`, linha `[ALSA] Playback stalled` do RetroArch, patch 0003); o som voltou (`OK`) |
| `roms` | partição de jogos criada ou verificada (`fsck`) |
| `kernel` | mensagens de erro do kernel no boot (quantidade e as 3 primeiras) |
| `temperature` | zona acima do limite passivo (`FAIL`); de volta 5 °C abaixo (`OK`) |
| `battery` | abaixo de 10% (`FAIL`) |
| `shutdown` | limpo; anterior limpo ou abrupto (detectado no boot seguinte) |
| `logs` | logs só na RAM, sem a partição de jogos |
| `usb` | a porta OTG mudou de estado (`OK otg: <estado>`, com os campos da linha `usb:` do `trace/`); um PC configurou o gadget "Lume" (`OK device: connected`, `udc` em `configured`) e foi desligado (`OK device: disconnected`); na VM, sem porta OTG, não há evento |

## `metrics/boot-<n>.csv`

CSV com cabeçalho, uma linha a cada `interval` segundos. As colunas que dependem do
hardware são descobertas a cada boot, e o cabeçalho de cada arquivo diz quais existem.

| Coluna | Conteúdo |
|---|---|
| `time` | data e hora local (`AAAA-MM-DDTHH:MM:SS`) |
| `uptime_s` | segundos desde o boot |
| `temp_<zona>_c` | uma por zona térmica: temperatura em °C (ex.: `temp_cpu_thermal_c`) |
| `freq_<política>_mhz` | uma por política de cpufreq: frequência atual em MHz (ex.: `freq_policy0_mhz`) |
| `cpu<N>_pct` | uma por núcleo: ocupação em % desde a amostra anterior |
| `mem_avail_mb` | memória disponível (MemAvailable) em MiB |
| `swap_used_mb` | swap em uso em MiB |
| `bat_pct` | carga da bateria em % (vazio sem bateria) |
| `bat_mv` | tensão da bateria em mV |
| `bat_ma` | corrente da bateria em mA |
| `bat_status` | `Charging`, `Discharging`, `Full`… |
| `frontend` | `launcher` (a interface do lume-launcher na tela), `menu`, `game`, `paused`, `no_answer` (RetroArch sem resposta), `other` (outro frontend) ou `stopped` |
| `core` | no RetroArch, o sistema que o core informa no `GET_STATUS` (`nes` com o fceumm, não o nome do core; o core exato está no evento `game` do `events.log`); vazio fora de jogo; num runner nativo do launcher, o nome do runner (`love`, `sh`) |
| `content` | nome do jogo em execução (vazio fora de jogo); sempre vazio com o lume-launcher |
| `fps` | quadros por segundo do jogo desde a amostra anterior: diferença do contador de quadros do `GET_STATUS` (patch 0004 do RetroArch) dividida pelo tempo. Vazio no menu, na pausa, na primeira amostra de um jogo e quando o contador recomeça |
| `fps_nominal` | FPS nominal do core (linha `Geometry: ... FPS:` do log do RetroArch), para comparar com `fps`; vazio fora de jogo |
| `lume_ui_rss_kb` | memória residente da interface do launcher (`lume-ui`) em KiB; vazio quando ela não está rodando (durante um jogo) |
| `lume_ui_cpu_pct` | CPU do `lume-ui` em % de um núcleo desde a amostra anterior; vazio na primeira amostra |
| `lume_run_rss_kb` | memória residente do supervisor (`lume-run`) em KiB |
| `lume_run_cpu_pct` | CPU do `lume-run` em % de um núcleo |
| `input_rss_kb` | memória residente do daemon de entrada (`r36os-input`) em KiB |
| `input_cpu_pct` | CPU do `r36os-input` em % de um núcleo |

Na VM não há cpufreq, zonas térmicas nem bateria, e essas colunas não aparecem.

## `trace/boot-<n>.log`

Serve para descobrir **onde** o RetroArch parou quando o aparelho congela. Cada linha
começa com a hora (`HH:MM:SS`). Uma linha por amostra (a cada `interval` segundos):

```
10:46:08 fe=no_answer pid=312 st=S utime=412 stime=96 threads=5 dri_fds=1 gpu_mhz=384 vblank=2842 pcm=RUNNING/48000/46.12/2211840 tasks= 312:S:do_poll 318:S:futex_wait_queue
```

| Campo | Conteúdo |
|---|---|
| `fe` | o mesmo estado da coluna `frontend` das métricas |
| `pid` | processo do RetroArch (`-` se não há) |
| `st` | estado do processo: `R` rodando, `S` dormindo, `D` preso no kernel, `Z` zumbi |
| `utime`, `stime` | tempo de CPU do processo em ticks (100 por segundo), em modo usuário e kernel |
| `threads` | número de threads |
| `dri_fds` | descritores abertos em `/dev/dri/` (mais de um pode indicar o dispositivo herdado do processo anterior) |
| `gpu_mhz` | frequência da GPU (devfreq) em MHz; vazio sem devfreq. Mostra se o clock da GPU mudou quando o jogo abriu |
| `vblank` | soma das interrupções do controlador de vídeo (`lcd-controller`, o vblank); vazio sem ele (VM). Com o display vivo, sobe ~55 por segundo; **parada, a tela congelou** |
| `pcm` | primeira reprodução de áudio aberta, como `estado/taxa/uptime/hw_ptr` (`-` sem nenhuma). O `uptime` é o de `/proc/uptime`, lido logo antes do `hw_ptr`, que conta os quadros que o hardware já consumiu; entre duas linhas com o mesmo stream em `RUNNING`, `Δhw_ptr / Δuptime` é a taxa real de saída, que deve bater com a `taxa` |
| `tasks` | por thread: `tid:estado:wchan`. O `wchan` é a função do kernel em que a thread está dormindo |

Além disso:

- `k <mensagem>`: mensagens novas do kernel surgidas depois do início do `logd` (erros do
  driver de vídeo, de áudio ou do cartão aparecem aqui, com a hora do kernel).
- `usb: <estado>`: a porta OTG vista pelo kernel, uma linha por amostra (change
  `usb-device-access`, D1). Serve para saber como cada console distingue um PC, um
  carregador e um adaptador OTG. Cada campo só aparece quando o console o tem; sem nenhum
  (a VM), a linha é `usb: none`:

  ```
  10:46:08 usb: extcon=1c19400.phy:USB=1,USB-HOST=0 musb=b_peripheral udc=musb-hdrc.1.auto:configured vbus=axp20x-usb:1 host_devs=0
  ```

  | Campo | Conteúdo |
  |---|---|
  | `extcon` | o PHY da porta (`/sys/class/extcon/*`, só os que têm cabos USB): `USB=1` é VBUS visto pelo PHY, `USB-HOST=1` é o pino ID em nível baixo (adaptador OTG) |
  | `musb` | modo do controlador MUSB (GA36): `b_idle`, `b_peripheral`, `a_host`… |
  | `role` | papel de um `usb-role-switch` (`none`, `host`, `device`) |
  | `udc` | lado gadget do controlador (`/sys/class/udc/*/state`), com `_` no lugar de espaço: `not_attached`, `configured`… |
  | `vbus` | `online` de cada fonte de energia do tipo USB (a entrada de carga do PMIC) |
  | `host_devs` | dispositivos USB atrás das portas host (sem contar os hubs raiz nem as interfaces) |

  Quando o estado muda, o `events.log` ganha `usb OK otg: <estado>`.
- **Instantâneo** (`=== snapshot of retroarch pid ...` até `=== end of snapshot`): gravado
  quando o RetroArch fica 3 amostras seguidas (15 s) vivo e sem responder ao `GET_STATUS`,
  e de novo a cada 6 amostras, no máximo 6 por boot. Traz o `status` do processo, cada
  thread com a pilha no kernel (`stack`, quando o kernel expõe), os descritores de
  dispositivos abertos (`fd`), a carga (`loadavg`) e as interrupções (`irq`, a tabela de
  `/proc/interrupts`). Comparando duas tabelas, as contagens que param de subir (vídeo,
  GPU, áudio) mostram o que travou.
- **Travamento (hung) e recuperação.** O `logd` declara o frontend travado quando o mesmo
  processo do RetroArch passa 2 amostras seguidas (10 s) **sem usar CPU** (no máximo 2
  ticks) e com o `vblank` parado (ou sem `vblank`, na VM). Quem só está carregando um jogo
  grande usa CPU e nunca é declarado travado, e um processo bloqueado com o `vblank`
  subindo também não. Ao declarar, o `events.log` ganha `frontend FAIL retroarch pid <pid>
  hung: blocked with no CPU and no display vblank for 10s`, o instantâneo é gravado e
  descarregado no cartão, e só então o processo é morto (`kill -9`) para a sessão reiniciar o
  frontend no menu (`frontend OK recovery <n> of 3: killed the hung retroarch`). São no
  máximo 3 recuperações por boot (`RECOVER_MAX`; com 0 só registra). A sessão conta a morte
  como uma falha do frontend (`terminated with error (code 137)`), e 3 falhas em 60 s
  param o reinício.
- **Reabilitar o vblank antes de matar (só no GA36).** No primeiro sinal de bloqueio (5 a 8 s),
  se o console tem controlador de vídeo, o `logd` grava o instantâneo e lê o registrador
  `TCON_GINT0` (base do `lcd-controller` + 4) com o `r36os-devmem`. Um console saudável tem
  `0xc8000200` ali. Nos congelamentos vistos, o valor era `0x00000a00`: as três habilitações
  de interrupção (bits 31, 30 e 27) zeradas, com a flag `TRI_FINISH` pendente, então o page
  flip que o RetroArch espera nunca é entregue. Se as habilitações estiverem zeradas, o `logd`
  liga os três bits (`0xc8000000`) e espera até 3 s o contador `vblank` voltar a subir. Se
  subir, o RetroArch continua **sem ser morto** (`frontend OK recovery: re-enabled the masked
  display vblank interrupt`). Se as habilitações já estiverem ligadas, ou a escrita não
  resolver, segue o caminho de antes: travamento declarado em 10 s e processo morto. No
  máximo 5 reabilitações por boot (`KICK_MAX`). No `trace/` ficam as linhas `tcon GINT0 ...`
  com o valor lido e o escrito.
- O instantâneo também grava o estado do vídeo: `sysfs` do conector (`status`, `enabled`,
  `dpms`) e da luz de fundo, `debugfs` do DRM (`state`, o estado atômico, e `clients`, quem
  é o master), os registradores do controlador de vídeo, do DSI e do DE (frontend e backend)
  (`regs`, do regmap) e os clocks de TCON, DSI, PLLs de vídeo e GPU (`clk`). O instantâneo é
  montado num arquivo na RAM e gravado de uma vez (antes levava 11 s na A33).
- Ao declarar o congelamento, o `events.log` ganha `frontend FAIL retroarch pid <pid>
  alive but no answer for 15s`, e a descarga no cartão é imediata. Enquanto o estado muda
  ou não há resposta, a descarga acontece a cada amostra, porque um aparelho congelado
  costuma ser desligado na marra e o intervalo normal de `flush` perderia a evidência.

Como ler: `st=S` com o mesmo `wchan` e `utime` parado entre amostras é um processo
bloqueado (esperando o kernel). `st=R` com `utime` subindo é um processo em laço, ocupado.
Junto com o `frontend/boot-<n>.log` (que mostra até onde o RetroArch chegou), isso separa
um travamento de vídeo/GPU de um de áudio, de memória ou do disco.

## Entrada (`r36os-input`) no `boot/boot-<n>.log`

O daemon de entrada grava no log do kernel (e por isso no `boot/boot-<n>.log` e nas linhas
`k` do `trace/`) uma linha ao subir e uma por problema:

```
r36os-input: "GA36-MB Gamepad" from 2 of 2 source(s), socket /run/r36os/input.sock, volume DAC
r36os-input: no input device named "1c21800.lradc" (optional)
r36os-input: source device "gpio-keys" gone
```

`from 1 of 2` com uma origem `(optional)` faltando quer dizer que aquele dispositivo (os
botões de volume, ou os analógicos do R36S) não foi achado pelo nome do perfil: o controle
funciona sem ele. Uma origem obrigatória faltando faz o serviço tentar de novo
(`supervise-daemon`, até 5 vezes).

## Escolha do device tree no `boot/boot-<n>.log`

O `lume-bootsel` do initramfs escolhe o DTB entre os de `BOOT/dtbs/<soc>/` (ver
`docs/BRINGUP-GA36.md` e `docs/BRINGUP-R36S.md`) e registra cada passo no log do kernel,
com o prefixo `lume-bootsel:`:

| Linha | Significado |
| :--- | :--- |
| `soc <soc> (<compatible>), running device tree <id>` | SoC e DTB com que o bootloader iniciou o kernel |
| `candidate <id> (<arquivo>) priority <p>, <n> rule(s)\|no rules[, default]` | DTB da pasta aceito como candidato |
| `ignored <arquivo>: <motivo>` | DTB recusado: inválido, de outro SoC, sem o nó `lume-select` ou com `lume,id` repetido |
| `vendor device tree <id> loaded on demand` | um DTB convertido de `dtbs/<soc>/vendor/` (D17) foi nomeado pelo `force`, pela lista, pela escolha salva, pelo aprendido ou pelo estado e lido agora; segue a linha `candidate <id> (vendor/<id>.dtb) ...`. Num boot normal a pasta não é lida |
| `probe adc\|gpio\|i2c <endereço> ...: <leitura> (rule ...) match\|no match` | leitura feita por uma regra |
| `signature: panel id <hex> (<dispositivo DSI>)` | assinatura do aparelho: o ID que o painel respondeu ao driver (D15) |
| `no signature: the panel did not answer its driver` / `no signature: no panel driver shows panel_id` | painel mudo com o DTB em uso (dispara a busca) / kernel sem a leitura do ID (nada é testado sozinho) |
| `panel id of <dispositivo>: unsupported` | o host DSI não faz a leitura do ID: nada se conclui sobre o painel, e a busca não roda |
| `panel id <hex> (<dispositivo>): the panel answered, but the ID is blank: no signature` | o painel respondeu (o DTB serve), mas o ID é `000000` ou `ffffff` (nunca gravado, como no JD9366 do GA36): nada é aprendido por ele |
| `panel <dispositivo>: no driver bound, the panel did not answer its probe` | o driver do painel recusou o probe (o `jd9366` sem resposta), depois de esperar 2 s por um probe adiado: conta como painel mudo |
| `probe panel id <regra>: <lido> match\|no match` | regra `lume,panel-id` |
| `learned before: <id> for panel:<hex>` / `learned: <id> for panel:<hex>` / `forgotten: ...` | o que já foi aprendido para essa assinatura / aprendizado novo / um DTB descartado sai do aprendido |
| `search: <id> does not work (...); discarded on this device` / `search: <id> works, the panel answered` / `search: no device tree left; ...` | busca sozinha (D15): DTB descartado, achado, ou candidatos esgotados |
| `probe ...: failed (<motivo>)` | leitura que não pôde ser feita; a regra conta como não batida |
| `rules of <id>: match\|no match`, `no rule matched` | resultado das regras |
| `device: SoC serial number <serial>, choice in dtb-<soc>-<serial>.conf` | o aparelho, pelo número de série do SoC |
| `no SoC serial number: the choice in dtb-<soc>.conf applies to every <soc> device` | sem número de série: a escolha vale para todo aparelho do SoC |
| `force: BOOT/dtbs/force selects <id>` / `force ignored: '<nome>' ...` | escolha pelo PC aceita ou recusada (nome inválido) |
| `force ignored: <id> was discarded on this device (bad); ...` | `force` de um DTB descartado neste aparelho |
| `fallback: <id> was not confirmed in the previous boot; discarded` | volta ao último DTB confirmado |
| `list shown (<n> candidate(s)[, <m> converted])`, `list: <id> chosen and saved`, `list: automatic chosen, ...` | lista aberta pela tecla de seleção; `converted`: quantos DTBs de `vendor/` ela mostrou |
| `selected <id> (reason: default\|rule\|manual\|forced\|fallback\|reverted\|learned\|auto\|search)` | **o DTB escolhido e o motivo** (`learned`: aprendido antes para a assinatura; `auto`: o painel respondeu ao DTB em uso, que é aprendido; `search`: o painel não respondeu e o próximo candidato é testado) |
| `keeping the running device tree, no kexec` | boot segue sem troca |
| `switching to <id> by kexec (...)` | troca: o kernel reinicia com o DTB escolhido |
| `switching to <id> by the boot image (...) and a reboot` / `boot image with <id> written at sector <n> of <disco> (... read back)` | troca no GA36 (D16): a imagem de boot do setor 172032 é regravada com o DTB escolhido, conferida, e o console reinicia |
| `device tree from the boot image: <id> (reason: <motivo>)` | no GA36, o início depois desse reinício (o DTB em uso é o `pending`): segue como o segundo início do kexec |
| `rebooting into the boot image with <id>` e `before reboot: <linha>` | o início que regrava a imagem guarda as suas linhas em `ROMS/system/etc/dtb-<soc>-before-reboot.log` (ele reinicia antes de qualquer log chegar ao cartão); o início seguinte as repete com esse prefixo e apaga o arquivo |
| `kexec: <linha>` | o que o `kexec -l` imprimiu (antes só ia para a tela) |
| `kexec -l failed (status <n>); details follow`, `iomem: <linha>` | a carga falhou: segue a saída do `kexec -d` e a RAM do `/proc/iomem` |
| `watchdog armed: 60 s ...` / `watchdog stopped` / `no /dev/watchdog: ...` | watchdog armado antes da troca para um DTB novo e parado no início seguinte |
| `before kexec: <linha>` e `device tree from kexec: <id> (reason: <motivo>)` | no segundo início, as linhas do primeiro (que se perderiam com o kexec) e a origem do DTB; depois de uma volta, as do primeiro vêm com o prefixo duas vezes |
| `question shown: keep <id>? (15 s)` | pergunta na tela do primeiro boot com um DTB novo |
| `confirmed on screen: <id> kept` | o usuário apertou A: o DTB fica confirmado neste aparelho |
| `not confirmed within 15 s: <id> discarded on this device, going back to <id>` | sem resposta: o DTB vai para `bad` e o kernel volta (`reverted`) |
| `no question on the screen (...): <id> stays pending until the frontend starts` | sem tecla de confirmar: o `r36os-logd` confirma quando o frontend sobe |
| `back from a device tree that was not confirmed: no question, no switch` | terceiro início, depois da volta |
| `kexec -e failed: <id> is no longer pending` | o `kexec -e` falhou e o boot segue com o DTB em uso |
| `no device tree` | sem device tree (a VM): nada a escolher |

O estado fica em `ROMS/system/etc/dtb-<soc>-<serial>.conf` (`manual=`, `good=`,
`pending=`, `bad=`), um arquivo por aparelho, identificado pelo número de série do SoC
(`/sys/devices/soc0/serial_number`); sem ele, `dtb-<soc>.conf`, um por SoC. Um DTB que não
é o padrão e ainda não foi confirmado no aparelho fica `pending` e é confirmado na tela; se
a pergunta não pôde aparecer, o `r36os-logd` o confirma quando o frontend sobe (`good=` e
sem `pending=`). Um DTB que continua `pending` no boot seguinte não foi confirmado e é
descartado (`fallback`). No `events.log`, a escolha vira `boot OK device tree selected …`,
a confirmação na tela `boot OK device tree confirmed on screen: …`, a do frontend
`boot OK device tree <id> confirmed: the frontend started (no question on the screen)`, e o
fallback, a falta de resposta e os erros do `lume-bootsel` viram `boot FAIL device tree …`.
O `hw/boot-<n>.txt` traz o DTB em uso e o arquivo de estado no campo `dt in use`.

O aprendido (D15) fica em `ROMS/system/etc/dtb-<soc>-learned.conf`, uma linha
`panel:<hex>=<id>` por assinatura, comum a todos os aparelhos do SoC que usam o cartão: vale
para qualquer aparelho cujo painel responda o mesmo ID.

## Módulos do kernel no `boot/boot-<n>.log`

Nos consoles, os módulos do kernel ficam fora do `SYSTEM`, num squashfs por console
(`BOOT/ga36/modules`, `BOOT/r36s/modules`). O initramfs o monta em `/lib/modules` antes do
`switch_root`, só se a pasta de versão da imagem for igual à do kernel em execução
(`uname -r`), e registra uma destas linhas com o prefixo `lume:`:

| Linha | Significado |
| :--- | :--- |
| `modules: <file> (<release>)` | imagem montada em `/lib/modules`, com a versão do kernel |
| `ERROR: BOOT has no <file>; starting without kernel modules` | o arquivo não está na `BOOT`, nem o `<file>.old` |
| `ERROR: BOOT has no <file>; using <file>.old from the previous build` | um `push` foi cortado entre os dois `mv` da troca (change `push-boot-swap`): monta o `.old`, que ainda passa pela conferência de versão abaixo. A mesma linha vale para o `SYSTEM` (`<console>/SYSTEM`); sem ele nem o `.old`, o boot vai para o modo de resgate |
| `ERROR: failed to mount <file>; starting without kernel modules` | o arquivo existe mas não montou (imagem corrompida) |
| `ERROR: <file> holds modules for <found>, the running kernel is <release>; starting without kernel modules` | a versão da imagem é outra (por exemplo, um `push` interrompido entre o kernel e os módulos); `<found>` lista as pastas da imagem, ou `no kernel` se ela está vazia |
| `ERROR: failed to move <file> to /lib/modules; starting without kernel modules` | a imagem montou mas não foi para a raiz nova |

Sem módulos o console sobe e abre o frontend (os drivers de boot estão embutidos no kernel),
mas fica sem `zram`, USB host e dongles. Cada linha `ERROR` vira `boot FAIL …` no
`events.log`. Na VM não há linha: os módulos dela ficam no `SYSTEM`.

## Diagnóstico de hardware no `boot/boot-<n>.log`

Alguns drivers gravam no log do kernel o que leram do próprio hardware. Elas aparecem no
`boot/boot-<n>.log` com a hora do kernel:

- `panel state <before-init|after-init> <reg>: <bytes>`: o painel lido pelo DSI antes e
  depois da sequência de inicialização (ID, energia, formato, autodiagnóstico e os
  registradores do fabricante), mais uma linha `power:` decodificada e
  `panel init sequence: <erro> (sent in command mode|in video mode)`. Hoje no painel do
  R36S.
- `SoC revision: PX30/RK3326` ou `PX30S/RK3326S` e `lane rate … Hz …`: a revisão do SoC do
  R36S e a taxa do link de vídeo do D-PHY.
- `dropped N stale read payload words`: o controlador DSI descartou uma resposta atrasada.

Como ler cada linha: `docs/BRINGUP-R36S.md`, seção 5. Reunir essas leituras num relatório
único de hardware é o P-40.

## `hw/boot-<n>.txt`

Mapa completo do hardware, gerado uma vez por boot pelo `hwinfo`, depois que o frontend
sobe (por isso inclui o tempo até ele). Só lê `/proc`, `/sys` e o debugfs. Seções:

- `== system`: versão, placa, modelo e `compatible` do device tree, o DTB em uso
  (`dt in use: <id> (<motivo>)`, com `after kexec` quando houve troca), número de série,
  SoC, kernel e linha de comando.
- `== component check`: para cada componente esperado (LEDs, USB OTG, USB host, PHY,
  entrada de energia USB/DC, bateria e carregador, PMIC, vídeo, painel, backlight, GPU,
  decodificador de vídeo, áudio, DMA, botões, gamepad, cartão, RTC, watchdog, sensor
  térmico, UART, I2C/RSB, Wi-Fi/Bluetooth), diz se o hardware está no device tree, se o
  kernel criou o dispositivo e **qual driver o ativa** (`NO DRIVER` quando não há),
  ou se o nó existe mas está desativado (`disabled in DT`). Traz também o modo do USB OTG,
  o estado da entrada de energia e os LEDs com driver, brilho e gatilho.
- `== CPU`, `== memory` (com o mapa físico do `/proc/iomem`), `== thermal`,
  `== regulators` (com a árvore de quem usa cada alimentação), `== battery and power`
  (com os domínios de energia).
- `== storage`: partições, montagens e, para o cartão, CID/CSD, fabricante, data e o
  `ios` do controlador (clock, largura do barramento, modo).
- `== USB` (controladores, modo, cada dispositivo com interfaces e drivers, `lsusb` e
  `lsusb -t`), `== PCI` (`lspci -nnk`; não há PCI nos consoles), `== network`.
- `== video`, `== audio` (com o mixer do `amixer` e os componentes ASoC), `== input`,
  `== serial ports`, `== other devices` (RTC, watchdog, PWM, IIO, extcon).
- `== buses and drivers`: **todo dispositivo que o kernel conhece**, por barramento, com
  o driver ligado e o `compatible` do device tree; os *probes* adiados e os módulos.
- `== device tree aliases`, `== GPIO and pins` (GPIOs em uso e pinos reservados por
  driver), `== clocks` (`clk_summary` inteiro), `== DMA` (canais e quem os usa),
  `== interrupts` e o resumo de hardware mostrado antes do frontend.
