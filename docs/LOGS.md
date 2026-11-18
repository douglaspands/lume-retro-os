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

- Os coletores escrevem na RAM (`/run/lume/logs/`). O serviço `lume-logd` grava no
  cartão a cada 60 s e no desligamento, em lote, para poupar o cartão e a CPU. Um corte
  de energia perde no máximo o último intervalo.
- O desligamento limpo grava o marcador `.clean`. Se o boot seguinte não o encontra,
  registra em `events.log` que o desligamento anterior foi abrupto.
- No console serial de debug: `/usr/libexec/lume/logd flush` grava na hora.

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
| `frontend` | iniciado; encerrado pelo usuário (`closed by user: shutting down`), pelo botão de energia segurado (`closed by the power button: shutting down`, device-fixes D11) ou pelo serviço; terminou com erro; parado após 3 falhas; vivo mas sem responder por 15 s (`FAIL`) e de volta a responder (`OK`); travado, sem CPU e sem vblank por 10 s (`FAIL`) e recuperado pelo `logd` (`OK`) |
| `game` | com o lume-launcher (frontend padrão), gravadas pelo `lume-run`, sem nome nem caminho do jogo: início (`OK <sistema> <runner> <core> start`, ou `menu` para o menu do RetroArch sem jogo) e fim (`<sistema> <runner> <core> exit=<código ou sigN> end=<normal, quit-combo, killed ou session> secs=<duração>`; `OK` com saída 0 ou fim por Fn+Start, `FAIL` nos outros casos; `-` no lugar do core de um runner nativo). Com o RetroArch como frontend: aberto (core e conteúdo) e fechado (core, conteúdo e duração), pelo `logd`. Nos dois: lento, duas amostras seguidas abaixo de 95% do FPS nominal do core (`FAIL slow`); de volta à velocidade cheia (`OK full speed again`) |
| `index` | fim de um scan das listas de jogos do launcher (`lume-index`): `scan systems=<n> games=<n> added=<n> failed=<n> ms=<n>` e a contagem por sistema com jogos (`nes=40 snes=12`), nunca um nome |
| `audio` | o dispositivo de som parou de consumir e o jogo segue sem som (`FAIL`, linha `[ALSA] Playback stalled` do RetroArch, patch 0003); o som voltou (`OK`) |
| `roms` | partição de jogos criada (`OK ROMS partition created`) e, em todo boot, o resultado das marcas do exFAT (`VolumeFlags`, deslocamento 106 do setor de boot; device-fixes D1, D3), com o valor delas: volume limpo, sem verificação (`OK clean: check skipped (flags 0x0000)`); volume sujo (corte de energia, travamento) ou com falha de mídia, verificado pelo `fsck.exfat -p` antes de montar (`OK dirty: checked: <resultado> (flags 0x0002 VolumeDirty)`, `0x0004 MediaFailure` ou as duas); pedido "Verificar no próximo boot" (`ROMS/system/card/check-next-boot`) consumido: desmonta, verifica, monta de novo, apaga o pedido e grava o boot em `ROMS/system/card/last-check` (`OK requested: checked: <resultado>`; num boot que já verificou o volume sujo, `OK requested: checked: by the dirty volume check of this boot`). `<resultado>` é `clean`, `errors corrected` ou `uncorrected errors (code <n>)`. Num boot que reinicia o kernel para trocar o DTB (kexec no R36S, reinício na imagem nova no GA36), as linhas do primeiro início voltam no segundo com o sufixo `(before kexec)` ou `(before reboot)`: são elas que dizem como o desligamento anterior deixou o cartão; a linha sem sufixo é do segundo início, que sempre acha o volume limpo. Marcas ilegíveis viram `boot FAIL ERROR: ROMS volume flags unreadable; checking the partition`, e a verificação roda |
| `kernel` | mensagens de erro do kernel no boot (quantidade e as 3 primeiras) |
| `temperature` | zona acima do limite passivo (`FAIL`); de volta 5 °C abaixo (`OK`) |
| `battery` | abaixo de 10% (`FAIL`) |
| `shutdown` | limpo; anterior limpo ou abrupto (detectado no boot seguinte); no desligamento pelo menu, a sessão remonta a `/storage` só leitura (ou a desmonta) depois da última gravação, para o volume ficar limpo (device-fixes D2), e só a falha das duas vira evento (`FAIL storage: remount read-only and unmount failed; ROMS stays marked dirty and is checked at the next boot`); o sucesso fica só no log do kernel (`lume: storage: remounted read-only`, ou `unmounted (remount read-only failed)`) |
| `logs` | logs só na RAM, sem a partição de jogos |
| `push` | `lume push --hot`: fragmento extraído na camada em RAM até o reboot (`OK hot <fragmento> <versão>`); reinício de serviço que falhou (`FAIL hot <fragmento> <versão> restart <serviços>`) |
| `usb` | a porta OTG mudou de estado (`OK otg: <estado>`, com os campos da linha `usb:` do `trace/`); um PC configurou o gadget "Lume" (`OK device: connected`, `udc` em `configured`) e foi desligado (`OK device: disconnected`); a rede `usb0` segue o estado do UDC, não o VBUS: sobe quando o UDC fica `configured` (também ao voltar a `configured`) e cai quando ele sai (`OK network: up on usb0 ...`, `OK network: down on usb0`); VBUS 0 com o UDC ainda `configured` é leitura falsa do PMIC e não derruba a rede (`OK vbus glitch: <fonte>:0 while the UDC is configured, network kept`, e `OK vbus glitch over: ...` quando volta); na VM, sem porta OTG, não há evento |

