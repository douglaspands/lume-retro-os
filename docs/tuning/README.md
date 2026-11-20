# Afinação dos cores por configuração

Método da medição A/B da change `game-experience-tuning` (D6). Os relatórios por console são
[`ga36.md`](ga36.md) e [`r36s.md`](r36s.md); os ajustes aceitos e a ligação com a P-10
(otimização por compilação) estão no fim deste arquivo (tarefa 8.1). O aprendizado do melhor
core por jogo fica só no cartão ([`aprendizado-cores.md`](aprendizado-cores.md)).

## Como rodar

Com o console no cabo, a imagem e o conjunto de teste (`var/roms_test/`, `lume dev roms push`)
no cartão, e o `lume-power` no modo automático (o modo manual é recusado):

```
.venv/bin/python tests/device/tuning_ab.py baseline --console ga36 --dry-run   # só o plano
.venv/bin/python tests/device/tuning_ab.py baseline --console ga36             # linha de base
.venv/bin/python tests/device/tuning_ab.py <plano> --console ga36 --only gpsp:<variante>
```

O plano é um arquivo de `tests/device/tuning/` (formato no cabeçalho do `baseline.toml`): por
core, o sistema e a posição do jogo na lista (nunca o nome) e as variantes, cada uma com chaves
do RetroArch (`retroarch = { ... }`) e/ou opções do core (`options = { ... }`). A linha de base
de um core é medida sozinha quando o relatório do console ainda não tem a dele
(`--rebaseline` mede de novo); uma variante sem linha de base no relatório é recusada.

## Uma execução

1. Devolve os arquivos salvos (configuração do RetroArch do usuário,
   `/run/lume/retroarch-extra.cfg` e o `.opt` do core) e, em B, aplica a variante: as chaves vão
   no fim do `retroarch-extra.cfg` (a última camada do `frontends/retroarch`), as opções
   substituem as mesmas chaves no `~/.config/retroarch/config/<corename>/<corename>.opt`.
2. Abre o jogo N do sistema pelo mesmo motor do `lume dev run` e confere, no evento
   `game OK <sistema> retroarch <core> start`, que o core é o do plano.
3. Espera 30 s e mede 120 s (amostrador no console + linhas do `lume-logd` da mesma janela).
4. Fecha o jogo e devolve os arquivos salvos.

A pasta das opções de um core é a do `library_name` que o próprio core informa ao RetroArch. Num
build `_lume` ela é a mesma do core do upstream (só o `corename` do `.info` ganha " (Lume)"),
então a ferramenta tira o sufixo, como o `frontends/retroarch` (conferido no GA36, 2026-11-20).

**LÖVE (tarefa 7.4).** Uma entrada com `process = "love"` aceita só variantes `env = { NOME =
"valor" }`: em B, o `ROMS/system/lume/runners.d/love.toml` do cartão (que vence o da imagem)
ganha um `[runner.env]`. O launcher lê os runners uma vez, quando volta depois de um jogo, então
cada execução do LÖVE grava o arquivo da execução **seguinte** antes de fechar o jogo (o jogo
aberto já tem o ambiente fixado), e a restauração entre execuções não mexe nele; no fim do grupo
o arquivo volta como estava.

O `frontends/retroarch` grava as chaves do `retroarch-extra.cfg` na configuração do usuário
(não só na execução), por isso a configuração inteira é salva antes da sequência e devolvida
depois de cada execução; uma sequência interrompida é desfeita no início da seguinte.

Ordem: linha de base `A, A`; cada variante `A, B, A`. A diferença entre os dois A é o ruído.

## Comparação de cores (tarefa 10.2)

Uma entrada do plano cujas variantes são `core = "<nome>"` compara cores num mesmo jogo
(plano `arcade-cores.toml`: os jogos 1 a 8 da pasta `arcade` em `fbneo`, `fbalpha2012`,
`mame2003_plus` e `mame2000`). `positions = [1, 2, ...]` cria uma entrada por jogo. Não há
linha de base separada: em cada sequência `A, B, A`, os A rodam o core padrão do sistema e
são a referência daquele jogo.

```
.venv/bin/python tests/device/tuning_ab.py arcade-cores --console ga36 --dry-run
.venv/bin/python tests/device/tuning_ab.py arcade-cores --console ga36 --only fbneo:mame2000
```

