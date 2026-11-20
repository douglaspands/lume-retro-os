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
| 1.4 | 1.3 | — | AG | opus | 4 | J1, J2 |
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

Modelos: aprovados pelo usuário em 2026-11-19 (ondas 0, 1 e 2, sem trocas, em paralelo; a 9.2 só registra a pendência, feita na sessão principal).

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
- [x] 1.2 Semeadura de padrões em cartões existentes (D3): a cada início, o `frontends/retroarch` acrescenta ao `retroarch.cfg` do usuário as chaves do `factory/retroarch/retroarch.cfg` que faltam, e copia para `~/.config/retroarch/config/<core>/<core>.opt` as opções de fábrica que faltam (por chave), sem mudar nenhuma existente; o `.opt` de fábrica mora em `/usr/share/lume/factory/retroarch/config/`. Verificação: testes de unidade (chave ausente entra; chave do usuário nunca muda; `.opt` inexistente nasce igual ao de fábrica; opção do usuário fica; nomes das pastas iguais ao `corename` dos `.info` instalados).
- [ ] 1.3 Analógico como direcional (D4): `input_player1..4_analog_dpad_mode = "1"` no `factory/retroarch/retroarch.cfg`, comentado. Verificação: teste de unidade das quatro chaves na fábrica e da semeadura num cartão antigo; no aparelho (J1, J2), o analógico move num jogo de NES e num de Mega Drive (jogador 2 com controle USB, se houver), e o PS1 com DualShock recebe o analógico sem duplicar o direcional (se duplicar, o remap do D4 entra aqui), anotado no `docs/BRINGUP-GA36.md` e no `docs/BRINGUP-R36S.md`.

- [x] 1.4 Padrão de fábrica aplicado uma vez por cartão (revisão do D3, achado da J1): o `frontends/retroarch` aplica cada chave do `factory/retroarch/retroarch.cfg` e cada opção dos `.opt` de fábrica uma única vez por cartão, vencendo o valor que o RetroArch gravou, com o registro em `ROMS/system/lume/factory-applied` (gravação atômica); depois da primeira vez, o valor do cartão nunca muda; um padrão que muda de valor numa imagem nova é aplicado de novo uma vez; um cartão novo registra todos como aplicados. Na primeira vez de um arquivo (registro sem linha dele: cartão antigo ou `.opt` que o usuário já tinha), só os padrões listados em `/usr/share/lume/factory/new-defaults` mudam o cartão (hoje o `input_player1..4_analog_dpad_mode`); os outros são só registrados (decisão do usuário, 2026-11-19); o `user_language` nunca é aplicado por cima. Custo: uma leitura do registro e um awk por início de jogo, nada gravado quando não há padrão novo. Verificação: testes de unidade (cartão sem registro com menu e teclas do usuário fica com eles e recebe só o analógico; cartão com `"0"` gravado pelo RetroArch passa a `"1"` na primeira vez; o usuário volta a `"0"` e fica; o RetroArch regrava tudo e nada muda; valor de fábrica novo aplicado uma vez depois do registro; `.opt` igual; cartão novo; formato da lista conferido contra a fábrica); no GA36, o analógico anda num jogo de NES e de Mega Drive no cartão atual.
  - 2026-11-20, GA36 (boot 230, com o usuário): no cartão antigo, o primeiro jogo depois da imagem nova passou `input_player1..4_analog_dpad_mode` para `"1"` e manteve `menu_driver` e `user_language` do usuário; o analógico esquerdo e o direcional movem o personagem no 1º jogo de NES e no 1º de Mega Drive. Falta o PS1 com DualShock e o R36S (J2).
- [ ] 1.5 BIOS oficial e a abertura dela em todo core que oferece (pedido do usuário, 2026-11-20: "todos os cores que tenham a opção de usar a BIOS oficial, que usem"; sem o arquivo, a BIOS própria do emulador): `.opt` de fábrica do `Gambatte` (`gambatte_gb_bootloader`), do `gpSP` (`gpsp_bios = "auto"`, `gpsp_boot_mode = "bios"`), do `Genesis Plus GX` (`genesis_plus_gx_bios`, a abertura do Master System, do Game Gear e o texto TMSS do Mega Drive) e do `PCSX-ReARMed` (`pcsx_rearmed_bios = "auto"`, `pcsx_rearmed_show_bios_bootlogo`), na lista `new-defaults` (aplicados uma vez nos cartões antigos). Os outros cores da imagem não têm abertura de BIOS (FDS, CD e Neo Geo já usam a BIOS do cartão sem opção). Verificação: testes de unidade; no GA36 a abertura aparece com as BIOS do cartão e o jogo abre sem elas; R36S na J2.
  - 2026-11-20, GA36 (boots 232 e 233, com o usuário): as opções foram aplicadas no cartão e o RetroArch as manteve; o usuário viu as aberturas do GBA, do PS1, do Master System (logo SEGA) e o texto de licença do Mega Drive (o GB e o GBC já tinham). Sem BIOS (pasta de sistema vazia só no teste): GB, GBA, Master System, Mega Drive e PS1 abriram e fecharam (`exit=0`); o PS1 caiu na BIOS HLE com o aviso "No PlayStation BIOS file found"; o gpSP carrega a BIOS embutida sem o `gba_bios.bin` (código do core, `libretro.c`). Achado: no PS1 o core escolhe sozinho a BIOS da região do jogo, e no cartão do usuário a dos EUA que ele acha primeiro é a do PS3 em modo compatível (`ps1_rom.bin`, "non-standard BIOS detected"). Falta o R36S (J2).

