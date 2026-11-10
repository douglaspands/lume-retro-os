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
  frontend/boot-<n>.log   log do RetroArch (também o log mostrado quando ele falha)
  .boot                   contador de boots (não apague só ele)
  .clean                  marcador de desligamento limpo
```

`<n>` é o número do boot e é o mesmo em todas as pastas: `boot/boot-12.log`,
`hw/boot-12.txt`, `metrics/boot-12.csv` e `frontend/boot-12.log` são do mesmo boot.

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
| `enable` | `1` | `0` desliga o retrato do hardware e as métricas. O log de boot, os eventos e o log do frontend continuam |
| `interval` | `5` | segundos entre amostras de métricas (mínimo 1) |
| `flush` | `60` | segundos entre gravações no cartão (mínimo 5) |
| `keep_boots` | `30` | quantos boots manter em `boot/`, `hw/`, `metrics/` e `frontend/` |
| `max_mb` | `64` | teto de `ROMS/logs/` em MiB (mínimo 8) |

Valores fora da faixa são ignorados e o padrão vale.

## Rotação

- `boot/`, `hw/`, `metrics/` e `frontend/`: os `keep_boots` boots mais recentes.
- `metrics/boot-<n>.csv` para de crescer em 4 MiB (cerca de 30 h a 5 s).
- `frontend/boot-<n>.log`: os últimos 4 MiB do log do RetroArch.
- `events.log` vira `events.1.log` em 1 MiB, e são mantidos 3 antigos.
- Acima de `max_mb`, apaga primeiro as métricas mais antigas, depois os logs do
  frontend, os retratos, os logs de boot e os eventos antigos. Os arquivos do boot atual
  nunca são apagados por esse teto.

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
| `frontend` | iniciado; encerrado pelo usuário ou pelo serviço; terminou com erro; parado após 3 falhas |
| `game` | aberto (core e conteúdo); fechado (core, conteúdo e duração em segundos) |
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

## `hw/boot-<n>.txt`

Texto com seções `== system`, `== CPU` (cores, governor, frequências), `== memory`,
`== thermal` (zonas e limites), `== regulators`, `== battery and power`,
`== storage`, `== video`, `== audio`, `== input` e o resumo de hardware mostrado
antes do frontend. É gravado depois que o frontend sobe, e por isso inclui o tempo até
ele.
