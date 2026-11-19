# Tasks

## Grafo de execução

Regras do projeto em `openspec/config.yaml` (`rules.tasks`, `operations.apply`).

**Recursos exclusivos:** `CPU` (um build pesado por vez, sob a proteção de calor),
`ARCH:armv7`, `ARCH:aarch64` e `ARCH:x86_64` (um `lume pkg` por arquitetura), `GA36`, `R36S`,
`USUARIO` (ação física ou olho humano), `MERGE` (um merge por vez, seguido de `cargo test` do
`lume/`, `pytest tests/unit` e das suítes de shell). Nenhum nó `TREE`.

**Outras changes ativas no branch:** `hide-clock`, `launcher-adjustments`, `lume-shaders`,
`r36s-usb-proof`. Dividem `CPU`, `ARCH:*`, `GA36`, `R36S`, `USUARIO` e `MERGE`; as janelas J1 e
J2 podem levar provas pendentes delas (`hide-clock` 2.1, `lume-shaders` 2.2,
`r36s-usb-proof` 1.x), anotadas com a change.

**Executores:** `AG` = subagente em `out/worktrees/<nó>` (código e teste de unidade); `PR` =
sessão principal (merge, build, aparelho, arquivos privados do usuário). Os jogos do usuário só
são tocados pela sessão principal (nó 4.2), nunca por subagente.

| Nó | Depende de | Recursos | Executor | Modelo | Onda | Janela |
|---|---|---|---|---|---|---|
| 1.1 | — | — | AG | sonnet | 0 | |
| 2.1 | — | — | AG | sonnet | 0 | |
| 3.1 | — | ARCH:armv7, ARCH:aarch64, ARCH:x86_64 | AG+PR | opus | 0 | |
| 4.1 | — | — | AG | sonnet | 0 | J1, J2 |
| 4.2 | — | USUARIO | PR | — | 0 | |
| 5.1 | — | — | AG | opus | 0 | |
| 9.1 | — | USUARIO | PR | — | 0 | |
| 1.2 | 1.1 | — | AG | opus | 1 | J1, J2 |
| 2.2 | 2.1 | — | AG | opus | 1 | J1, J2 |
| 3.2 | 3.1 | — | AG | sonnet | 1 | J1, J2 |
| 4.3 | 4.2 | — | AG | opus | 1 | J1, J2 |
| 1.3 | 1.2 | — | AG | sonnet | 2 | J1, J2 |
| 2.3 | 2.2 | — | AG | sonnet | 2 | J1, J2 |
| 9.2 | 3.2 | — | AG | sonnet | 2 | |
| 9.3 | 9.1 | — | AG | opus | 1 | J1, J2 |
| 6.1 | 1.3, 2.3, 3.2, 4.1, 4.3, 5.1, 9.3 | CPU, ARCH:armv7, ARCH:aarch64, ARCH:x86_64 | PR | — | 3 | |
| 6.2 | 6.1 | GA36, USUARIO | PR | — | 4 | J1 |
| 7.1 | 6.2 | GA36 | PR | — | 5 | J1 |
| 7.2 | 7.1 | GA36 | PR | — | 6 | J1 |
| 7.3 | 7.1 | GA36 | PR | — | 6 | J1 |
| 7.4 | 7.1 | GA36 | PR | — | 6 | J1 |
| 6.3 | 6.1 | R36S, USUARIO | PR | — | 4 | J2 |
| 7.5 | 6.3, 7.2, 7.3, 7.4 | R36S | PR | — | 7 | J2 |
| 8.1 | 7.2, 7.3, 7.4, 7.5 | — | AG | sonnet | 8 | |
| 8.2 | 8.1 | CPU, ARCH:armv7, ARCH:aarch64, GA36, R36S, USUARIO | PR | — | 9 | J3 |

Modelos: aprovados pelo usuário em 2026-11-19 (onda 0, sem trocas; onda 0 em paralelo).