## 2. Idioma, fuso e ambiente do runner

- [x] 2.1 Campo `[runner.env]` nos runners (`lume-core`, D5): tabela de nome e valor, nome `[A-Za-z_][A-Za-z0-9_]*`, runner com nome inválido é recusado com linha no log; `docs/LAUNCHER.md` (formato do runner) atualizado. Verificação: `cargo test` do `lume-core` (env válido lido, nome com `=` recusa o runner, outros runners seguem) e o teste que confere o exemplo do `docs/LAUNCHER.md`.
- [x] 2.2 Ambiente do jogo no `lume-run` (D5): vetor montado antes do `clone3` com o herdado menos `LANG`, `LANGUAGE`, `LC_*` e `TZ`, mais `LANG`/`LANGUAGE` do `settings.toml` lido a cada jogo, `TZ` de `/etc/timezone` (só se a zona existir) e as variáveis do runner por último; o filho usa `execve`. Verificação: teste do `lume-run` com um runner falso que grava o próprio ambiente (pt → `pt_BR.UTF-8`; sem idioma → `en_US.UTF-8`; troca de idioma vale no jogo seguinte; sem `LC_ALL`; variável do runner presente só no runner dele).
- [ ] 2.3 Probe de LÖVE em `tests/device/love-probe/` (um `.love` mínimo que mostra `os.getenv("LANG")`, `love.system.getPreferredLocales()` e a hora local, e grava os três num arquivo em `/run/lume/`) e roteiro `tests/device/scripts/love-probe.toml` que o abre com o idioma em `en` e em `pt`. Verificação: no aparelho (J1, J2), o roteiro passa com os valores esperados e a hora igual à do launcher; anotado nos `BRINGUP`.
  - 2026-11-20, GA36 (boot 228): o roteiro passou em `en` e em `pt` (`LANG`, `LANGUAGE`, `TZ=:/usr/share/zoneinfo/America/Sao_Paulo` e a hora igual à do console); o idioma do usuário voltou e o probe saiu do cartão. O LÖVE 11.5 da imagem não tem `love.system.getPreferredLocales` (o probe grava `n/a`; o roteiro aceita). Falta o R36S (J2).

## 3. TurboGrafx-16, TurboGrafx-CD e CPS-3

- [ ] 3.1 Aport `aports/libretro-mednafen-pce-fast/` (D8): commit fixo do `beetle-pce-fast-libretro`, `sha512sums`, build padrão do upstream sem flags de CPU, os três arches; entra em `rootfs/packages.txt`. Verificação: `lume pkg` nos três arches sem erro, `.so` e `.info` no pacote, e o teste de paridade de manifesto passa.
  - 2026-11-19: commit fixo `2de1ce1c`, `lume pkg` sem erro em armv7, aarch64 e x86_64, com o `.so` em `/usr/lib/libretro/`. O `.info` não vai no pacote (nenhum aport local leva): vem do `libretro-core-info` do Alpine, e o `rootfs/configure.sh` copia os dos `.so` instalados. Falta conferir na imagem da 6.1 o `.info` e a paridade de manifesto.
- [x] 3.2 Catálogo (D8): sistemas `pcengine` ("TurboGrafx-16", `TG16`) e `pcenginecd` ("TurboGrafx-CD", `TGCD`) com `mednafen_pce_fast` e extensões tiradas do `.info`, BIOS `syscard3.pce` obrigatória no CD; `cps3` ("CPS-3", `CPS3`) no `fbneo` com o romset do FBNeo; `LEIA-ME.txt`, `docs/CATALOG.md` e `tests/cores/run_roms.sh` atualizados. Verificação: `tests/unit/test_catalog.py` (validador aceita; arcade sem `core_by_arch`; mesmos cores nos dois consoles) e o teste do `LEIA-ME.txt`; prova no aparelho na 6.2/6.3 (um HuCard, um CD e, se o usuário tiver, um romset de CPS-3 abrem pelo launcher).

