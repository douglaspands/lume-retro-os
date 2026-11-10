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