Os nós 7.x são da sessão principal porque medem no aparelho; dentro de uma janela, 7.2, 7.3 e
7.4 rodam em sequência (mesmo `GA36`), na ordem da tabela.

**Trilhas e caminho crítico:**

```
 1.1 --> 1.2 --> 1.3 ----------------------------+
 2.1 --> 2.2 --> 2.3 ----------------------------+
 3.1 --> 3.2 --------------------------+---------+
                                       +--> 9.2  |
 4.1 ------------------------------------------+-+--> 6.1 --+--> 6.2 --> 7.1 --> 7.2/7.3/7.4 --+
 4.2 --> 4.3 ----------------------------------+            |                                  |
 5.1 ------------------------------------------+            +--> 6.3 ------------------------> 7.5 --> 8.1 --> 8.2
 9.1 --> 9.3 (conferência do cartão ao acordar) ---------------------------+--> 6.1

 caminho crítico: 3.1 -> 3.2 -> 6.1 -> 6.2 -> 7.1 -> 7.2..7.4 -> 7.5 -> 8.1 -> 8.2
```

**Ondas:**
- Onda 0: 1.1, 2.1, 3.1, 4.1, 5.1 (AG em paralelo); 4.2 e 9.1 (PR).
- Onda 1: 1.2, 2.2, 3.2, 4.3, 9.3.
- Onda 2: 1.3, 2.3, 9.2.
- Onda 3: 6.1 (build único da imagem com todo o código).
- Ondas 4 a 7: janelas J1 (GA36) e J2 (R36S): provas funcionais, linha de base e A/B.
- Onda 8: 8.1 (gravar os vencedores).
- Onda 9: 8.2 (segundo build e conferência nos dois consoles, J3).

**Janelas de aparelho:**
- **J1 (GA36 no cabo):** 6.2 (analógico, idioma, TurboGrafx, CPS-3 se houver romset, `scp`,
  `sftp`, `rsync`, `lume dev roms push`), depois 7.1 a 7.4 (linha de base e A/B, sem o usuário,
  com o console na mesa e carregador ligado). O usuário: olhar o analógico e o probe do LÖVE.
- **J2 (R36S no cabo):** 6.3 e 7.5, como na J1.
- **J3 (os dois, um por vez):** 8.2.

## 1. Chaves por core e por console, padrões de fábrica

- [x] 1.1 Formato do `retroarch-core.keys` com a dimensão do console (D2): o `frontends/retroarch` aceita `*`, `<core>`, `<board>:*` e `<board>:<core>`, nessa ordem de prioridade, com o board de `/etc/lume/board`; linha de console desconhecido é ignorada; o cabeçalho do arquivo documenta o formato. Verificação: testes novos em `tests/unit/test_retroarch_cfg.py` (chave só do GA36 vence a de todos no GA36 e não vale no R36S; valor do usuário volta no fim; `pcsx_rearmed video_threaded=false` continua valendo nos dois).
- [ ] 1.2 Semeadura de padrões em cartões existentes (D3): a cada início, o `frontends/retroarch` acrescenta ao `retroarch.cfg` do usuário as chaves do `factory/retroarch/retroarch.cfg` que faltam, e copia para `~/.config/retroarch/config/<core>/<core>.opt` as opções de fábrica que faltam (por chave), sem mudar nenhuma existente; o `.opt` de fábrica mora em `/usr/share/lume/factory/retroarch/config/`. Verificação: testes de unidade (chave ausente entra; chave do usuário nunca muda; `.opt` inexistente nasce igual ao de fábrica; opção do usuário fica; nomes das pastas iguais ao `corename` dos `.info` instalados).
- [ ] 1.3 Analógico como direcional (D4): `input_player1..4_analog_dpad_mode = "1"` no `factory/retroarch/retroarch.cfg`, comentado. Verificação: teste de unidade das quatro chaves na fábrica e da semeadura num cartão antigo; no aparelho (J1, J2), o analógico move num jogo de NES e num de Mega Drive (jogador 2 com controle USB, se houver), e o PS1 com DualShock recebe o analógico sem duplicar o direcional (se duplicar, o remap do D4 entra aqui), anotado no `docs/BRINGUP-GA36.md` e no `docs/BRINGUP-R36S.md`.