## 4. Cópia pelo cabo e conjunto de teste padrão

- [x] 4.1 `openssh-sftp-server` e `rsync` em `rootfs/packages.txt` (D9), com comentário; seção "Pelo cabo USB" do `docs/LAUNCHER.md` (ou do guia do usuário) com `scp`, `sftp://` e `rsync`. Verificação: teste do manifesto lista os dois nos três alvos; no aparelho (J1, J2), `scp` sem `-O`, o gerenciador de arquivos por `sftp://` e um `rsync` interrompido e retomado de um jogo de CD terminam com o mesmo SHA256, e nenhum processo dos dois roda sem cabo.
  - 2026-11-19, GA36 (J1, boot 221): `/usr/lib/ssh/sftp-server` e `rsync` na imagem; `rsyncd` (do `rsync-openrc`) fora de todo runlevel; nenhum processo de `sftp` ou `rsync` parado. Arquivo aleatório de 300 MiB: `scp` sem `-O` e `rsync` cortado aos 8 s e retomado (22,8 MB reaproveitados) com o mesmo SHA256 do PC lido do cartão. `sftp` pela linha de comando e pelo GVfs (o mesmo caminho do Nautilus, `gio mount sftp://root@10.55.0.1/` e `gio list .../storage`) mostram a `ROMS`. Detalhe de uso: o GVfs pergunta pela identidade do console a cada boot, porque a chave SSH muda em todo boot.
- [x] 4.2 Conjunto de teste em `var/roms_test/` (D10, sessão principal, arquivos privados): `roms/<sistema>/` com `gamelist.xml` (nomes limpos) e `images/`, e `bios/` com as BIOS que os jogos pedem. Por console, 6 a 10 dos jogos mais conhecidos dos backups do usuário; no arcade, romsets de cada família de hardware disponível (Capcom CPS-1 e CPS-2, SNK Neo Geo, Irem, Konami, Data East, Sega System 16), cada um conferido no core padrão da sua pasta antes de entrar; também os jogos de LÖVE. Verificação: cada `gamelist.xml` é XML válido, toda entrada aponta para um arquivo que existe e toda capa citada existe; nenhum nome de jogo vai para artefato do projeto.
  - 2026-11-19: 16 sistemas, 252 arquivos; todo `gamelist.xml` é XML válido, toda entrada e toda capa existem (conferido por contagem, sem nomes). Os backups não têm mais jogos de Master System, Sega CD, TurboGrafx-CD nem CPS-3 (pastas vazias). No GA36 (J1, boot 223) os 37 romsets de arcade (arcade 8, CPS-1 7, CPS-2 10, Neo Geo 12) iniciam no core padrão da pasta; os defeitos de saída de alguns cores foram para a P-114. Achado do roteiro: o `open_game` logo depois de um `close_game` perde teclas enquanto o launcher volta do jogo (o Neo Geo nº 5 caiu no menu do jogo anterior); com 3 s de espera entre eles passou. Correção da ferramenta: tarefa 6.4.
- [ ] 4.3 Comando `lume dev roms push [DIR]` (D10, padrão `var/roms_test/`): `rsync` pela rede USB quando o console tem `rsync`, senão `tar` pelo SSH; confere o SHA256 de cada arquivo copiado e recopia uma vez o que diferir; nunca apaga nem sobrescreve; funde o `gamelist.xml` só com as entradas que faltam; saída só com contagens por sistema; `docs/TESTES-APARELHO.md` (ou o guia de teste no aparelho existente) atualizado. Verificação: testes de unidade com um console falso (cartão vazio recebe tudo; cartão com jogos fica com os dele e ganha os que faltam; diferença de hash recopia e depois falha; saída sem nomes) e, no aparelho (J1), um cartão limpo fica com todos os sistemas do conjunto no launcher.

## 5. Ferramenta de medição

- [x] 5.1 Medição A/B por core (D6): script em `tests/device/` que, com o console no cabo, para cada core e variante, abre o jogo N do sistema pelo `lume dev run`, aplica as chaves da variante por `/run/lume/retroarch-extra.cfg` ou o `.opt` da variante (devolvendo o original), espera 30 s, mede 120 s na ordem A, B, A e grava uma linha agregada em `docs/tuning/<console>.md` (quadros mostrados por segundo, velocidade do core, falhas de áudio, clock médio, CPU por núcleo, temperatura, ruído entre os dois A, decisão). Fixa a fonte das falhas de áudio (`status` do ALSA ou log do RetroArch). Verificação: testes de unidade da agregação e do critério de aceite do spec (ganho acima do ruído, velocidade cheia, som contínuo) com amostras gravadas; o relatório não aceita nome de jogo nem caminho.