- **Troca do core só durante a execução:** o core vai pela opção por jogo do próprio launcher
  (`ROMS/system/lume/games/<sistema>.toml`, `options.rs` do `lume-core`), escrita **no
  console**: o comando remoto acha o caminho do jogo N no índice do launcher
  (`cache/index/<sistema>.bin`, a mesma ordem da grade), escapa o caminho para TOML lá mesmo e
  responde só `applied`; o caminho nunca passa pelo cabo. O arquivo original vai para
  `/run/lume/tuning` junto com a configuração do RetroArch e volta depois de cada execução, no
  fim da sequência, num erro ou Ctrl+C, e no início da medição seguinte se uma ficou
  interrompida. Nos A o arquivo fica vazio (o jogo abre no core padrão); em B, só com o jogo
  medido.
- **Core fora do catálogo:** o launcher só aceita o core guardado se o sistema o oferecer;
  enquanto ele não está em `alt_cores` (tarefa 10.5), o arquivo
  `ROMS/system/lume/systems.d/zz-lume-tuning.toml` o oferece durante a sequência (o launcher lê
  o catálogo quando volta depois do A1) e é apagado no fim.
- **Não instalado:** sem `/usr/lib/libretro/<core>_libretro.so`, a sequência inteira fica
  "não instalado" e nada roda.
- **Não abre:** B sem o evento `game OK <sistema> retroarch <core> start` em 90 s, com
  `start-failed`, aberto em outro core ou terminado antes do fim da medição. Fica registrado só
  o motivo (`start-failed`, `timeout`, `other-core`, `ended-early` ou `exit=<código>
  end=<como>` do evento de fim do `lume-run`), o A2 é pulado e a medição segue para a próxima
  sequência.
- **Resultados por jogo:** em `out/tuning/<console>-cores.jsonl` (fora do git; só posição,
  core, motivo e métricas). No fim, a ferramenta mostra no PC o core escolhido por jogo (pela
  posição): o de menor clock médio entre os que rodam com velocidade cheia e sem mais falhas de
  áudio que o padrão (empate: mais quadros); sem nenhum com velocidade cheia, o mais rápido. A
  escolha vai para o cartão do usuário, nunca para o repositório.
- **Relatório:** a seção "Cores alternativos por família de hardware" de
  `docs/tuning/<console>.md` é reescrita a partir dos resultados depois de cada sequência: uma
  linha por core e família, com jogos, quantos abrem, quantos com velocidade cheia, médias,
  diferença contra o padrão nos mesmos jogos e em quantos jogos o core foi o escolhido.

### Arquivo de famílias (privado)

A família de hardware de cada posição do conjunto de teste é dado privado: fica num arquivo
fora do git, por padrão `var/roms_test/families.toml` (`--families` muda o caminho). Uma tabela
por sistema, posição do jogo na grade = nome curto da família (`[a-z0-9_.+-]`, sem nome de
jogo):

```toml
[arcade]
1 = "cps1"
2 = "neogeo"
3 = "irem"
```

Sem o arquivo, o relatório agrupa só por core (família `todas`); uma posição que falta no
arquivo entra como `sem-familia`.

## Métricas e fontes

| Métrica | Fonte |
|---|---|
| quadros mostrados por segundo | `drm-page-flips` do fdinfo do processo do jogo (patch 0036 do kernel), fim menos início da janela, um contador por `drm-client-id` |
| velocidade do core | média da coluna `fps` do `lume-logd` (contador do `GET_STATUS`, patch 0004 do RetroArch) sobre `fps_nominal` |
| falhas de áudio | `status` do ALSA do stream do jogo, uma amostra por segundo (abaixo) |
| clock médio | `stats/time_in_state` do cpufreq, fim menos início (média ponderada pelo tempo); sem ele, a média de `freq_*_mhz` do `lume-logd` |
| CPU por núcleo | média de `cpu<N>_pct` do `lume-logd` |
| temperatura | média de cada `temp_*_c` do `lume-logd`; vale a zona mais quente |

Das métricas do `lume-logd` só saem colunas de uma lista fixa (`uptime_s`, `frontend`, `fps`,
`fps_nominal`, `temp_*`, `freq_*`, `cpu*`), filtradas no console: a coluna `content` (o nome
do jogo) nunca passa pelo cabo.

### Fonte das falhas de áudio (decidida na tarefa 5.1)

O `status` do ALSA (`/proc/asound/card*/pcm*p/sub*/status`), e não o log do RetroArch:

- o driver ALSA do RetroArch (`audio/drivers/alsa.c`, v1.22.2) recupera um underrun com
  `snd_pcm_recover(pcm, err, 1)`, o modo silencioso, sem nenhuma linha de log;
- o arquivo do kernel só traz `xrun_counter` com `CONFIG_SND_PCM_XRUN_DEBUG`, que depende de
  `CONFIG_SND_DEBUG`, desligado nos dois kernels;