## 2. Idioma, fuso e ambiente do runner

- [x] 2.1 Campo `[runner.env]` nos runners (`lume-core`, D5): tabela de nome e valor, nome `[A-Za-z_][A-Za-z0-9_]*`, runner com nome inválido é recusado com linha no log; `docs/LAUNCHER.md` (formato do runner) atualizado. Verificação: `cargo test` do `lume-core` (env válido lido, nome com `=` recusa o runner, outros runners seguem) e o teste que confere o exemplo do `docs/LAUNCHER.md`.
- [ ] 2.2 Ambiente do jogo no `lume-run` (D5): vetor montado antes do `clone3` com o herdado menos `LANG`, `LANGUAGE`, `LC_*` e `TZ`, mais `LANG`/`LANGUAGE` do `settings.toml` lido a cada jogo, `TZ` de `/etc/timezone` (só se a zona existir) e as variáveis do runner por último; o filho usa `execve`. Verificação: teste do `lume-run` com um runner falso que grava o próprio ambiente (pt → `pt_BR.UTF-8`; sem idioma → `en_US.UTF-8`; troca de idioma vale no jogo seguinte; sem `LC_ALL`; variável do runner presente só no runner dele).
- [ ] 2.3 Probe de LÖVE em `tests/device/love-probe/` (um `.love` mínimo que mostra `os.getenv("LANG")`, `love.system.getPreferredLocales()` e a hora local, e grava os três num arquivo em `/run/lume/`) e roteiro `tests/device/scripts/love-probe.toml` que o abre com o idioma em `en` e em `pt`. Verificação: no aparelho (J1, J2), o roteiro passa com os valores esperados e a hora igual à do launcher; anotado nos `BRINGUP`.

## 3. TurboGrafx-16, TurboGrafx-CD e CPS-3

- [ ] 3.1 Aport `aports/libretro-mednafen-pce-fast/` (D8): commit fixo do `beetle-pce-fast-libretro`, `sha512sums`, build padrão do upstream sem flags de CPU, os três arches; entra em `rootfs/packages.txt`. Verificação: `lume pkg` nos três arches sem erro, `.so` e `.info` no pacote, e o teste de paridade de manifesto passa.
  - 2026-11-19: commit fixo `2de1ce1c`, `lume pkg` sem erro em armv7, aarch64 e x86_64, com o `.so` em `/usr/lib/libretro/`. O `.info` não vai no pacote (nenhum aport local leva): vem do `libretro-core-info` do Alpine, e o `rootfs/configure.sh` copia os dos `.so` instalados. Falta conferir na imagem da 6.1 o `.info` e a paridade de manifesto.
- [ ] 3.2 Catálogo (D8): sistemas `pcengine` ("TurboGrafx-16", `TG16`) e `pcenginecd` ("TurboGrafx-CD", `TGCD`) com `mednafen_pce_fast` e extensões tiradas do `.info`, BIOS `syscard3.pce` obrigatória no CD; `cps3` ("CPS-3", `CPS3`) no `fbneo` com o romset do FBNeo; `LEIA-ME.txt`, `docs/CATALOG.md` e `tests/cores/run_roms.sh` atualizados. Verificação: `tests/unit/test_catalog.py` (validador aceita; arcade sem `core_by_arch`; mesmos cores nos dois consoles) e o teste do `LEIA-ME.txt`; prova no aparelho na 6.2/6.3 (um HuCard, um CD e, se o usuário tiver, um romset de CPS-3 abrem pelo launcher).

## 4. Cópia pelo cabo e conjunto de teste padrão