## 6. Imagem e provas funcionais

Estado em 2026-11-19, antes da 6.1: o código de 1.3, 2.3, 3.1, 4.1, 4.3 e 9.3 está mesclado; cada um espera a imagem (3.1: `.info` e paridade de manifesto) ou a prova no aparelho (1.3, 2.3, 4.1, 4.3, 9.3, na J1/J2). Pacote novo a construir na 6.1: `lume-cardid`.

- [x] 6.1 Build dos pacotes (`armv7`, `aarch64`, `x86_64`) e das imagens `ga36` e `r36s` com os nós 1 a 5 mesclados, sob a proteção de calor. Verificação: build sem erro e `lume test-vm` passa (o RetroArch abre um jogo de TurboGrafx-16 na VM com o `run_roms.sh`).
  - 2026-11-19: build `20261119-213407` sem erro em 3m45s (só o que mudou foi compilado; CPU máx. 79,4 °C, sem pausa). Os manifestos do GA36 e do R36S trazem `libretro-mednafen-pce-fast`, `lume-cardid`, `openssh-sftp-server` e `rsync` (com o `rsync-openrc` puxado pelo Alpine: conferir na J1 que não está em runlevel nenhum). `lume test-vm` não rodou, por decisão do usuário (vm fora do ciclo de build): o TurboGrafx-16 é provado no GA36 na J1. Paridade: `test_every_catalog_core_is_in_both_images` passa; `test_userland_packages_match_in_name_and_version` continua falhando só pelo `retroarch` (r118 no GA36 e r116 no R36S), falha que já existia antes desta change.
- [ ] 6.2 J1, GA36: `lume push` com o boot conferido; `lume dev roms push` num cartão limpo; provas de 1.3, 2.3, 3.2, 4.1 e 4.3. Verificação: cada prova anotada no `docs/BRINGUP-GA36.md` (sem nome de jogo).
  - 2026-11-20: provas anotadas no `docs/BRINGUP-GA36.md` (seção "Afinação dos jogos: provas da J1"): push e boot (231 a 236), 1.3 (NES e Mega Drive), 1.5, 2.3, 3.2 (HuCard; o conjunto não tem TurboGrafx-CD nem CPS-3), 4.1, cores novos, despertar normal. Faltam o PS1 com DualShock (1.3) e o cartão limpo (4.3, precisa de um segundo cartão vazio), os dois com o usuário.
- [x] 6.4 Corrida do `open_game` depois do `close_game` (achado da J1): o `GameDriver.open` (`src/lume_tool/dev_game.py`) espera o launcher voltar à tela (estado `ui` do launcher, não um tempo fixo) antes de mandar as teclas, para os roteiros e a medição A/B (5.1) não abrirem o jogo errado. Verificação: teste de unidade do driver com um estado falso que demora a voltar; no aparelho, o roteiro dos 37 romsets de arcade passa sem a espera de 3 s.
  - 2026-11-20: feita na 10.2 (`GameDriver.open` espera o launcher pronto); no GA36 (boot 228) os 37 romsets abriram e fecharam em sequência sem a espera de 3 s.
- [ ] 6.3 J2, R36S: o mesmo da 6.2 no R36S. Verificação: anotado no `docs/BRINGUP-R36S.md`.

## 7. Linha de base e A/B

- [ ] 7.1 Linha de base no GA36 de cada core do catálogo e do LÖVE, com a configuração padrão. Verificação: uma linha por core em `docs/tuning/ga36.md`.
  - 2026-11-20: `baseline.toml` no catálogo da 11.5 (os `_lume`, o `fbalpha2012`, o `mame2003_plus` no jogo de arcade cujo core por jogo ele é, o `fbneo` no nº 2, o `picodrive` no 32X, o LÖVE); um teste confere que todo core padrão do catálogo tem entrada. Faltam rodar 7 bases (~40 min) no GA36; a do LÖVE sai das execuções A da 7.4.
- [x] 7.2 A/B das chaves do RetroArch (D7, primeira linha) por core no GA36. Verificação: linhas com a decisão de cada variante em `docs/tuning/ga36.md`.
  - 2026-11-20 (boots 225 a 226): `alsathread`, `swapchain-2`, `latency-96` e `resampler-lowest` no core padrão dos 11 sistemas (`tests/device/tuning/retroarch-keys.toml`). `alsathread` aceito em 6 (CPS-2, Neo Geo, SNES, GBC, PS1, TurboGrafx-16); `swapchain-2` piora quase tudo; `latency-96` só no GBC; `resampler-lowest` sem ganho. `threaded-off` travou o GA36 (fora das medições do GA36). A decisão do que vira padrão é do usuário (8.1).
  - 2026-11-20, teste de ouvido com o usuário (arcade nº 1, `fbneo` a 63%): o som estalou igual com `alsa` e com `alsathread`, mas a ferramenta contou 60 e 0 falhas. **A medição não vê as falhas com o `alsathread`**: a thread alimenta a ALSA de um buffer próprio do RetroArch, a ALSA não registra underrun e o som picota mesmo assim. Os "aceitos" do `alsathread` não valem; ele fica fora dos padrões até a ferramenta medir as falhas do buffer do RetroArch (ou de outra fonte que veja os picotes).
