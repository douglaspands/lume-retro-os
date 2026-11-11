# Pendências que exigem uma change própria

Este arquivo guarda **só o que precisa de uma change exclusiva** para ser resolvido:
mudança de design, capacidade nova, refatoração grande ou trabalho fora do escopo da
change ativa. **Quando o usuário perguntar o que falta, ou antes de propor uma change,
consultar aqui.**

O que **não** entra aqui:

- Correções, investigações e ajustes da change ativa: vão para o `tasks.md` dela
  (`openspec/changes/alpine-retroarch-distro/tasks.md`), que é a fonte de verdade.
- Tarefas já planejadas: continuam no `tasks.md`.

Como usar:

- Cada item tem um **ID estável** (`P-NN`). Não reaproveitar IDs.
- **Estado:** `aberta`, `bloqueada` ou `ideia` (ainda sem decisão de fazer).
- Ao virar change, anotar o nome dela no item; ao concluir, mover para "Concluídas".
- Pendência nova encontrada em qualquer conversa entra aqui **só se** exigir change
  própria, com ID novo, estado e evidência. Caso contrário, vira tarefa no `tasks.md`.

Atualizado em 2026-11-10.

## 1. Changes decididas, esperando para serem propostas

| ID | Estado | Assunto | Descrição |
|---|---|---|---|
| P-09 | aberta | **Internacionalizar o projeto: inglês como idioma do sistema** | Ver "P-09 em detalhe" abaixo |
| P-08 | aberta | **Mecanismo único de rotação de logs** (tarefa 12.3) | Tabela declarativa de políticas (caminho, teto, retenção, ordem de remoção) lida por funções genéricas, valendo também para os logs em RAM (`/var/log/rc.log`, syslog) e para `BOOT/logs/`. Hoje um log novo exige editar quatro lugares. Sem `logrotate` (não há agendador no console). Verificar com os testes de shell atuais sem mudança e com um teste novo que falha se achar um arquivo de log sem política. Fazer depois de resolver o congelamento (tarefa 9.8) |
| P-04 | ideia | **Configuração de fábrica versionada** | Hoje a configuração de fábrica só é copiada para cartões novos, e só o idioma do build é reaplicado em cartões que já têm `retroarch.cfg` (`lang_sync` no `r36os-persist`). Qualquer outro padrão novo (escala, atalhos) fica de fora de quem usa `--update`. **Ideia:** versão da configuração de fábrica em `ROMS/system/etc/` e migração só das chaves que mudaram, sem tocar nas escolhas do usuário. Exige design e spec |
| P-07 | ideia | **Relógio persistente sem RTC com bateria** | O console sobe em 1970-01-02, então `events.log`, métricas e datas de arquivo no cartão não servem para ordenar sessões entre boots. **Ideia:** gravar a hora no desligamento (como o `fake-hwclock`) e usar a data do build como mínimo no boot. É um requisito novo de `boot-runtime` |
| P-20 | ideia | **Escalonamento do clock da CPU pelo jogo** | Hoje a CPU usa `schedutil` (120 a 1008 MHz), que só olha a carga e não conhece o FPS. Em três etapas: (1) **perfil por core e por sistema**: o `logd` já sabe o core pelo `GET_STATUS`, então ao abrir o jogo fixa o `scaling_min_freq` do perfil (NES e Game Boy com mínimo baixo, PSX e arcade com mínimo alto) e ao voltar ao menu restaura o padrão; os valores precisam ser medidos no aparelho (base: `docs/referencia/ga36-emuelec/` e `ROMS/logs/`); (2) **controlador em espaço de usuário** que mede o tempo de CPU da thread principal do RetroArch (`utime`, já no rastreio) e sobe o clock acima de cerca de 85% de um núcleo e desce abaixo de cerca de 50%; (3) **controlador por FPS real**, só se o RetroArch passar a informar o FPS alcançado por fora do processo (o `GET_STATUS` não traz; o FPS de 59,73 do log é o alvo do core), o que exigiria um patch numerado no RetroArch. **Restrição:** a Mali não tem regulador no DTS nem refrigeração térmica (`CONFIG_DEVFREQ_THERMAL` desligado), então a GPU só deve mudar de clock nas fronteiras menu→jogo, sem carga. A hipótese de que a troca de clock da GPU causava o congelamento do GA36 foi refutada (tarefa 9.8), mas isso não prova que escalar no meio do jogo seja seguro. Começar só depois de a 9.8 estar resolvida. Relaciona-se com o P-10 |
| P-21 | ideia | **Layout de cartão único para todos os consoles (trocar de console sem perder a ROMS)** | Hoje o cartão de um console não serve ao outro sem perder a ROMS. Causas, todas nossas: o início da BOOT difere (GA36 em 128 MiB, `VENDOR_BOOT_START` em `image.py`; R36S e VM em 16 MiB, setor 32768), a assinatura de disco difere (`board/<alvo>/disk-id`: GA36 `4c554d32`, R36S `4c554d31`, VM `4c554d33`) e o `flash --update` recusa um cartão com início, tamanho ou assinatura diferentes (`_check` em `flash.py`); a gravação completa recria a tabela e zera o começo da ROMS. **Proposta:** o R36S passa a usar o mesmo layout do GA36 (BOOT em 128 MiB, ROMS logo depois, a mesma assinatura e as mesmas partições; o `idbloader` no setor 64 e o `u-boot.itb` no setor 16384 cabem na área de 128 MiB). Trocar de console vira `flash <alvo> --update`: só a área de boot (128 MiB) e a BOOT (1 GiB) são regravadas e a ROMS fica intacta; o cartão passa a iniciar só no console da última gravação. **Evidência (2026-11-10):** mapa dos setores ocupados da área de fábrica do GA36: o boot0 ocupa os setores 16 a 277, e o espaço de 8 MiB a 18,6 MiB está livre. **Decidir antes das tarefas 10.5 e 10.6** (U-Boot e `r36s.img`), porque o R36S ainda não tem imagem e mudar depois quebra a compatibilidade dos cartões. Exige: `boot_start` e assinatura comuns, ajuste do `_check` do `flash`, testes de layout e de `--update` entre alvos e o contrato de cartão no spec `system-image`. Os *save states* podem não ser compatíveis entre armv7 e aarch64 (os saves `.srm` costumam ser). **Variante, não viável hoje: um cartão que inicia os dois sem regravar.** O boot0 do GA36 (setores 16 a 277) cobre o setor 64, onde o RK3326 exige o `idbloader`. Só seria possível com o U-Boot mainline do GA36 (P-19) com um SPL de no máximo ~24 KiB e o resto em outro setor, e com um `SYSTEM` de cada arquitetura na BOOT (cerca de 280 MB cada, cabem no 1 GiB) e o initramfs escolhendo o certo. Relaciona-se com o P-16 (segundo slot do R36S) e o P-19 |