| `power` | `lume-power` (game-governor, ver "Energia" abaixo): troca de perfil (`OK profile: <cenário> -> <perfil>`, sem nome de jogo); perfis desligados (`OK disabled: enabled 0`); linha ou perfil recusado (`FAIL <origem>: rejected <tipo> <nome>: <motivo>`, origem `image` ou `card`); arquivo da imagem recusado inteiro (`FAIL image: whole file refused, game_min <khz> is not an OPP (floor <khz>)`); `FAIL image profiles file unreadable`; console sem arquivo de perfis ou sem cpufreq, como a VM (`OK no profiles file for <console>: kernel default`, `OK no cpufreq: kernel default`); escrita no sysfs recusada pelo kernel (`FAIL write <caminho> <valor> failed`); modo manual da medição (`OK manual: <perfil>`, `OK auto`; as trocas nele saem como `profile: <cenário> -> <perfil> (manual)`); aviso de bateria fraca, uma vez por descarga (`OK warning: battery <n>%`); desligamento por bateria crítica (`OK shutdown: battery critical`); controlador pela carga ao parar (`OK controller: <khz>=<s>s ... up=<n> down=<n> end=<motivo>`, o tempo em cada degrau; no modo por gargalo, `OK controller: cpu: ... gpu: ... up=<n> down=<n> bottleneck cpu=<n> gpu=<n> pacing=<n> thermal=<n> memory=<n> sync=<n> mem_min=<kB>k end=<motivo>`) ou ao cair/recusar (`FAIL controller: exit <código>: <última linha>`), seguido de `OK profile: game -> <perfil> (without controller)` |
| `sleep` | `lume-sleep` (device-fixes D11, protocolo em [`docs/LAUNCHER.md`](LAUNCHER.md#protocolo-do-sono-para-quem-programa); formato em `lume/lume-core/src/sleep.rs`): suspensão, logo antes de gravar em `/sys/power/state` (`OK suspend <modo>`, modo `freeze` ou `mem`); volta (`OK resume after <s>`, segundos inteiros suspenso pela `/proc/uptime`, que conta o tempo suspenso); o kernel recusou e tudo voltou com a tela acesa (`FAIL suspend <modo>: <motivo>`, por exemplo `write /sys/power/state failed (Device or resource busy)`; sem linha de `resume`); um passo falhou e a sequência seguiu (`FAIL <passo>: <motivo>`, passo `clients`, `audio`, `clock`, `sync`, `backlight`, `wifi`, `governor` ou `usb`; os clientes que não responderam em 2 s saem como `FAIL clients: <a>/<n> answered within 2s`, e o `lume-input` mudo como `FAIL clients: lume-input did not answer within 3s`); desligamento pelo botão segurado (`OK poweroff: power button held`); nome desconhecido na pasta dos pedidos (`FAIL refused request: <nome>`, só letras, dígitos, `.`, `_` e `-`, até 32 caracteres). O pedido em dobro e o toque que acordou o console não geram evento, só uma linha no log do kernel |

| `card` | `lume-card` (device-fixes D4, pedidos em [`docs/LAUNCHER.md`](LAUNCHER.md#pedidos-de-manutenção-do-cartão-interface-congelada)): TRIM iniciado (`OK trim: started`); concluído (`OK trim: <bytes> bytes trimmed`); falhou (`FAIL trim: <motivo>`, a última linha do `fstrim`, ou `no games partition`, ou `last-trim not written`); pedido com outro em andamento, apagado sem rodar (`FAIL trim: busy, request dropped`); verificação pedida para o próximo boot (`OK check-next-boot: requested for the next boot`) ou não gravada (`FAIL check-next-boot: <motivo>`); nome desconhecido na pasta dos pedidos, apagado (`FAIL refused request: <nome>`, só letras, dígitos, `.`, `_` e `-`, até 32 caracteres, o resto vira `?`) |

Exemplo de um `push --hot` (o `<time>` e o `<boot>` são os do console; a linha vem do `event` do
próprio console e é descarregada no cartão na hora):

```
2026-11-17T10:22:41 47 push OK hot lume-audio 0.3.1-r4
2026-11-17T10:22:44 47 push FAIL hot lume-audio 0.3.1-r4 restart lume-mixer
```

O `dev watch` grava uma linha dessas a cada ciclo bem-sucedido; o build dele fica no PC, em
`out/dev-watch/<fragmento>.log`, não nos logs do console. O `lume dev log` mostra essas linhas
junto com as do boot atual.

### O que o `lume push` e o `lume dev` leem

Estas linhas e arquivos são contrato: mudar o formato quebra a verificação.

- `/run/lume/logs/boot-n` (RAM): o número do boot atual. O `push` o lê antes do reboot e
  depois dele; o boot novo precisa ter outro número (o relógio do console não é confiável).
- `events.log`, a linha `<time> <n> boot OK completed: ...` do boot `<n>` (o segundo campo
  é o número do boot): o `push` espera por ela até 120 s e mostra o detalhe
  (`frontend in <s>s from kernel`) no `ok: boot N completed with build X (...)`. O autoteste
  (`boot-completed`) e o `lume dev log` leem a mesma linha; o `dev log` imprime todas as
  linhas do boot atual do `events.log` depois do `boot-<n>.log`.
- `/boot/VERSION` (linha `build: <carimbo>`): comparada com o build enviado.
- `boot/boot-<n>.log` (RAM, senão `ROMS/logs/boot/`): o que o `dev log` imprime primeiro; o
  autoteste confere que existe (`bootlog-written`).
- `lume-index: scan ... failed=<n>` do syslog do boot: o autoteste (`lume-index-scan`) passa
  com `failed=0`, ou se o scan ainda roda.

## Energia: FIFO, perfis e `power.state` (game-governor)

Protocolo congelado na change `game-governor` (nó 1.1). Código: `lume/lume-core/src/power.rs`
(escritor), `powerstate.rs` (leitor), `powerconf.rs` (editor) e
`aports/lume-power/files/usr/libexec/lume/power-profiles.sh` (validador em shell, `source` pelo
`lume-power`).

### FIFO `/run/lume/power`

Uma mensagem por linha, escrita pelo `lume-ui` e pelo `lume-run` (grupo `game`):

| Mensagem | Quem | Efeito |
|---|---|---|
| `menu` | `lume-ui` | cenário menu |
| `idle` | `lume-ui` | cenário launcher parado |
| `game <sistema> <core> [<chave>]` | `lume-run`, antes do `exec` | cenário jogo (perfil pela `<chave>` do jogo, depois pelo `core`, depois pela classe do sistema, depois `game`); a chave é `lume_core::power::game_key` da ROM (FNV-1a 64 do caminho relativo a `ROMS/roms/`, `<sistema>/<arquivo>`, 16 dígitos hex; `game_key_of(sistema, caminho do gamelist)` dá a mesma), nunca o nome; uma linha de 3 palavras continua valendo |
| `end` | `lume-run`, depois de o cgroup esvaziar | volta ao menu |
| `reload` | quem mudou o `power.conf` | relê os arquivos e reaplica o perfil do cenário (no jogo, só na próxima fronteira) |
| `controller <chave>` | o próprio serviço (o subshell do controlador) | o controlador saiu sozinho: o perfil do jogo de novo, sem ele (chave errada é ignorada) |
| `manual` | `lume-power set`/`auto` (root, pelo cabo) | relê `/run/lume/power.manual` (só o root grava): com um nome, aplica esse perfil já e em todo cenário (medição, D5); sem o arquivo, volta ao perfil do cenário |

O escritor abre o FIFO com `O_NONBLOCK`, sem criá-lo: sem o serviço (sem FIFO, sem leitor, pipe
cheio) a mensagem é descartada e o chamador segue. Espaço ou caractere de controle em
`<sistema>` e `<core>` vira `_`, vazio vira `-`. API: `lume_core::power::notify(&Message)`.

### Serviço `lume-power`

`/usr/bin/lume-power` (pacote `lume-power`), serviço do OpenRC no runlevel `boot` sob o
`supervise-daemon`. Ao subir guarda o padrão do kernel em `/run/lume/power.default`
(governor, `cpuinfo_min_freq`, `cpuinfo_max_freq`, `max_freq` do devfreq; um respawn o reusa),
cria o FIFO (grupo `game`, `0620`), mantém o FIFO aberto para leitura e escrita (o `read -t 60`
dorme até chegar mensagem e nunca vê fim de arquivo) e aplica o perfil `boot`. Cada perfil é
aplicado por cima do padrão do kernel (chave ausente = valor do kernel), na ordem do D4:
núcleos que faltam, `scaling_min_freq`/`scaling_max_freq` (descendo, o mínimo primeiro;
subindo, o máximo primeiro), governor, parâmetros do governor, núcleos a mais (nunca o `cpu0`),
`max_freq` da GPU; só escreve o que muda. Cenário sem perfil, perfil recusado e `enabled 0`
ficam no padrão do kernel; no jogo, sempre com `scaling_min_freq` no `game_min`. A bateria (a
fonte `power_supply` do tipo `Battery`) é lida a cada mensagem e a cada 60 s, sem processo novo.
Eventos gravados antes de o `lume-logd` numerar o boot esperam em `/run/lume/power.early` e
entram no `events.log` com o número certo.

**Controlador pela carga (D12):** num perfil de jogo com `controller=load`, o serviço aplica o
perfil e liga o `/usr/bin/lume-powerctl` (pacote `lume-powerctl`, C, por arquitetura) num
subshell que espera por ele. O controlador põe o governor em `userspace`, começa no maior
degrau permitido e, a cada 250 ms, lê `utime`+`stime` de todas as threads dos processos do
cgroup de jogo mais novo (`/sys/fs/cgroup/lume/game-*`, pelo `mtime`) e toma a thread mais
ocupada (o "processo principal" é o dono dela: o runner que o `lume-run` executa no cgroup).
Sobe um degrau de `scaling_available_frequencies` depois de 1 s acima de 85% de um núcleo,
desce um depois de 3 s abaixo de 50%, sempre entre o `min` do perfil (o `scaling_min_freq` já
com o piso de jogo) e o `max`, e nunca acima do `scaling_max_freq` atual (o teto térmico, lido a
cada amostra). Roda com `nice -10`. Termina no SIGTERM (`end=stop`, o serviço o para antes do
perfil seguinte), quando o cgroup do jogo esvazia ou some (`end=game`), sem jogo em 10 s
(`end=no-game`), com o serviço morto (`end=owner`) ou com outro governor posto por fora
(`end=governor`, código 4). Sem `userspace` em `scaling_available_governors` ele recusa (código
3, nada muda). Ao sair, imprime o tempo em cada degrau, que o subshell grava como
`power OK controller: ...` (ou `FAIL controller: exit <código>: ...`); se ele saiu sozinho, o
subshell manda `controller <chave>` ao FIFO do próprio serviço, que reaplica o mesmo perfil sem
o controlador (`profile: game -> <perfil> (without controller)`), sem laço de espera. A saída do
controlador fica em `/run/lume/powerctl.out`.

**Controlador por gargalo (D17):** com `controller=auto`, o mesmo binário roda com `--mode auto`,
a faixa da GPU do perfil (`--gpu-min`, `--gpu-max`, o diretório do devfreq em `--gpu`) e
`--state /run/lume/powerctl.state`; no R36S o serviço liga antes o `profiling` do `panfrost`.
Uma decisão por segundo, com três sinais de fora do jogo: a thread mais ocupada da CPU (como
acima), a ocupação da GPU (o maior `drm-engine-*` do `fdinfo` dos arquivos do DRM que o jogo
tem abertos, `/proc/<pid>/fd` -> `/dev/dri/*`, achados a cada 2 s, um cliente por
`drm-client-id`) e os quadros entregues (`drm-page-flips` do mesmo `fdinfo`, patch 0036; alvo =
maior ritmo dos últimos 30 s, queda = abaixo de 90% dele). Regras: recurso acima de 85% sobe
um degrau; queda de quadros em duas janelas seguidas sem recurso saturado sobe o mais ocupado se ele passa de 50%
(`pacing`), senão é `sync` (vsync, áudio, painel: não sobe nada); recurso abaixo de 50% por 3 s,
sem queda por clock e sem subida nos últimos 5 s, desce um; nunca acima do teto térmico.
A CPU vai pelo `scaling_setspeed`; a GPU pelo `min_freq` do devfreq (o `simple_ondemand` segue
livre acima dele), devolvido ao parar. Faixa de um degrau = recurso travado, não controlado (a
CPU fica no governor do perfil). Sem `drm-page-flips` ele vira o controlador pela carga nos dois
recursos. A linha ao parar:

```
power OK controller: cpu: 1008000=12.0s 912000=3.0s gpu: 384000000=4.0s 240000000=11.0s up=2 down=3 bottleneck cpu=1 gpu=2 pacing=0 thermal=0 memory=0 sync=0 mem_min=412000k end=stop
```

`/run/lume/powerctl.state` (reescrito a cada segundo enquanto o controlador vive, apagado ao
parar; para a barra de status e a tela futura):

```
mode auto
cpu_khz 912000          # degrau atual (ou o clock atual, com a CPU travada)
cpu_load 63             # % de um núcleo da thread mais ocupada, -1 sem amostra
gpu_hz 240000000        # piso atual da GPU (ou o clock atual, travada), -1 sem devfreq
gpu_busy 41             # %, -1 sem drm-engine-*
fps 59.9                # -1.0 sem drm-page-flips
fps_target 60.0
bottleneck gpu          # none, cpu, gpu, pacing, thermal, memory ou sync
mem_avail_kb 412000     # MemAvailable; memory = abaixo de 32 MiB (só diagnóstico, D19)
```

Linha de comando (root, pelo cabo): `lume-power set <perfil|default>` (modo manual da
medição: aplica já e mantém até `auto` ou reboot), `lume-power auto`, `lume-power reload`,
`lume-power status` (imprime o `power.state`).

### Arquivo de perfis

Duas camadas: `/usr/share/lume/power/<console>.conf` (imagem) e, por cima, o
`ROMS/system/lume/power.conf` (cartão, escrito à mão ou pela interface). Uma entrada por linha;
linhas em branco e `#` (inclusive no fim da linha) são ignorados.

```
profile <nome> chave=valor...   governor min max cores gpu_min gpu_max up_threshold
                                sampling_down_factor rate_limit_us controller=load|auto
class <sistema> <perfil>        perfil da classe do sistema
core <core> <perfil>            exceção por core
game <chave> <perfil>           perfil de um jogo (só no cartão; chave de 16 dígitos hex)
battery warn=<%> critical=<%>
enabled 0|1
idle after=<segundos>           0 desliga
limit game_min=<khz>            piso de jogo; só no arquivo da imagem
```

- `min` e `max` em kHz na tabela de `scaling_available_frequencies` (ou entre
  `cpuinfo_min_freq` e `cpuinfo_max_freq` sem tabela), `gpu_min` e `gpu_max` em Hz na tabela
  do devfreq, `governor` em `scaling_available_governors`, `cores` de 1 ao número de núcleos,
  `min` <= `max`, `gpu_min` <= `gpu_max`. Ajuste manual por recurso (D18): `min=max` trava a
  CPU, `gpu_min=gpu_max` trava a GPU; com `controller=auto`, o controlador escolhe dentro da
  faixa de cada recurso que tenha mais de um degrau.
- `game <chave> <perfil>` só vale no `power.conf` (na imagem é recusado), com a chave de 16
  dígitos hex; precedência no jogo: `game`, `core`, `class`, perfil `game`.
- Um perfil inválido é recusado inteiro. A linha do cartão recusada deixa a da imagem valer;
  `class`/`core` que apontam para perfil recusado ou desconhecido são recusadas (a classe usa o
  perfil `game`). Linha desconhecida é registrada e ignorada. O cartão vale por chave: `profile
  <nome>`, `class <sistema>`, `core <core>`, `game <chave>`, `battery`, `idle`, `enabled`.
- **Piso:** todo perfil usado em jogo (`game` e os alvos de `class`/`core`/`game`, de qualquer camada)
  sem `min` recebe `min=<game_min>`; `min` ou `max` abaixo do piso recusa o perfil. Perfis só de
  boot, menu e idle não têm piso. `limit` no `power.conf` é registrado e ignorado. Se o
  `game_min` não é um OPP, o arquivo da imagem é recusado inteiro e o piso vira o maior OPP
  <= 600 MHz. Sem `limit` não há piso (R36S). O serviço mantém `scaling_min_freq` no piso
  efetivo também para um perfil de jogo recusado e com `enabled 0`.

Validador (`power-profiles.sh`): `pp_load <imagem> [cartão]` imprime os registros aceitos e os
`refused`, e sai com 0 (tudo aceito), 1 (algo recusado) ou 2 (imagem ilegível ou recusada
inteira); `pp_floor <imagem>` imprime o piso efetivo em kHz; `pp_state <console> <imagem>
[cartão]` imprime o `power.state`. Cada recusa vai também para `pp_log FAIL`, que o serviço liga
ao `event power`. `PP_SYS` troca a raiz do sysfs nos testes (`tests/unit/test_power_profiles.py`).

### `/run/lume/power.state`

Gravado pelo serviço a cada carga e troca de perfil (legível pelo grupo `game`), uma chave por
linha, `<chave> <valor...>`; leitores ignoram chaves desconhecidas:

```
console ga36
enabled default 1                       # enabled <origem> 0|1; origem image, card ou default
cpu_freqs 120000 240000 ...             # kHz
cpu_governors performance schedutil ...
cpu_cores 4
gpu_freqs 144000000 ...                 # Hz, vazio sem devfreq
game_min 600000                         # piso efetivo; ausente sem piso
limit image game_min=600000
profile <origem> <nome> chave=valor...  # perfis em vigor, com o piso já em min=
class <origem> <sistema> <perfil>
core <origem> <core> <perfil>
game card <chave> <perfil>              # perfis por jogo, só a chave
battery <origem> warn=5 critical=3     # battery default ... sem linha battery
idle default after=120                  # idle <origem> after=<s>
scenario game                           # boot, menu, idle ou game
current heavy                           # perfil em vigor, - se nenhum
manual heavy                            # só no modo manual (lume-power set)
refused <origem> <tipo> <nome|-> <motivo...>
```

Leitor: `lume_core::powerstate::PowerState::read`. Editor do `power.conf`
(`lume_core::powerconf`): troca ou acrescenta uma linha (`profile`, `class`, `core`, `game`,
`battery`, `idle`, `enabled`) depois de validar contra o `power.state` (valores do console, piso), mantém
comentários, ordem e linhas desconhecidas byte a byte e grava de forma atômica (temporário na
mesma pasta, `fsync`, `rename`); depois a interface manda `reload`.

## Coletor: `lume-logd` e `lume-logd`

O serviço `lume-logd` (shell, `lume-core`) abre o boot, grava o retrato do hardware, confirma o
device tree e então passa o laço de amostras ao `lume-logd` (C, APK `lume-logd`,
`/usr/bin/lume-logd run`), que a cada `interval` grava a linha de métricas, as linhas `fe=` e
`usb:` do rastreio e os eventos da amostra, e rastreia as mensagens do kernel (`k [...]`) direto
do `/dev/kmsg`, durante a espera. O formato é o mesmo das seções abaixo. Para o trabalho raro
ele chama o shell de volta: `logd flush` (a descarga a cada `flush` s, numa troca de estado do
frontend e enquanto ele não responde), `logd snapshot <pid> <estado>` (o retrato detalhado de um
RetroArch travado) e `logd kick` (reabilitar a interrupção da tela mascarada; saída 0 = a tela
voltou, 1 = gravou sem efeito, 2 = nada gravado). Sem o binário (imagem antiga), o laço em shell
roda como antes. Custo medido no GA36 (game-governor 1.2): 0,8% de um núcleo no launcher parado
e 0,9% num jogo.

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
| `input_rss_kb` | memória residente do daemon de entrada (`lume-input`) em KiB |
| `input_cpu_pct` | CPU do `lume-input` em % de um núcleo |

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
  driver de vídeo, de áudio ou do cartão aparecem aqui, com a hora do kernel, no formato do
  `dmesg`). Desde a change `game-governor` (D8) elas vêm do `/dev/kmsg`, lido por um leitor
  que roda ao lado do `logd` o boot inteiro, e a hora no começo da linha é a da chegada da
  mensagem, não a da amostra seguinte.

Custo da coleta (change `game-governor`, D8, P-60): a amostra não dispara processos. Os
arquivos são lidos com o `read` do shell, as contas são do shell, a hora vem de um `date` por
minuto mais o `uptime`, e o `pid` de cada processo é guardado entre amostras. Sobram: o
`pidof` quando um processo vigiado mudou (ou o RetroArch é procurado e não está, fora do
launcher), o `nc` do `GET_STATUS` enquanto o RetroArch roda, um `stat` quando o log do
frontend mudou e a descarga em lote (`flush`).
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
  `TCON_GINT0` (base do `lcd-controller` + 4) com o `lume-devmem`. Um console saudável tem
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

## Entrada (`lume-input`) no `boot/boot-<n>.log`

O daemon de entrada grava no log do kernel (e por isso no `boot/boot-<n>.log` e nas linhas
`k` do `trace/`) uma linha ao subir e uma por problema:

```
lume-input: "GA36-MB Gamepad" from 2 of 2 source(s), socket /run/lume/input.sock, volume DAC
lume-input: no input device named "1c21800.lradc" (optional)
lume-input: source device "gpio-keys" gone
```

`from 1 of 2` com uma origem `(optional)` faltando quer dizer que aquele dispositivo (os
botões de volume, ou os analógicos do R36S) não foi achado pelo nome do perfil: o controle
funciona sem ele. Uma origem obrigatória faltando faz o serviço tentar de novo
(`supervise-daemon`, até 5 vezes).

O sono (device-fixes D11) deixa no log do kernel só o que não vira evento do `events.log`:

```
lume-input: no sleep service (/run/lume/sleep missing): power button request dropped
lume-sleep: suspend request dropped: busy (suspending 4)
lume-sleep: suspend request dropped: the press that woke the console
lume-sleep: suspend cancelled: power off requested
lume-sleep: poweroff request dropped: busy (poweroff)
lume-sleep: power button held: the session powers off
lume-sleep: power button held: no session, powering off
lume-sleep: the session did not power off within 30s: powering off
lume-sleep: cannot give /run/lume/sleep to the group game
```

O pedido de suspensão feito durante uma sequência (um segundo toque, o item Suspender) é
apagado no fim dela com a linha `busy (suspending <seq>)`. Com o botão segurado durante a
espera dos clientes, a suspensão é cancelada (tudo volta, sem evento `sleep OK suspend`) e o
desligamento roda em seguida.

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
| `device: SoC serial number <serial>, choice in dtb-<soc>-<serial>.conf` | o aparelho, pelo número de série do SoC (`/sys/devices/soc0`) |
| `device: bootloader serial number <serial>, choice in dtb-<soc>-<serial>.conf` | sem `soc0`, o número que o bootloader grava no DTB (`/serial-number`; o U-Boot de fábrica do R36S) |
| `no serial number: the choice in dtb-<soc>.conf applies to every <soc> device` | sem número de série: a escolha vale para todo aparelho do SoC |
| `force: BOOT/dtbs/force selects <id>` / `force ignored: '<nome>' ...` | escolha pelo PC aceita ou recusada (nome inválido) |
| `force ignored: <id> was discarded on this device (bad); ...` | `force` de um DTB descartado neste aparelho |
| `fallback: <id> was not confirmed in the previous boot; discarded` | volta ao último DTB confirmado |
| `list shown (<n> candidate(s)[, <m> converted])`, `list: <id> chosen and saved`, `list: automatic chosen, ...` | lista aberta pela tecla de seleção; `converted`: quantos DTBs de `vendor/` ela mostrou |
| `selected <id> (reason: default\|rule\|manual\|forced\|fallback\|reverted\|learned\|auto\|search)` | **o DTB escolhido e o motivo** (`rule`: as regras de um DTB bateram, inclusive as do padrão, como o ID do painel do R36S V5; `learned`: aprendido antes para a assinatura; `auto`: o painel respondeu ao DTB em uso, que é aprendido; `search`: o painel não respondeu e o próximo candidato é testado) |
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
| `no question on the screen (...): <id> stays pending until the frontend starts` | sem tecla de confirmar: o `lume-logd` confirma quando o frontend sobe |
| `back from a device tree that was not confirmed: no question, no switch` | terceiro início, depois da volta |
| `kexec -e failed: <id> is no longer pending` | o `kexec -e` falhou e o boot segue com o DTB em uso |
| `no device tree` | sem device tree (a VM): nada a escolher |

O estado fica em `ROMS/system/etc/dtb-<soc>-<serial>.conf` (`manual=`, `good=`,
`pending=`, `bad=`), um arquivo por aparelho, identificado pelo número de série do SoC
(`/sys/devices/soc0/serial_number`) ou, sem ele, pelo `/serial-number` que o bootloader grava
no DTB (levado adiante no kexec); sem nenhum dos dois, `dtb-<soc>.conf`, um por SoC. Um DTB que não
é o padrão e ainda não foi confirmado no aparelho fica `pending` e é confirmado na tela; se
a pergunta não pôde aparecer, o `lume-logd` o confirma quando o frontend sobe (`good=` e
sem `pending=`). Um DTB que continua `pending` no boot seguinte não foi confirmado e é
descartado (`fallback`). No `events.log`, a escolha vira `boot OK device tree selected …`,
a confirmação na tela `boot OK device tree confirmed on screen: …`, a do frontend
`boot OK device tree <id> confirmed: the frontend started (no question on the screen)`, e o
fallback, a falta de resposta e os erros do `lume-bootsel` viram `boot FAIL device tree …`.
O `hw/boot-<n>.txt` traz o DTB em uso e o arquivo de estado no campo `dt in use`.

O aprendido (D15) fica em `ROMS/system/etc/dtb-<soc>-learned.conf`, uma linha
`panel:<hex>=<id>` por assinatura, comum a todos os aparelhos do SoC que usam o cartão: vale
para qualquer aparelho cujo painel responda o mesmo ID.

## Raiz do sistema (slots) no `boot/boot-<n>.log`

Nos consoles, o sistema é um conjunto de slots squashfs em `BOOT/<console>/slot/`, descrito
pelo manifesto `BOOT/<console>/SLOTS` (change `build-speed`, D9). O initramfs monta `lume`,
`runtime` e `base` como `lowerdir` do overlay (o de cima prevalece), embaixo da camada de 32 MiB
na RAM, e o slot `modules` em `/lib/modules`. As linhas `core-<nome>` do manifesto são
ignoradas no boot (P-80). A ordem de tentativa é:

1. `<console>/SLOTS`;
2. `<console>/SLOTS.old` (o conjunto anterior), quando o `SLOTS` falta, está truncado, cita um
   arquivo ausente ou algum slot dele não monta;
3. o `<console>/SYSTEM` antigo (ou o `SYSTEM.old`), como antes dos slots;
4. o modo de resgate, com a mesma mensagem de antes (`BOOT has no <console>/SYSTEM, …`).

Um conjunto que falha no meio é desmontado inteiro (do último ao primeiro) antes do passo
seguinte: nunca sobra um overlay pela metade. O cartão antigo, sem `SLOTS` nem `SLOTS.old`, não
ganha linha nova: monta o `SYSTEM` exatamente como antes. Linhas, com o prefixo `lume:`:

| Linha | Significado |
| :--- | :--- |
| `slots: <manifest> (build <id>)` | conjunto montado: `<manifest>` é `<console>/SLOTS` ou `<console>/SLOTS.old`, `<id>` o build dele |
| `slot <name>: <file> (packages: <n>)` | um slot do conjunto (`base`, `runtime`, `lume`, `modules`), o arquivo na `BOOT` (`<console>/slot/<name>-<sha12>`) e quantos pacotes ele traz |
| `slot <name> packages: <package>-<version> …` | os pacotes do slot com a versão, em linhas de até ~400 caracteres (cabem num registro do `dmesg`) |
| `root: <manifest> (lume, runtime, base; read-only) + 32 MiB RAM layer` | raiz montada pelos slots |
| `root: <file> (read-only) + 32 MiB RAM layer` | raiz montada pelo `SYSTEM` antigo (cartão antigo ou depois das falhas abaixo) |
| `ERROR: <console>/SLOTS <reason>; using <console>/SLOTS.old from the previous build` | o `SLOTS` falta (`push` cortado entre os dois `mv`), está truncado ou cita um slot ausente; `<reason>` diz qual |
| `ERROR: <console>/SLOTS <reason> and <console>/SLOTS.old <reason>; no slot set to mount` | nenhum dos dois manifestos serve |
| `ERROR: no slot set of <console> to mount; trying the old <console>/SYSTEM` | segue para o `SYSTEM` antigo depois da linha acima |
| `ERROR: failed to mount slot <name> (<file>) of <manifest>` | um slot não montou (squashfs corrompido, sem dispositivo loop, arquivo ruim); o que já estava montado do conjunto é desmontado |
| `ERROR: failed to mount slot modules (<file>) of <manifest>` | o slot `modules` não montou; o conjunto inteiro é desmontado |
| `ERROR: failed to mount the RAM layer for <manifest>` | o `tmpfs` da camada de escrita não montou |
| `ERROR: failed to mount the overlay of <manifest>` | o overlay dos slots não montou |
| `ERROR: <manifest> gives the overlay lowerdir "<lowerdir>"` | o manifesto não deu os três slots do overlay na ordem esperada |
| `ERROR: failed to unmount <path>` | um ponto de montagem do conjunto que falhou não desmontou nem com `umount -l` |
| `ERROR: <console>/SLOTS could not be mounted; using <console>/SLOTS.old from the previous build` | o `SLOTS` estava bom mas não montou: tenta o conjunto anterior |
| `ERROR: <console>/SLOTS could not be mounted and <console>/SLOTS.old <reason>; trying the old <console>/SYSTEM` | o `SLOTS` não montou e o `SLOTS.old` não serve |
| `ERROR: <console>/SLOTS.old could not be mounted either; trying the old <console>/SYSTEM` | nenhum dos dois conjuntos montou |
| `ERROR: <console>/SLOTS.old could not be mounted; trying the old <console>/SYSTEM` | só havia o `SLOTS.old` e ele não montou |

Com os slots, a linha de módulos (seção abaixo) traz o slot: `modules:
<console>/slot/modules-<sha12> (<release>)`, com a mesma conferência de versão. Na VM não há
slots: ela monta o `BOOT/SYSTEM` como antes.

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
- `== fragments`: a versão de cada fragmento do projeto instalado no console (pacotes
  `lume-*` e `lume-*` do banco do apk, lidos de `/lib/apk/db/installed`), uma linha
  `   <pacote>:   <versão>` por fragmento, em ordem alfabética (por exemplo
  `   lume-core:   1.0-r5`). Mostra qual versão de cada fragmento rodou naquele boot; o
  `lume push` confere essas mesmas versões depois do reboot e falha quando diferem das
  que enviou (`the console runs lume-core 1.0-r4, the push sent 1.0-r5`).
- `== component check`: para cada componente esperado (LEDs, USB OTG, USB host, PHY,
  entrada de energia USB/DC, bateria e carregador, PMIC, vídeo, painel, backlight, GPU,
  decodificador de vídeo, áudio, DMA, botões, gamepad, cartão, RTC, watchdog, sensor
  térmico, UART, I2C/RSB, Wi-Fi/Bluetooth), diz se o hardware está no device tree, se o
  kernel criou o dispositivo e **qual driver o ativa** (`NO DRIVER` quando não há),
  ou se o nó existe mas está desativado (`disabled in DT`). Traz também o modo do USB OTG,
  o estado da entrada de energia e os LEDs com driver, brilho e gatilho.
- `== memory` traz, só no GA36 (com o `lume-devmem` instalado), o bloco
  `-- DRAM clock (A33 registers, read only)`: os registradores crus `PLL_DDR1_CTRL_REG`
  (0x01c2004c), `PLL_DDR1_PAT_CTRL_REG0/1` (0x01c202ac/b0), `DRAM_CFG_REG` (0x01c200f4) e
  `PLL_DDR_CFG_REG` (0x01c200f8) e a linha `dram effective: memory <MHz> MHz, controller
  <MHz> MHz (pll-ddr1 24 MHz x N=<n> = <MHz> MHz, M+1=<m>; ...)` (P-23). A conta é a parte
  inteira do PLL (24 x N), memória = PLL / 2 e controlador = PLL / (M+1); a fração do
  sigma-delta não entra (o registrador cru está na linha acima, com `sigma-delta on/off`).
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