- [ ] 7.3 A/B das opções de cada core (D7), com os nomes de opção conferidos no `libretro_core_options.h` do commit fixado de cada core antes de medir. Prioridade (J1, 2026-11-19, decisão do usuário): o `fbneo` na pasta `arcade` rodou a 42 e 30 quadros por segundo com a CPU no máximo (1008 MHz, `bottleneck cpu=70`); medir nos jogos lentos do conjunto (posições achadas pelos eventos `slow`) o `frameskip`, a taxa do som, as interpolações e a velocidade da CPU emulada. Core alternativo para a pasta `arcade` fica na P-24. Verificação: linhas com a decisão em `docs/tuning/ga36.md`.
  - 2026-11-20: depois da 10.5 o `fbneo` ficou só no jogo de arcade que nenhum outro core abre (nº 2 do conjunto) e no CPS-3. Plano `fbneo-options.toml` nesse jogo (frameskip automático e fixo 1, interpolações desligadas, taxa 44100, CPU emulada a 80%), nomes e valores conferidos no `retro_common.cpp` do commit fixado `77016b4d`; a ferramenta passou a aceitar chaves com hífen. Falta rodar no GA36 (~21 min; risco da P-115 no `fbneo`).
- [ ] 7.4 A/B do LÖVE (variáveis do runner e classe de energia `love`). Verificação: linhas com a decisão em `docs/tuning/ga36.md`.
  - 2026-11-20: a ferramenta aceita variantes `env` do LÖVE (o `runners.d/love.toml` do cartão com `[runner.env]`, gravado antes de fechar o jogo anterior, porque o launcher lê os runners ao voltar); plano `love-runner.toml` (`mesa_glthread`, `SDL_VIDEO_DOUBLE_BUFFER`). A classe de energia `love` é a do perfil, medida na base. Falta rodar no GA36 (~12 min).
- [ ] 7.5 R36S: linha de base e A/B dos mesmos candidatos, começando pelos aceitos no GA36. Verificação: `docs/tuning/r36s.md` com uma linha por core e variante.

## 8. Vencedores na imagem

- [ ] 8.1 Gravar os ajustes aceitos: chaves por core e por console no `retroarch-core.keys`, `.opt` de fábrica por core, `[runner.env]` do `love.toml`; `docs/tuning/README.md` explica o método e liga os relatórios, como base da P-10. Verificação: testes de unidade conferem que cada chave e opção gravada tem linha "aceito" no relatório do console dela.
- [ ] 8.2 Segundo build e conferência (J3) nos dois consoles: cada core roda com os ajustes e repete as métricas do relatório dentro do ruído medido. Verificação: uma linha "conferido" por core e console em `docs/tuning/<console>.md`.

## 9. Investigação e distribuição

- [x] 9.1 Listas corrompidas de 2026-11-19 (D11): perguntar ao usuário se o cartão passou pelo leitor USB do PC à tarde; ler o `events.log` desse boot (gravações do índice e do launcher); se a causa for do sistema, abrir a correção nesta change como tarefa nova antes do 6.1. Verificação: causa anotada aqui e no `docs/BRINGUP-GA36.md`; os `gamelist.xml.corrupt` apagados do cartão depois.
- [x] 9.2 Jogos livres para os sistemas novos em `var/roms_default/` (distribuição final): registrar no `docs/PENDENCIAS.md` (tema "Emuladores, cores e RetroArch", P-NN novo) os sistemas sem jogo livre de exemplo (`pcengine`, `pcenginecd`, `cps3` e os que já faltam hoje), com a regra de que só entram jogos livres de direitos autorais. Verificação: a pendência existe com a lista e a regra.
- [ ] 9.3 Conferência do cartão ao acordar (D11, `system-sleep`): antes de suspender, o `lume-sleep` faz o `persist flush` e o `sync`, grava a marca `ROMS/logs/.suspended-<console>`, remonta a `ROMS` só leitura e guarda a impressão digital do cartão (pacote novo `lume-cardid`: contador `.boot`, a entrada dele e o bitmap de alocação, lidos do dispositivo de bloco com `O_DIRECT`); ao acordar, o primeiro passo relê a impressão digital; se mudou (ou o cartão não pode ser lido), desliga o exFAT e reinicia com `reboot -n -f`, e o boot seguinte registra `sleep FAIL card changed during suspend`; o outro console que iniciar o cartão registra `sleep FAIL card left a suspended console`. Verificação: testes de unidade do `lume-cardid` (imagens exFAT sintéticas) e de shell do `lume-sleep` e dos logs (cartão igual segue; cartão mudado reinicia sem `sync`; `ROMS` só leitura durante o sono); no aparelho (J1, J2), primeiro `lume-cardid` no cartão real mostra o `.boot` certo; suspender, levar o cartão ao outro console, devolver e acordar: reinicia, nenhuma lista nem log corrompido, as duas linhas no `events.log`; um despertar normal segue sem atraso perceptível (tempo medido).
  - 2026-11-19: código mesclado (decisão do usuário: com a `ROMS` só leitura e o `lume-cardid`). Falta construir o `lume-cardid` na 6.1 e as provas no aparelho.
  - 2026-11-20, GA36: o `lume-cardid` no cartão real leu `boot=221` (certo) em 10 ms, estável entre duas leituras. Despertar normal (boot 230, com o usuário): "acordou rápido", `sleep OK resume after 19`, sem reinício. **Mas** a remontagem só leitura falhou antes de suspender (`sleep FAIL card: /storage not read-only (Resource busy); checked at the wake all the same`): valeu o plano B (conferência ao acordar). Ver a 9.4. Falta a prova da troca de cartão entre os consoles (usuário, com o R36S).