- mas cada recuperação prepara o stream de novo, o que zera o `hw_ptr`
  (`snd_pcm_lib_ioctl_reset`, `sound/core/pcm_lib.c`), e o início seguinte grava um
  `trigger_time` novo (`snd_pcm_post_start`, `sound/core/pcm_native.c`).

A medida é então **segundos com underrun**: amostras de 1 s do stream cujo `owner_pid` é o
processo do jogo em que o estado é `XRUN`, o `trigger_time` mudou ou o `hw_ptr` voltou. Vários
underruns no mesmo segundo contam um (é um limite inferior). Um kernel com `xrun_counter` é
usado direto (contagem exata). Se o áudio passar pelo `dmix` (memória compartilhada do
alsa-lib, chave `0x0056a4d5`), o stream do hardware nunca sofre underrun: a métrica sai como
não medida e a variante fica "inconclusivo".

**Ponto cego: `audio_driver = "alsathread"`** (teste de ouvido do usuário no GA36,
2026-11-20). A thread do driver alimenta a ALSA a partir de um buffer próprio do RetroArch: o
stream do hardware não sofre underrun e a medida dá zero, mas o som picota igual quando o core
não acompanha (o mesmo jogo lento estalou igual com `alsa` e com `alsathread`). Variante com
`alsathread` não é medida por esta fonte; precisa de outra que veja o buffer do RetroArch.

## Critério de aceite (spec `core-tuning`, "Ajuste aceito só com ganho medido")

Para cada métrica, o ruído é a diferença entre os dois A, nunca menor que um piso (quadros/s
0,3; clock 10 MHz; temperatura 0,5 °C; velocidade 0,5 ponto; CPU somada 2 pontos). B é
comparado com a média dos dois A. A variante é **aceita** quando:

1. mantém a velocidade cheia do core (FPS do core ≥ 99% do nominal);
2. mantém o som contínuo (falhas de áudio de B ≤ as do melhor A);
3. melhora pelo menos uma de quadros mostrados (mais), clock médio (menor) ou temperatura
   (menor) acima do ruído;
4. não piora nenhuma de quadros mostrados, clock, temperatura, velocidade ou CPU somada acima do
   ruído.

Senão é **recusada**, com os motivos na coluna "decisão". Sem a medida de áudio (dmix, stream
não achado), fica **inconclusivo** e não entra na imagem.

## Ajustes aceitos e o que entrou na imagem (tarefa 8.1)

Uma linha "aceito" do relatório é candidata; entra na imagem só com a decisão do usuário, que
fica registrada aqui. Estado no GA36 em 2026-11-20:

| Ajuste | Relatório | Decisão |
|---|---|---|
| `audio_driver = "alsathread"` | "aceito" em vários cores | **fora**: ponto cego da medida de áudio (acima); o ouvido mostrou o mesmo picote |
| `video_max_swapchain_images = 2` | recusado em todos | fora |
| `audio_resampler_quality = 1` | recusado (sem ganho acima do ruído) | fora |
| `audio_latency = 96` | aceito só no `gambatte` (GBC: +1,4 quadros/s) no GA36; recusado no R36S (GBC e GB, sem ganho) | **fora** (recomendação; 32 ms a mais de atraso do som para um jogo de um console) |
| `video_threaded = false` | travou o GA36 (fora das medições) | fora; o PS1 já roda sem thread de vídeo por estabilidade (`retroarch-core.keys`) |
| core por placa de arcade | comparação de cores (10.2) | aplicado: catálogo (10.5) e core por jogo no cartão do usuário |
| build `_lume` (flags do processador) | comparação de cores (11.3) | aplicado: `genesis_plus_gx_lume`, `snes9x2005_plus_lume`, `pcsx_rearmed_lume` |
| BIOS oficial e abertura | pedido do usuário (1.5), não é ganho de desempenho | aplicado (`.opt` de fábrica e `new-defaults`) |

Medidos também: as opções do `fbneo` e do `mame2003_plus` nos jogos lentos (7.3, todas
recusadas: limite da CPU do A33), as variáveis do LÖVE (7.4, recusadas) e o R36S (7.5, nenhuma
chave aceita). **Velocidade no R36S:** a tela de 59,02 Hz fica dentro dos 5% de
`audio_max_timing_skew`, e o RetroArch põe o core no ritmo dela; a velocidade é medida contra a
taxa da tela nesse caso (`tuning.target_fps`).

## Ligação com a P-10

A P-10 (otimização por compilação: flags, PGO) usa estes relatórios como linha de base. As
flags do processador já viraram os builds `_lume` (P-114, tarefa 11); o PGO fica para depois,
medido com o mesmo método e os mesmos jogos.