### P-09 em detalhe

**Princípio.** O inglês é o idioma do projeto. O português (e o espanhol) existe só como
tradução da interface, escolhida pelo usuário: o menu do RetroArch (`user_language`, do
`--lang` do build ou do menu) e as mensagens de tela do sistema que seguem esse idioma
(`ui_lang` em `lib.sh`). O padrão do build já é inglês (`--lang en`).

**Decisões confirmadas pelo usuário em 2026-11-10:**

1. A documentação e o OpenSpec também passam para inglês. Ao concluir a change, atualizar
   a regra em `CLAUDE.md`, `AGENTS.md` e `GEMINI.md`, que hoje mantém `docs/` e
   `README.md` em português.
2. Os arquivos em português são renomeados, inclusive o `LEIA-ME.txt` do cartão (muda o
   contrato de pastas do spec `game-library` e os testes que o conferem).
3. As changes arquivadas também são traduzidas ("quero tudo isso"). Se a intenção era
   mantê-las como registro histórico, ajustar aqui antes de propor a change.

**Escopo:**

| Área | O que traduzir | Observação |
|---|---|---|
| Scripts e testes | comentários, mensagens, rótulos dos `check` e identificadores em português, em `src/`, `rootfs/`, `initramfs/`, `tests/`, `scripts/` (exceto o guardrail) | os textos `pt` e `es` de `ui_lang` e da tela de falha do `session` são traduções de propósito e ficam |
| Configuração e pacotes | comentários dos `APKBUILD`, `*.cfg`, `*.conf`, `packages.txt`, `board/**` (DTS, `u-boot.config`) | |
| Documentação | `README.md` e `docs/*.md` (`VM`, `LOGS`, `FRONTEND`, `CATALOG`, este arquivo) | `docs/referencia/` fica: são dados medidos copiados do projeto anterior |
| OpenSpec | `proposal`, `design`, `specs` e `tasks` da change ativa, os specs principais em `openspec/specs/` e as changes arquivadas | |
| Nomes em português | `docs/PENDENCIAS.md` → `docs/PENDING.md`; `src/r36os/leiame.py` → `readme.py`; o guia no cartão `LEIA-ME.txt` → `README.txt` (texto gerado no idioma do build) | |
| Mensagens de commit | passam para inglês | |
| Fora do projeto | o guardrail (`scripts/guardrail.py`) e o bloco gerado dos arquivos de instruções vêm do `ctx` e seriam sobrescritos; a conversa com o usuário continua em português | |