- [ ] 9.4 A `ROMS` não ficou só leitura na suspensão do GA36 (achado da 9.3, boot 230, `Resource busy`): quando a remontagem falha, o `lume-sleep` registra no rastreio quais processos têm arquivo da `ROMS` aberto para escrita (comando, `flags` e o caminho relativo, sem nome de jogo), e a causa é corrigida (o processo fecha o arquivo antes de suspender, ou a espera passa de 0,5 s). Verificação: teste de shell do registro; no GA36, 10 suspensões seguidas, do launcher e de dentro de um jogo, com `/storage` só leitura enquanto dorme.
  - 2026-11-20: registro feito (`sl_card_writers`: uma linha `writer <comando> <flags> <duas pastas>` por processo, sem nome de arquivo) com teste de shell, no GA36 desde o boot 236. As 10 suspensões precisam do usuário: o `lume-sleep` desliga o despertar pelo RTC e o kernel do GA36 não tem `pm_test` nem `wake_lock`; uma tentativa de fazer o kernel recusar (`pm_freeze_timeout` de 1 ms) suspendeu de verdade com o usuário longe. Essa suspensão é o primeiro dado do registro, a ler quando o console acordar.

Causa da 9.1 (2026-11-19): o cartão saiu do GA36 suspenso (boot 204, 04:41 UTC), iniciou no R36S (boots 205 a 214) e voltou; ao acordar às 19:39, o GA36 gravou com a tabela do exFAT de antes da troca (D11). Não foi o leitor USB nem a gravação atômica. Os seis `gamelist.xml.corrupt` foram apagados do cartão (recontagem 0). Correção na 9.3.

## 10. Cores alternativos de arcade (pedido do usuário, 2026-11-19)

O `fbneo` rodou jogos da pasta `arcade` abaixo da velocidade cheia no GA36 com a CPU no máximo e um núcleo a 100% (J1). O usuário pediu outros cores no lugar dele e a escolha do mais rápido para os jogos dele. Cada core pede romsets da sua versão (FB Alpha 0.2.97.29, MAME 0.78, MAME 0.37b5): o teste mostra quais abrem. Nós aprovados em 2026-11-19 (10.1 e 10.2 em paralelo).

| Nó | Depende de | Recursos | Executor | Modelo | Onda | Janela |
|---|---|---|---|---|---|---|
| 10.1 | — | — | AG | opus | A1 | |
| 10.2 | 5.1 | — | AG | opus | A1 | |
| 10.3 | 10.1 | CPU, ARCH:armv7 | PR | — | A2 | |
| 10.4 | 10.2, 10.3 | GA36 | PR | — | A3 | J1 |
| 10.5 | 10.4 | — | AG | sonnet | A4 | |

