# Design

## Context

Motivação em `proposal.md`. Estado de hoje, conferido no código e no GA36 (2026-11-19):

- **Camadas do RetroArch:** `retroarch-lume.cfg` (fixo, todos), `retroarch-<board>.cfg` (fixo por
  console, `video_threaded=true` e o refresh real do painel), `factory/retroarch/retroarch.cfg`
  (padrões do usuário, copiado para o cartão só no primeiro boot) e `retroarch-core.keys`
  (`<core> chave=valor` e `*`, valem só na execução do core, o valor do usuário volta no fim; hoje
  só `pcsx_rearmed video_threaded=false`). Quem aplica é `frontends/retroarch` (`merge_fixed`,
  `LUME_RESTORE`), e o self-test usa `/run/lume/retroarch-extra.cfg` para chaves de uma execução.
- **Opções de core:** nenhuma de fábrica; cada core roda com o padrão do upstream. A pasta de
  configuração do RetroArch (`~/.config/retroarch/`) vive na RAM e é espelhada no cartão
  (`ROMS/system/retroarch/`) pelo `lume-persist`.
- **Ambiente dos jogos:** o `lume-run` lança o jogo por `clone3` + `exec`, herdando o próprio
  ambiente. Há `TZ=:/usr/share/zoneinfo/<zona>` no ambiente do launcher e nenhuma variável de
  idioma. O idioma do launcher está em `ROMS/system/lume/settings.toml` (`en`, `pt`, `es`), lido
  por `lume_core::gametext::language`, e o `lume-ui` grava o `user_language` correspondente no
  RetroArch.
- **Rede USB:** servidor `dropbear`, sem `scp` nem `sftp-server` no console.
- **Medição:** o `lume-logd` já registra quadros mostrados (fdinfo do DRM), FPS do core
  (`GET_STATUS`), CPU por núcleo, clock e temperatura; o `lume dev run` executa roteiros
  (`tests/device/scripts/*.toml`) que abrem o jogo N de um sistema sem nomeá-lo.
- **Catálogo:** `aports/lume-games/files/usr/share/lume/systems.json` (esquema 3), validado no
  build; arcade não pode ter `core_by_arch`.
- **Jogos de exemplo:** `var/roms_default/` (fora do git) é reservado à distribuição final: só
  jogos livres, um exemplo por sistema. Os testes desta change usam outro conjunto (D10).

## Goals / Non-Goals

**Goals:**
- Cada core e o LÖVE no melhor ponto que a configuração alcança em cada console, provado por
  medição A/B contra uma linha de base gravada.
- Padrões novos chegando a cartões existentes sem tocar no que o usuário escolheu.
- Medições repetíveis: mesma carga (mesmo jogo do conjunto de teste) em datas diferentes.

**Non-Goals:**
- Flags de compilação, PGO ou troca de core por desempenho (P-10, P-24); o `mednafen_pce_fast`
  entra com o build padrão do upstream.
- Run-ahead, shaders e filtros (custam CPU/GPU, contra a regra de bateria primeiro; shaders são a
  P-89).
- Completar o `var/roms_default/` com jogos livres de todos os sistemas: é trabalho da
  distribuição; esta change só lista o que falta para os sistemas novos (tarefa 9.2).
- Um painel de configurações no launcher para essas opções (P-91).

## Decisions

### D1. Três destinos para um ajuste, pelo tipo
| Tipo | Destino | Quem muda |
|---|---|---|
| Chave do RetroArch de desempenho ou estabilidade (ex.: `video_threaded`, `video_max_swapchain_images`, `audio_latency`) | `retroarch-core.keys`, por core e por console | só a distro; vale na execução e o valor do usuário volta |
| Opção do core (ex.: síntese do YM2612, dynarec, taxa do som) | `.opt` de fábrica por core | o usuário, no Quick Menu > Opções do core |
| Preferência global do RetroArch (analógico como direcional) | `factory/retroarch/retroarch.cfg` | o usuário, no menu |

