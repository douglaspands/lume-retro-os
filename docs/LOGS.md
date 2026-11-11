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
  frontend/boot-<n>.log   log do RetroArch (também o log mostrado quando ele falha)
  .boot                   contador de boots (não apague só ele)
  .clean                  marcador de desligamento limpo
```

`<n>` é o número do boot e é o mesmo em todas as pastas: `boot/boot-12.log`,
`hw/boot-12.txt`, `metrics/boot-12.csv`, `trace/boot-12.log` e `frontend/boot-12.log`
são do mesmo boot.

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
| `game` | aberto (core e conteúdo); fechado (core, conteúdo e duração em segundos) |
| `audio` | o dispositivo de som parou de consumir e o jogo segue sem som (`FAIL`, linha `[ALSA] Playback stalled` do RetroArch, patch 0003); o som voltou (`OK`) |
| `roms` | partição de jogos criada ou verificada (`fsck`) |
| `kernel` | mensagens de erro do kernel no boot (quantidade e as 3 primeiras) |
| `temperature` | zona acima do limite passivo (`FAIL`); de volta 5 °C abaixo (`OK`) |
| `battery` | abaixo de 10% (`FAIL`) |
| `shutdown` | limpo; anterior limpo ou abrupto (detectado no boot seguinte) |
| `logs` | logs só na RAM, sem a partição de jogos |

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
| `frontend` | `menu`, `game`, `paused`, `no_answer` (RetroArch sem resposta), `other` (outro frontend) ou `stopped` |
| `core` | core do jogo em execução (vazio fora de jogo) |
| `content` | nome do jogo em execução (vazio fora de jogo) |

Na VM não há cpufreq, zonas térmicas nem bateria, e essas colunas não aparecem.

## `trace/boot-<n>.log`

Serve para descobrir **onde** o RetroArch parou quando o aparelho congela. Cada linha
começa com a hora (`HH:MM:SS`). Uma linha por amostra (a cada `interval` segundos):

```
10:46:08 fe=no_answer pid=312 st=S utime=412 stime=96 threads=5 dri_fds=1 gpu_mhz=384 vblank=2842 tasks= 312:S:do_poll 318:S:futex_wait_queue
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
| `tasks` | por thread: `tid:estado:wchan`. O `wchan` é a função do kernel em que a thread está dormindo |

Além disso:

- `k <mensagem>`: mensagens novas do kernel surgidas depois do início do `logd` (erros do
  driver de vídeo, de áudio ou do cartão aparecem aqui, com a hora do kernel).
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

## `hw/boot-<n>.txt`

Mapa completo do hardware, gerado uma vez por boot pelo `hwinfo`, depois que o frontend
sobe (por isso inclui o tempo até ele). Só lê `/proc`, `/sys` e o debugfs. Seções:

- `== system`: versão, placa, modelo e `compatible` do device tree, número de série, SoC,
  kernel e linha de comando.
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