- [x] 10.1 Aports `libretro-fbalpha2012` (completo), `libretro-mame2003-plus` e `libretro-mame2000`: commit fixo, `sha512sums`, build padrão do upstream sem flags de CPU, os três arches; em `rootfs/packages.txt` e nos slots. Verificação: testes de manifesto e de slots; pacote com o `.so`; o `.info` de cada um no `libretro-core-info` da imagem (ou a falta registrada).
- [x] 10.2 Variante "core" na medição A/B (`src/lume_tool/tuning.py`, `tests/device/tuning_ab.py`): a variante troca o core de um jogo só durante a execução (pela opção por jogo do launcher, devolvida depois), registra se o jogo abriu e mede como as outras variantes; o relatório agrega por core e família de hardware, sem nome de jogo. Verificação: testes de unidade (aplicar e devolver a opção por jogo; jogo que não abre vira "não abre" sem derrubar a sequência; relatório sem nomes).
- [x] 10.3 Build armv7 dos três cores (fila de build, proteção de calor) e envio ao GA36. Verificação: `lume pkg` sem erro; `.so` no console.
  - 2026-11-20: os três compilaram para armv7 (perto de 85 °C, com a proteção de calor) e foram ao GA36 no build `20261120-000302` (boot 225): `.so` em `/usr/lib/libretro/` e `.info` em `/usr/share/lume/libretro-info/`. O usuário pediu só ARM e só o necessário: nenhum build x86; o aarch64 (R36S) só dos cores aprovados no 10.4. Melhoria da ferramenta para depois: numa comparação de cores, medir o core padrão uma vez antes e uma depois de todos os alternativos do mesmo jogo (5 execuções em vez de 9).
- [x] 10.4 Medição no GA36: cada jogo da pasta `arcade` do conjunto de teste em `fbneo`, `fbalpha2012`, `mame2003-plus` e `mame2000` (abre, velocidade cheia, quadros mostrados, clock, som). Verificação: linhas agregadas por core e família em `docs/tuning/ga36.md`; a escolha por jogo fica só no cartão do usuário.
- [x] 10.5 Catálogo: os cores aprovados entram como `alt_cores` da pasta `arcade` (ou o padrão muda, se um vencer em todas as famílias), com o romset de cada um no `LEIA-ME.txt`. Verificação: `tests/unit/test_catalog.py` e o teste do `LEIA-ME.txt`.
  - 2026-11-20 (decisão do usuário: "manter apenas os cores funcionais"): `arcade`, `cps1`, `cps2` e `neogeo` com o `fbalpha2012` completo como padrão; alternativos `mame2003_plus` e `fbneo` no `arcade`, `fbneo` nos outros três; `cps3` segue no `fbneo`. Saíram da imagem e do catálogo o `mame2000` e os três recortes (os aports ficam). `LEIA-ME.txt` com o romset de cada alternativo; README com os créditos e as licenças.
  - 2026-11-20, decisão 2 do usuário (core vencedor por jogo no cartão dele, nunca no repositório): dos 24 jogos medidos no GA36, 18 ficam no padrão novo e 6 do arcade ganham a exceção por jogo do launcher em `ROMS/system/lume/games/arcade.toml` (5 no `mame2003_plus`, 1 no `fbneo`), escolhidos pelo `tuning.pick` só entre os cores da imagem nova (os recortes contam como o `fbalpha2012`, o `mame2000` saiu da escolha). A tabela por placa para jogos não medidos fica para a P-116.

## 11. Cores `_lume` com as flags do processador (decisão do usuário, 2026-11-20)

O usuário trocou a decisão de 2026-11-17 (cores só no build do upstream): todos os cores ganham um build `_lume` com as flags do processador, ao lado do build do upstream, medido contra ele antes de substituí-lo; o PGO fica para depois (P-10). Sufixo `_lume` no id, no `.so` e no pacote (P-114). Flags: GA36 (armv7, Cortex-A7) `-marm -mcpu=cortex-a7 -mfpu=neon-vfpv4 -mfloat-abi=hard`; R36S (aarch64, Cortex-A35) `-mcpu=cortex-a35`; sem `-Ofast` nem LTO. Os dois MAME ganham também uma variante com o Cyclone (68000) e o DrZ80 (Z80) em assembly ARM, só no armv7.

| Nó | Depende de | Recursos | Executor | Modelo | Onda | Janela |
|---|---|---|---|---|---|---|
| 11.1 | 10.1 | — | AG | sonnet | B1 | |
| 11.2 | 11.1 | CPU, ARCH:armv7 | PR | — | B2 | |
| 11.3 | 11.2, 10.4 | GA36 | PR | — | B3 | J1 |
| 11.4 | 11.1 | CPU, ARCH:aarch64 | PR | — | B4 | |
| 11.5 | 11.3 | — | AG | sonnet | B5 | |