*Alternativas:* overrides de core do RetroArch (`config/<core>/<core>.cfg`) para as chaves de
desempenho, recusados porque o usuário poderia salvá-los por cima e porque o `game-runners` já
manda o launcher vencer overrides; tudo como chave fixa, recusado porque as opções do core são
preferência do usuário (paleta, aspecto, som) além de desempenho.

### D2. Dimensão do console no `retroarch-core.keys`
O primeiro campo passa a aceitar `<core>`, `*`, `<board>:<core>` e `<board>:*`. Ordem de
aplicação (a última vence): `*`, `<core>`, `<board>:*`, `<board>:<core>`. O `<board>` é o de
`/etc/lume/board` (`ga36`, `r36s`, `vm`). A leitura continua no `frontends/retroarch`, com as
mesmas regras de nome de chave; uma linha com console desconhecido é ignorada. O formato é
congelado por teste antes dos consumidores (tarefa 1.1).

### D3. Opções de core de fábrica e semeadura
Arquivos em `/usr/share/lume/factory/retroarch/config/<Nome do core>/<Nome do core>.opt` (o nome
da pasta é o `corename` do `.info` do core, conferido por teste contra os `.info` instalados). O
`frontends/retroarch`, a cada início, copia para `~/.config/retroarch/config/...` cada opção de
fábrica que falte no arquivo do usuário (linha a linha, por chave), sem mudar as que existem. O
mesmo `merge` de chaves faltantes vale para o `retroarch.cfg` do usuário com o
`factory/retroarch/retroarch.cfg` (D4). As opções de core são iguais nos dois consoles; se a
medição pedir um valor diferente por console para uma opção, ele vai como chave do core no D2
quando o RetroArch tiver chave equivalente, e senão fica registrado como pendência (o `.opt` é
um arquivo só no cartão compartilhado).

*Alternativa:* semear no `lume-persist` no boot. Recusada: o frontend já faz o merge das chaves
fixas a cada início e conhece o caminho do usuário; o boot não ganha trabalho novo (prioridade do
boot rápido).

### D4. Analógico como direcional
`input_player1_analog_dpad_mode` até `input_player4_analog_dpad_mode` = `"1"` (analógico
esquerdo) no `factory/retroarch/retroarch.cfg`, chegando a cartões existentes pela semeadura do
D3. O PS1 com DualShock: o `pcsx_rearmed` declara o analógico pelo tipo de controle; a chave
`pcsx_rearmed input_player1_analog_dpad_mode=0` não serve, porque desligaria também no controle
padrão. A tarefa 1.3 confere no aparelho o comportamento com DualShock e, se o analógico
duplicar o direcional, usa o remap de core do RetroArch (`input_libretro_device_p1` analógico
desliga o modo) em vez de mexer na chave global.

### D5. Idioma, fuso e ambiente do runner no `lume-run`
Antes do `clone3`, o `lume-run` monta o vetor de ambiente do jogo: o ambiente herdado, menos
`LANG`, `LANGUAGE`, `LC_*` e `TZ`, mais
- `LANG` e `LANGUAGE` do `settings.toml` (`en` → `en_US.UTF-8` e `en_US:en`, `pt` →
  `pt_BR.UTF-8` e `pt_BR:pt`, `es` → `es_ES.UTF-8` e `es_ES:es`), lidos a cada jogo;
- `TZ=:<zoneinfo>/<zona de /etc/timezone>`, como o `lume-logd` faz, só se o arquivo de zona
  existir;
- as variáveis do runner (`[runner.env]` no TOML), por último.
O filho usa `execve` com esse vetor (montado antes do fork, nada é alocado no filho). Fonte do
idioma: o `settings.toml` do launcher, porque é o idioma que o usuário escolhe na interface e que
o `lume-ui` copia para o RetroArch; o `ui_lang` do `lib.sh` (que lê o RetroArch) continua para as
mensagens dos scripts. Sem `LC_ALL` e sem o pacote `musl-locales`: o musl continua com mensagens
em inglês e ponto decimal `.`, então os logs e os scripts que leem saída de comandos não mudam.