**Tamanho (medido em 2026-11-10):** cerca de 75 arquivos de código e configuração, o
`README.md`, 5 documentos em `docs/` e 11 artefatos do OpenSpec da change ativa e dos
specs principais têm texto em português, fora as changes arquivadas.

**Como verificar.** Um teste novo varre os arquivos do projeto e falha se achar letras
acentuadas fora de uma lista de exceções (os textos de tradução `pt`/`es` e
`docs/referencia/`). Isso evita a regressão e dispensa a revisão manual.

**Ordem sugerida.** (1) scripts e testes; (2) configuração e pacotes; (3) documentação e
OpenSpec; (4) renomeações e o `LEIA-ME.txt`. Cada etapa só fecha com os testes unitários e
as suítes em busybox passando.

## 2. Fora do escopo da change atual (próximas changes)

Vêm da seção "Fora do escopo" da `proposal.md` e do `design.md`.

| ID | Estado | Assunto | Observação |
|---|---|---|---|
| P-10 | ideia | Otimização do A33 | Flags Cortex-A7 nos pacotes (hoje só o `pcsx-rearmed` tem `-marm -mfpu=neon`), `snes9x2005_plus` no armv7, governor, latência de áudio e curva de bateria medidas. Base: `docs/referencia/ga36-emuelec/` e os logs de `ROMS/logs/`. O escalonamento do clock pelo jogo é o P-20 |
| P-11 | ideia | Frequências acima do mainline no GA36 | O `sun8i-a33.dtsi` vai até 1008 MHz @ 1,20 V; o firmware de fábrica vai a 1200 MHz @ 1,32 V (níveis 1104, 1200, 1344 e 1536 MHz). Overclock |
| P-12 | ideia | Splash de boot | Hoje o boot é verboso, sem splash |
| P-13 | ideia | Tema visual próprio (Lume) e Lume Console | Frontend próprio. O tema no XMB (ícones, fonte, wallpaper) foi descartado nesta change |
| P-14 | ideia | Atualização A/B | Hoje a atualização é `r36os flash --update` pelo PC |
| P-15 | ideia | Wi-Fi e Bluetooth | Se chegar, revisar o `GET_STATUS` por UDP local usado pelo `logd` e o Core Updater (hoje oculto: os cores do buildbot são glibc e não rodam no musl) |
| P-16 | ideia | Hardware adicional | Segundo slot de cartão do R36S, outras revisões do R36S, GA36 com A23 |
| P-17 | ideia | Miniaturas e wallpaper por sistema | |
| P-23 | ideia | **Clock da DRAM: confirmar, monitorar e decidir se varia por uso** | Pedido do usuário (2026-11-10). Análise inicial em `docs/referencia/a33-clocks.md` (seção 4.3): o `dram` de 270 MHz do Linux é o controlador (metade da memória), o Linux calcula a memória em 540 MHz (`pll-ddr1` 1080 / 2) e o FEX de fábrica pede `dram_clk = 552`; a diferença provavelmente é o sigma-delta do PLL, que o driver `ccu_mult` não lê. A fábrica variava a DRAM de 168 a 552 MHz (devfreq `dsm` do kernel do fabricante); o mainline não tem devfreq de DRAM para o A33, então a nossa fica fixa perto do máximo. **Etapas:** (1) **confirmar** o clock real lendo no aparelho `PLL_DDR1_CTRL_REG` (0x01C2004C), `PLL_DDR1_PAT_CTRL_REG0/1` (0x01C202AC, 0x01C202B0) e `DRAM_CFG_REG` (0x01C200F4) com o `r36os-devmem`, e calcular o clock efetivo; (2) **monitorar**: registrar esses valores no `hw/boot-<n>.txt` e o clock da DRAM e do MBUS por amostra nas métricas, junto do core em uso, para ver se a memória está na frequência certa em cada core; (3) **medir** se a banda de memória limita algum core (PSX, arcade, SNES com Super FX) e quanto a DRAM fixa custa de bateria em repouso; (4) **decidir** se vale um mecanismo de variação (devfreq de DRAM para o A33 não existe no mainline: seria driver novo, MBUS/MDFS) ou se o valor fixo basta. Mudar o clock da DRAM é arriscado (tempos de `dram_tpr*` calculados para 552 MHz): só com medição e teste longo. Relaciona-se com o P-10 e o P-20 |
| P-24 | ideia | **Catálogo completo de cores: tudo que o A33 roda bem, com o core otimizado para ele** | Pedido do usuário (2026-11-11). Hoje a imagem leva 11 cores para 9 sistemas (`rootfs/packages.txt`, `systems.json`: NES, SNES, Master System, Mega Drive, Game Boy, GBC, GBA, arcade, PlayStation). **Critérios para entrar:** (a) roda em velocidade cheia no GA36 a no máximo 1008 MHz (sem depender do overclock do P-11), medido no aparelho com o rastreio e as métricas (CPU por núcleo, temperatura, quadros); (b) o core é o mais otimizado para ARMv7/Cortex-A7 entre as opções (recompilador dinâmico ARM, NEON, versões "lite" ou antigas mais leves); (c) compila para musl (Alpine ou `aports/` local; os cores do buildbot são glibc); (d) licença compatível com a distribuição (vários cores são "não comercial": registrar). **Candidatos a avaliar** (lista inicial, nada decidido): PC Engine/TurboGrafx e PC Engine CD (`beetle-pce-fast`), Neo Geo Pocket (`race` ou `beetle-ngp`), WonderSwan (`beetle-wswan`), Atari 2600 (`stella2014`), Atari 7800 (`prosystem`), Atari Lynx (`handy`), Sega CD e 32X (`picodrive`, que já está na imagem, com recompilador ARM no 32X), Game Gear e SG-1000 (já cobertos pelo `genesis-plus-gx`/`picodrive`, falta o sistema no catálogo), MSX e ColecoVision (`bluemsx` ou `fmsx`), Pokémon Mini (`pokemini`), Vectrex (`vecx`), Intellivision (`freeintv`), Virtual Boy (`beetle-vb`, no limite), ZX Spectrum (`fuse`), Amstrad CPC (`cap32`), Commodore 64 (`vice`), DOS (`dosbox-pure`, no limite), ScummVM, Doom (`prboom`) e Quake (`tyrquake`). **Referência de fábrica:** `docs/referencia/ga36-emuelec/cores-fabrica.md` traz o core padrão e os alternativos de todos os ~100 sistemas do EmuELEC de fábrica e a comparação com os nossos 9. **Comparar o padrão de fábrica com o nosso no aparelho** (mesma ROM, 5 minutos, CPU por núcleo, temperatura e quadros perdidos, pelas métricas do `logd`), começando pelos quatro sistemas em que eles diferem: NES (fábrica `nestopia`, nós `fceumm`), SNES (fábrica `snes9x`, com `snes9x2005_plus_a33` como padrão pelo `emuelec.conf`; nós `snes9x2010`), Master System (fábrica `gearsystem`, nós `genesis_plus_gx`) e GBA (fábrica `mgba`, nós `gpsp`). No arcade, a fábrica usava o FBNeo *standalone* (`FbneoSA`), fora do RetroArch: comparar com o `fbneo` e o `mame2003_plus` libretro. Ficar com o core de menor uso de CPU que roda sem perder quadros e sem erro visível; registrar o resultado na tabela. O estudo de flags e PGO do `snes9x2005_plus` para o A33 (`docs/referencia/ga36-emuelec/cores/`, P-10) vale como modelo de avaliação. Provavelmente **fora** (pesados demais para o A33): Nintendo 64, PSP, Dreamcast, Saturn, NDS. **Cada core novo exige:** aport com flags de Cortex-A7 (`-mcpu=cortex-a7 -mfpu=neon-vfpv4`, padrão do P-10), entrada em `systems.json` (extensões, BIOS em `/storage/bios`), atualização dos testes de catálogo (`test_catalog.py`, `test_playlists.sh`), autoconfiguração do controle e um teste no aparelho de 5 minutos por sistema. Relaciona-se com o P-10 (otimização), o P-20 (clock por jogo, os perfis por core) e o P-23 (banda de memória por core) |
| P-25 | ideia | **Painel do GA36 a 60 Hz** | Medido em 2026-11-11 (imagem `20261110-235619`): o modo do JD9366 (patch 0005, timing FEX de fábrica) é 30 MHz / (1040 × 518) = 55,69 Hz. Com o `video_refresh_rate` real (tarefa 9.12) o RetroArch regula pelo áudio e descarta ~4 quadros por segundo nos jogos de 60 fps (vídeo menos fluido). Um painel a ~60 Hz deixaria o vsync e o áudio sincronizados. Caminhos: subir o pixel clock para ~32,3 MHz ou reduzir os porches (`htotal`/`vtotal`); conferir o que o PLL do vídeo do A33 consegue gerar, o limite do JD9366 e a taxa da via DSI; testar no aparelho os dois painéis (tremor, faixas, imagem que não sobe). Ao mudar, atualizar o `video_refresh_rate` do `retroarch-ga36.cfg` (o teste `test_ga36_refresh_rate_matches_panel_mode` acusa a divergência) |
| P-22 | ideia | **Imagem de debug separada da imagem final** | Pedido do usuário (2026-11-10). Hoje uma imagem só carrega as ferramentas de diagnóstico (`usbutils`, `pciutils`, `alsa-utils`, `r36os-devmem`, debugfs, rastreio detalhado do `logd`, `hwinfo` completo). **Ideia:** um perfil de build `debug` (ex.: `r36os build ga36 --debug`) com as ferramentas, o rastreio e o retrato completo do hardware, e uma imagem final enxuta, só com o necessário para jogar e com o `logd` reduzido a eventos e métricas. Exige: lista de pacotes por perfil (`rootfs/packages-debug.txt`), nome do perfil na versão da imagem (`os-release`) e nos logs, testes que garantam que a imagem final não leva as ferramentas, e decidir se o kernel de debug muda (debugfs, `CONFIG_DYNAMIC_DEBUG`) |