- [ ] 4.1 `openssh-sftp-server` e `rsync` em `rootfs/packages.txt` (D9), com comentário; seção "Pelo cabo USB" do `docs/LAUNCHER.md` (ou do guia do usuário) com `scp`, `sftp://` e `rsync`. Verificação: teste do manifesto lista os dois nos três alvos; no aparelho (J1, J2), `scp` sem `-O`, o gerenciador de arquivos por `sftp://` e um `rsync` interrompido e retomado de um jogo de CD terminam com o mesmo SHA256, e nenhum processo dos dois roda sem cabo.
- [ ] 4.2 Conjunto de teste em `var/roms_test/` (D10, sessão principal, arquivos privados): `roms/<sistema>/` com `gamelist.xml` (nomes limpos) e `images/`, e `bios/` com as BIOS que os jogos pedem. Por console, 6 a 10 dos jogos mais conhecidos dos backups do usuário; no arcade, romsets de cada família de hardware disponível (Capcom CPS-1 e CPS-2, SNK Neo Geo, Irem, Konami, Data East, Sega System 16), cada um conferido no core padrão da sua pasta antes de entrar; também os jogos de LÖVE. Verificação: cada `gamelist.xml` é XML válido, toda entrada aponta para um arquivo que existe e toda capa citada existe; nenhum nome de jogo vai para artefato do projeto.
- [ ] 4.3 Comando `lume dev roms push [DIR]` (D10, padrão `var/roms_test/`): `rsync` pela rede USB quando o console tem `rsync`, senão `tar` pelo SSH; confere o SHA256 de cada arquivo copiado e recopia uma vez o que diferir; nunca apaga nem sobrescreve; funde o `gamelist.xml` só com as entradas que faltam; saída só com contagens por sistema; `docs/TESTES-APARELHO.md` (ou o guia de teste no aparelho existente) atualizado. Verificação: testes de unidade com um console falso (cartão vazio recebe tudo; cartão com jogos fica com os dele e ganha os que faltam; diferença de hash recopia e depois falha; saída sem nomes) e, no aparelho (J1), um cartão limpo fica com todos os sistemas do conjunto no launcher.

## 5. Ferramenta de medição

- [x] 5.1 Medição A/B por core (D6): script em `tests/device/` que, com o console no cabo, para cada core e variante, abre o jogo N do sistema pelo `lume dev run`, aplica as chaves da variante por `/run/lume/retroarch-extra.cfg` ou o `.opt` da variante (devolvendo o original), espera 30 s, mede 120 s na ordem A, B, A e grava uma linha agregada em `docs/tuning/<console>.md` (quadros mostrados por segundo, velocidade do core, falhas de áudio, clock médio, CPU por núcleo, temperatura, ruído entre os dois A, decisão). Fixa a fonte das falhas de áudio (`status` do ALSA ou log do RetroArch). Verificação: testes de unidade da agregação e do critério de aceite do spec (ganho acima do ruído, velocidade cheia, som contínuo) com amostras gravadas; o relatório não aceita nome de jogo nem caminho.

## 6. Imagem e provas funcionais

- [ ] 6.1 Build dos pacotes (`armv7`, `aarch64`, `x86_64`) e das imagens `ga36` e `r36s` com os nós 1 a 5 mesclados, sob a proteção de calor. Verificação: build sem erro e `lume test-vm` passa (o RetroArch abre um jogo de TurboGrafx-16 na VM com o `run_roms.sh`).
- [ ] 6.2 J1, GA36: `lume push` com o boot conferido; `lume dev roms push` num cartão limpo; provas de 1.3, 2.3, 3.2, 4.1 e 4.3. Verificação: cada prova anotada no `docs/BRINGUP-GA36.md` (sem nome de jogo).
- [ ] 6.3 J2, R36S: o mesmo da 6.2 no R36S. Verificação: anotado no `docs/BRINGUP-R36S.md`.

## 7. Linha de base e A/B