### D6. Medição A/B
Por core e por console: um roteiro `lume dev run` abre o jogo N do sistema (conjunto de teste,
D10), espera 30 s e mede 120 s com o perfil normal do governor. Variantes:
- chaves do RetroArch pelo `/run/lume/retroarch-extra.cfg` (já lido pelo frontend, última camada);
- opções do core escrevendo o `.opt` do usuário antes do jogo e devolvendo o original depois.
Ordem A, B, A para cada variante (a diferença entre os dois A é o ruído). Métricas: quadros
mostrados por segundo (fdinfo do DRM), velocidade do core (`GET_STATUS`), falhas de áudio
(contagem de underruns do ALSA; a tarefa 5.1 fixa a fonte entre o `status` do
`/proc/asound/card*/pcm*p/sub0` e o log do RetroArch), clock médio, CPU por núcleo e temperatura,
tiradas do `lume-logd`. Um script em `tests/device/` agrega em `docs/tuning/<console>.md` uma
linha por core e variante, sem jogo nem caminho.

### D7. Candidatos por core (nomes de chave conferidos no commit fixado de cada core antes da medição)
| Core | Candidatos |
|---|---|
| todos (RetroArch) | `video_threaded`, `video_max_swapchain_images` 2/3, `video_frame_delay_auto`, `audio_latency`, `audio_resampler_quality`, `input_poll_type_behavior` |
| fceumm / nestopia | qualidade do som, overscan |
| snes9x2005_plus | frameskip, overclock do Super FX, filtro de áudio |
| genesis_plus_gx | YM2612 (MAME contra Nuked), filtro NTSC, filtro de áudio |
| picodrive | dynarec, taxa do som, renderer |
| gambatte | `mix_frames` |
| gpsp | dynarec, BIOS, frameskip |
| fbneo / fbalpha2012_* | `allow-depth-32`, taxa do som, interpolações, frameskip |
| pcsx_rearmed | dynarec, `gpu_thread_rendering` (com `video_threaded=false`), enhancement, SPU (reverb, interpolação), frameskip |
| mednafen_pce_fast | taxa do som, CD com cache em RAM |
| love (runner) | `mesa_glthread`, variáveis do SDL do KMSDRM, classe de energia do sistema `love` |

### D8. TurboGrafx e CPS-3 no catálogo
- `pcengine` ("TurboGrafx-16", sigla `TG16`) e `pcenginecd` ("TurboGrafx-CD", `TGCD`), core
  `mednafen_pce_fast`, extensões tiradas do `.info` do core e conferidas por teste; a BIOS
  `syscard3.pce` obrigatória no CD. Ids iguais aos usados por EmulationStation/ArkOS, para quem
  já tem as pastas.
- `cps3` ("CPS-3", `CPS3`), core `fbneo`, `romset` "FBNeo (a versão do core da imagem)", sem
  `core_by_arch` (regra do arcade).
- Aport `libretro-mednafen-pce-fast` como os outros locais: commit fixo, `make` padrão do
  upstream, os três arches; nenhuma flag de CPU (a P-10 continua adiada).

### D9. `openssh-sftp-server` e `rsync`
Pacotes do Alpine em `rootfs/packages.txt`. O `dropbear` procura o `sftp-server` em
`/usr/lib/ssh/sftp-server` (o caminho que ele tentou no GA36) e o `scp` moderno do PC usa sftp;
o `rsync` roda pela sessão SSH. Nenhum serviço nem script no boot.

### D10. Conjunto de teste padrão em `var/roms_test/`
`var/roms_test/` (fora do git, como `var/`) tem `roms/<sistema>/` com `gamelist.xml` e `images/`, e
`bios/` com as BIOS que esses jogos pedem. Montado nesta sessão a partir dos backups do usuário;
prioriza arcade, CPS-1, CPS-2 e Neo Geo. Comando novo `lume dev roms push` (console no cabo):
`rsync` pela rede USB quando o console tem `rsync` (D9), senão `tar` pelo SSH; confere SHA256
dos arquivos copiados; nunca apaga nem sobrescreve; funde o `gamelist.xml` só com as entradas
que faltam, pela mesma regra do índice de jogos. A saída só traz contagens por sistema.