## 3. Adiadas desta change (tarefas do grupo 12)

| ID | Estado | Assunto | Observação |
|---|---|---|---|
| P-18 | aberta | Reativar o PSP (PPSSPP) | Tarefa 12.1: `aports/libretro-ppsspp` pronto, mas com `arch=""`. Avaliar o desempenho na Mali-400 (só GLES2) |
| P-19 | bloqueada | U-Boot mainline no GA36 | Tarefa 12.2: o build compila, mas o aparelho não deu sinal de vida. Hoje o GA36 usa o boot0 e o U-Boot do fabricante. Diagnosticar com FEL (`sunxi-fel`) ou com LEDs |

## 4. Movidas para o `tasks.md` da change ativa

Itens que apareceram aqui no início, mas são correções da change atual e não exigem change
própria. Os IDs `P-01` a `P-03`, `P-05` e `P-06` não são reaproveitados.

| ID antigo | Assunto | Onde está agora |
|---|---|---|
| P-01 | GA36 congela ao abrir qualquer jogo | tarefa 9.8 |
| P-02 | Leitor USB 14cd:125d corrompe gravações pequenas | tarefa 11.5 |
| P-03 | Menu pequeno na tela do GA36 | tarefa 9.9 (e 7.5 na VM) |
| P-05 | Mali-400 sem regulador e sem refrigeração no DTS | tarefa 9.10 |
| P-06 | Mensagens de erro recorrentes no boot | tarefa 9.11 |

## 5. Concluídas

| O que | Onde |
|---|---|
| Swap comprimido em ZRAM | change arquivada `openspec/changes/archive/2026-11-10-zram-swap/` |
| `r36os flash --eject` | commit `f10d652` |
| Escala do menu e idioma ajustáveis pelo menu do RetroArch | commit `678855d` |