- [ ] 7.1 Linha de base no GA36 de cada core do catálogo e do LÖVE, com a configuração padrão. Verificação: uma linha por core em `docs/tuning/ga36.md`.
- [ ] 7.2 A/B das chaves do RetroArch (D7, primeira linha) por core no GA36. Verificação: linhas com a decisão de cada variante em `docs/tuning/ga36.md`.
- [ ] 7.3 A/B das opções de cada core (D7), com os nomes de opção conferidos no `libretro_core_options.h` do commit fixado de cada core antes de medir. Verificação: linhas com a decisão em `docs/tuning/ga36.md`.
- [ ] 7.4 A/B do LÖVE (variáveis do runner e classe de energia `love`). Verificação: linhas com a decisão em `docs/tuning/ga36.md`.
- [ ] 7.5 R36S: linha de base e A/B dos mesmos candidatos, começando pelos aceitos no GA36. Verificação: `docs/tuning/r36s.md` com uma linha por core e variante.

## 8. Vencedores na imagem

- [ ] 8.1 Gravar os ajustes aceitos: chaves por core e por console no `retroarch-core.keys`, `.opt` de fábrica por core, `[runner.env]` do `love.toml`; `docs/tuning/README.md` explica o método e liga os relatórios, como base da P-10. Verificação: testes de unidade conferem que cada chave e opção gravada tem linha "aceito" no relatório do console dela.
- [ ] 8.2 Segundo build e conferência (J3) nos dois consoles: cada core roda com os ajustes e repete as métricas do relatório dentro do ruído medido. Verificação: uma linha "conferido" por core e console em `docs/tuning/<console>.md`.

## 9. Investigação e distribuição

- [x] 9.1 Listas corrompidas de 2026-11-19 (D11): perguntar ao usuário se o cartão passou pelo leitor USB do PC à tarde; ler o `events.log` desse boot (gravações do índice e do launcher); se a causa for do sistema, abrir a correção nesta change como tarefa nova antes do 6.1. Verificação: causa anotada aqui e no `docs/BRINGUP-GA36.md`; os `gamelist.xml.corrupt` apagados do cartão depois.
- [ ] 9.2 Jogos livres para os sistemas novos em `var/roms_default/` (distribuição final): registrar no `docs/PENDENCIAS.md` (tema "Emuladores, cores e RetroArch", P-NN novo) os sistemas sem jogo livre de exemplo (`pcengine`, `pcenginecd`, `cps3` e os que já faltam hoje), com a regra de que só entram jogos livres de direitos autorais. Verificação: a pendência existe com a lista e a regra.
- [ ] 9.3 Conferência do cartão ao acordar (D11, `system-sleep`): o `lume-sleep` guarda o contador `.boot` da `ROMS` antes de suspender e, ao acordar, antes de qualquer gravação na `ROMS`, relê o contador do cartão sem o cache de página; se mudou, reinicia na hora sem `sync` e sem gravar no cartão, e o boot seguinte registra o motivo no `events.log` (por exemplo `sleep FAIL card changed during suspend`). Resolver como os gravadores da `ROMS` (`lume-logd`, `lume-persist`, launcher) esperam a conferência (protocolo de clientes do sono ou conferência antes do descongelamento). Verificação: testes de unidade e de shell do `lume-sleep` (contador igual segue; contador diferente reinicia sem gravar; nenhum gravador grava antes da conferência); no aparelho (J1, J2), suspender, levar o cartão ao outro console, devolver e acordar: reinicia, nenhuma lista nem log corrompido, linha no `events.log`; e um despertar normal segue sem atraso perceptível.

Causa da 9.1 (2026-11-19): o cartão saiu do GA36 suspenso (boot 204, 04:41 UTC), iniciou no R36S (boots 205 a 214) e voltou; ao acordar às 19:39, o GA36 gravou com a tabela do exFAT de antes da troca (D11). Não foi o leitor USB nem a gravação atômica. Os seis `gamelist.xml.corrupt` foram apagados do cartão (recontagem 0). Correção na 9.3.

## Workflow follow-up

- Branch `feature/game-experience-tuning` a partir da `main`; merge na `main` por PR com squash, só quando o usuário pedir.
- Arquivar a change depois da 8.2 e das provas nos dois consoles.