### D11. Listas corrompidas de 2026-11-19
Seis `gamelist.xml` do GA36 apareceram com bytes aleatórios do tamanho de um XML (gravados entre
13:39 e 15:40, cópias `.bak`/`.pre-merge` íntegras). Duas hipóteses: o leitor USB do PC (já
conhecido por corromper escritas pequenas), se o cartão passou por ele nesse horário; ou a
gravação do índice ou do launcher (escrita atômica que não chegou ao cartão antes de um corte).
A tarefa 9.1 decide pela resposta do usuário e pelo `events.log` desse boot; se for do sistema,
a correção entra nesta change.

**Causa (9.1, 2026-11-19):** nenhuma das duas. O GA36 suspendeu no boot 204 (04:41 UTC) e só
acordou às 19:39; nesse meio o mesmo cartão iniciou no R36S (boots 205 a 214, 14:28 a 16:04
-03), que gravou as listas. Ao acordar, o kernel do GA36 seguiu com a tabela de alocação do
exFAT guardada na RAM antes da troca e gravou (logs, listas) em clusters que o R36S tinha dado a
outros arquivos: as listas ficaram com o tamanho certo e conteúdo alheio, e o `events.log` perdeu
os boots 207 a 214 e o começo do 205 sob as linhas do 204. O kernel não percebe a troca: é o
mesmo cartão (mesmo CID). Com um cartão para dois consoles, isso se repete.

**Correção (escolha do usuário, tarefa 9.3):** antes de suspender, o `lume-sleep` guarda o
contador `.boot` da `ROMS`; ao acordar, antes de liberar qualquer gravação, relê o contador do
cartão sem o cache de página; se mudou, reinicia na hora sem gravar nada (sem `sync`, que
gravaria a tabela velha), e o boot seguinte registra o motivo. Ponto a resolver na 9.3: o
`freeze` descongela os processos antes do `lume-sleep` rodar, então quem grava na `ROMS` (o
`lume-logd`, o `lume-persist`, o launcher) precisa esperar o "acordou e o cartão confere" do
`lume-sleep` pelo protocolo de clientes do sono, ou a conferência precisa vir antes do
descongelamento.

## Risks / Trade-offs

- [Medição com ruído maior que o ganho] → ordem A, B, A e o critério do spec (melhora acima da
  variação entre os dois A); sem ganho claro, nada muda.
- [Chave boa num console, ruim no outro] → toda chave aceita tem dimensão de console (D2); o
  R36S só herda um valor do GA36 depois de medido.
- [Opção de core que precisa ser diferente por console] → só via chave do RetroArch (D3); senão
  fica o valor bom para os dois ou pendência.
- [Semeadura de padrões apagando escolha do usuário] → merge só de chaves ausentes, com teste de
  unidade (chave existente nunca muda).
- [LANG mudando saída que algum script lê] → só no ambiente dos jogos, não no do sistema; musl sem
  `musl-locales` não traduz nada.
- [`mednafen_pce_fast` pesado no A33] → medido na linha de base; se não tiver velocidade cheia no
  GA36, fica registrado e a troca de core vai para a P-24.
- [Romsets de arcade da versão errada] → o conjunto de teste só leva romsets que abriram no core
  padrão da pasta (tarefa 4.2).

## Migration Plan

Imagem nova por `lume push` (boot conferido) em cada console. Cartões existentes recebem os
padrões novos pela semeadura (D3), as pastas novas pelo boot e as opções de core no primeiro jogo
de cada core. Volta atrás: a imagem anterior; as chaves semeadas ficam no cartão e são inofensivas
para a imagem antiga (são chaves e opções que o RetroArch já conhece).

## Open Questions

- Ganhos reais de cada candidato do D7: saem das medições; o spec já diz como decidir.
- ~~Se o cartão passou pelo leitor USB do PC na tarde de 2026-11-19 (D11)~~: resolvido pelos
  logs (troca do cartão com o GA36 suspenso).