- [x] 11.1 Builds `_lume` dos 16 cores da imagem: um jeito único de gerar o pacote `libretro-<core>-lume` (com `<core>_lume_libretro.so` e o `.info` com o `corename` próprio) a partir do aport do upstream de cada core, com as flags por arquitetura acima e nada mais mudado; aports locais novos para os 4 cores que hoje vêm do Alpine (`fceumm`, `nestopia`, `gambatte`, `gpsp`), com commit fixo; variante Cyclone/DrZ80 dos dois MAME só no armv7 (`<core>_cyclone_lume`). Fora do catálogo até a 11.5. Verificação: testes de aport (flags por arquitetura, nenhuma outra mudança no build, nomes com `_lume`), manifesto e slots.
- [x] 11.2 Build armv7 dos cores `_lume` (arcade primeiro), envio ao GA36. Verificação: `lume pkg` sem erro; `.so` no console.
  - 2026-11-20: os 16 compilaram (as flags `-marm -mcpu=cortex-a7 -mfpu=neon-vfpv4 -mfloat-abi=hard` em cada linha de compilação) e foram ao GA36 no build `20261120-043741` (boot 227): 16 `.so` e 16 `.info` com o `corename` "(Lume)". Os dois Cyclone/DrZ80 foram recusados pelo abuild (*text relocations*) e ficaram suspensos (`cores_lume.SUSPENDED`, P-114).
- [ ] 11.3 Medição no GA36: cada core `_lume` contra o build do upstream, nos mesmos jogos do conjunto de teste (comparação de cores da 10.2). Verificação: linhas agregadas em `docs/tuning/ga36.md`.
  - 2026-11-20 (boots 227 e 228): medidos CPS-1, CPS-2 e Neo Geo (3 jogos cada), NES, SNES, Mega Drive, GBC, GBA, PS1, TurboGrafx-16 e os jogos 1 a 3 do arcade. Ganho claro no `genesis_plus_gx_lume` (98% → 100% e 938 → 816 MHz; o `picodrive_lume` 100% a 600 MHz), no `pcsx_rearmed_lume` (45,8 → 53,9 quadros por segundo, 627 → 600 MHz) e no `snes9x2005_plus_lume` (901 → 842 MHz); igual nos FB Alpha 2012, no `fceumm`, no `gambatte`, no `gpsp` e no `mednafen_pce_fast`; o `fbneo_lume` ficou ~1,5 ponto mais lento. Falta o arcade 4 a 8: o GA36 travou duas vezes no `fbneo` pesado (P-115) e o resto foi medido sem a pasta `arcade` para não arriscar o cartão.
  - 2026-11-20, depois da 11.5: os jogos 4 a 8 rodam no `mame2003_plus` (core por jogo no cartão), e o `mame2003_plus_lume` saiu da imagem com os outros `_lume` não adotados. Para medir esses jogos é preciso pôr o `mame2003_plus_lume` de volta numa imagem de teste (o aport continua); a decisão de core desses jogos não depende disso (o `_lume` empatou nos FB Alpha e só ganha em cores pesados de CPU, a confirmar). Fica para quando o usuário quiser a imagem de teste, ou para a P-114.
- [x] 11.4 Build aarch64 dos cores `_lume` (R36S). Verificação: `lume pkg` sem erro.
  - 2026-11-20: os 16 compilaram para aarch64 (`-mcpu=cortex-a35`); ainda não foram ao R36S (J2).
- [x] 11.5 Catálogo e imagem: o core `_lume` que vencer substitui o do upstream (migração das opções, saves, estados e remaps do usuário para o `corename` novo, com teste); o do upstream sai da imagem. Verificação: testes do catálogo e da migração.
  - 2026-11-20: entram `genesis_plus_gx_lume` (Master System, Game Gear, SG-1000, Mega Drive, Sega CD), `snes9x2005_plus_lume` e `pcsx_rearmed_lume`, nos dois consoles (o mesmo cartão: as mesmas pastas de opções); os do upstream e os outros `_lume` (empate ou perda) saem da imagem e ficam como aport (`cores_lume.ADOPTED`). Saves e estados ficam por jogo (`sort_*_by_content`), nada a mover. Falta o R36S (J2).
  - 2026-11-20, GA36 (boots 231 e 232): os três `_lume` abrem os jogos; o log do RetroArch mostra que eles gravam as opções em `config/Genesis Plus GX/`, `config/Snes9x 2005 Plus/` e `config/PCSX-ReARMed/`, as pastas do upstream: o RetroArch nomeia a pasta pelo `library_name` que o core informa, não pelo `corename` do `.info`. A migração por cópia para `<corename> (Lume)` (feita no commit da 11.5) era inútil e saiu; as opções do usuário já valem no `_lume` sem migração. As opções de fábrica de um `_lume` vão para a pasta do upstream (o frontend tira o sufixo do `corename`), com teste. As três pastas `(Lume)` criadas no cartão foram apagadas.

## Workflow follow-up

- Branch `feature/game-experience-tuning` a partir da `main`; merge na `main` por PR com squash, só quando o usuário pedir.
- Arquivar a change depois da 8.2 e das provas nos dois consoles.
