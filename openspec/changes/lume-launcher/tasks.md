# Tasks

## 1. Verificações prévias e branch

- [ ] 1.1 Kernel (D9): conferir no `.config` final de `board/ga36` e de `board/r36s` as opções
  `CGROUPS`, `CGROUP_PIDS`, `MEMCG` e a presença de `cgroup.kill` (kernel ≥ 5.14). Ligar no
  fragmento da placa o que faltar. Verificação: `rg` nos dois `.config` gerados e
  `ls /sys/fs/cgroup/` na VM com `rc_cgroup_mode="unified"`, mostrando `cgroup.kill`.
  *(2026-11-14: parte da VM feita, `cgroup.kill` e os controladores `pids` e `memory` no
  `test-vm`; falta o `.config` dos consoles, no próximo `r36os build console`.)*
- [x] 1.2 RetroArch 1.22.2 (D7): ler na fonte quatro pontos e anotar o resultado em
  "Resultados das verificações" no `design.md`:
  - (a) se `-e/--entryslot` existe e carrega o estado;
  - (b) se uma chave de `--appendconfig` acaba gravada no `retroarch.cfg` ao sair;
  - (c) se o `QUIT` do comando de rede ignora o `quit_press_twice`;
  - (d) o nome da subpasta por core em `states/<id>/`.

  Para isso, declarar `retroarch` em `[upstream.*]` do `policy.toml` com o OK do usuário, ou
  ler o tarball do `aports/retroarch`.
- [x] 1.3 LÖVE (D5): conferir se o Alpine 3.24 empacota o `love` para armv7 e aarch64. Se não,
  criar `aports/love` fixado, no padrão de `aports/README.md`. Verificação: `apk` instala o
  pacote no rootfs dos dois alvos.
- [x] 1.4 Criar a `feature/lume-launcher`, com a base confirmada pelo usuário (`main` ou
  `feature/boot-dtb-select`), antes do primeiro commit de código. Verificação:
  `git log --oneline -n 1` mostra o ponto de partida combinado.

## 2. Workspace Rust e renderização (D2, D3)

- [ ] 2.1 Protótipo mínimo de renderização, que desenha a grade parada a 640x480 com 8 tiles e
  texto. Medir no GA36 o RSS e o tempo de quadro do SDL2 (KMSDRM + GLES, `lima`) contra o
  *dumb buffer* do DRM em software. Repetir no R36S quando estiver em mãos. Anotar os números e
  o backend escolhido por console no `design.md` (D3).
- [x] 2.2 Criar `lume/` (workspace com `lume-core`, `lume-index`, `lume-ui` e `lume-run`;
  perfil de release com `opt-level="s"`, `lto`, `panic=abort` e `strip`; `Cargo.lock`
  versionado). Verificação: `cargo build` e `cargo test` passam no host. A versão mínima do
  Rust bate com o `rustc` do Alpine 3.24.
- [x] 2.3 Criar `aports/lume-launcher`: crates vendorizadas num tarball de `distfiles` com
  SHA512, build offline, os binários em `/usr/bin` e a fonte Noto Sans (OFL) com a licença.
  Verificação: o pacote compila para x86_64, armv7 e aarch64 no pipeline do `r36os build`, e
  `tests/integration/test_local_repo.py` o lista.

## 3. Daemon de entrada `r36os-input` (D8)

- [x] 3.1 Transformar o `aports/r36os-padmerge` no `aports/r36os-input`:
  - perfis em `/usr/share/r36os/input/{ga36,r36s,vm}.conf`, com as origens por nome e o mapa de
    códigos;
  - captura exclusiva das origens e publicação do controle virtual com o mesmo nome de hoje;
  - pacote nos três alvos.

  Testes: `tests/unit/test_padmerge.py` vira `test_r36os_input.py`, com dispositivos falsos de
  `uinput` para os três perfis. O nome publicado bate com a autoconfiguração do RetroArch de
  cada console.
- [x] 3.2 Acorde do Fn e socket `/run/r36os/input.sock`, conforme D8. Testes com `uinput`
  falso:
  - Fn sozinho sai como pressionar e soltar `BTN_MODE` ao soltar;
  - Fn+Start manda `quit` e não repassa nenhuma das duas teclas;
  - Fn+outra tecla repassa as duas;
  - sem cliente conectado, nada acontece.
- [x] 3.3 Volume no daemon: `KEY_VOLUMEUP` e `KEY_VOLUMEDOWN` em passos fixos no controle de
  mixer do `r36os-mixer`, sem repassar a tecla. Teste com um mixer falso (variável de ambiente),
  como os outros testes de serviço.
- [x] 3.4 RetroArch:
  - tirar o `input_volume_*` da configuração de fábrica;
  - manter o menu no `BTN_MODE` pela autoconfiguração;
  - atualizar `tests/unit/test_retroarch_cfg.py` e o mapa de chaves fixas.

  Verificação: a suíte de unidade passa.
- [ ] 3.6 RetroArch, rótulo de "Sair" pelo frontend (D7): os patches 0001 e 0002 leem
  `LUME_RETROARCH_QUIT` (definida pelo `frontends/retroarch`). Aberto pelo lume, o item mostra o
  texto do upstream e fecha sem a confirmação dupla. Como frontend de reserva, continua
  "Desligar" com confirmação. Verificação: o aport compila e o self-test da VM abre o menu nos
  dois modos. *(2026-11-14: retroarch r111 compila; `lume-retroarch-menu` confere
  `LUME_RETROARCH_QUIT=launcher` no RetroArch aberto pelo lume e `quit-label-desligar` os
  textos do modo reserva. Falta ver o texto do item na tela, no aparelho.)*
- [x] 3.7 `frontends/retroarch`, chaves de uma execução só (D7): aceitar as chaves do launcher,
  guardar os valores do usuário (`aspect_ratio_index`, `state_slot`) numa pendência, rodar o
  RetroArch sem `exec` e devolvê-los ao terminar, ou no início da próxima execução se ele foi
  morto. Testes de shell com um `retroarch` falso: os valores voltam nos dois casos, e sem chaves
  do launcher nada muda.
- [x] 3.5 Serviço OpenRC e regra do udev do GA36: esconder a origem como no R36S e subir antes
  do `frontend`. Documentar o daemon em `docs/BRINGUP-GA36.md` e `docs/BRINGUP-R36S.md` (seção
  de controles) e a linha de log dele em `docs/LOGS.md`. Verificação: o self-test da VM vê um
  único controle. *(2026-11-14: `input-daemon` PASS no `test-vm` 80/80, um único "Lume VM
  Keyboard" e a linha `from 1 of 1 source` no log de boot.)*

## 4. Catálogo, runners e opções (`lume-core`, D5, D6)

- [x] 4.1 `systems.json` esquema 3: `abbr`, `emulators` derivável de
  `core`/`core_by_arch`/`alt_cores`, e os sistemas `love` e `ports`.
  - Atualizar `src/r36os/catalog.py` (validação do runner citado e da coerência das duas
    formas).
  - Atualizar o `LEIA-ME.txt`, a criação das pastas e o `docs/CATALOG.md`.

  Testes: `tests/unit/test_catalog.py` (esquema 3, runner ausente recusado, pastas `love/` e
  `ports/` criadas sem apagar nada) e `test_playlists.sh` inalterado e passando.
- [x] 4.2 Leitura de runners em `lume-core`: TOML, marcadores, `kind`, `quit` e `timeout`; o do
  cartão vence o da imagem; arquivo inválido é recusado com uma linha de log. Testes `cargo`:
  ROM com espaço vira um único argumento; marcador desconhecido, `exec` vazio e executável
  ausente são recusados.
- [x] 4.3 Runners da imagem em `rootfs/overlay/usr/share/lume/runners.d/` (`retroarch`, `love`
  e `sh`) e extensão pelo cartão em `ROMS/system/lume/systems.d/`. Testes: o build valida os
  runners da imagem, e um `systems.d` de teste acrescenta um emulador a `snes` e cria um sistema
  novo.
- [x] 4.4 Três camadas e persistência (`settings.toml`, `systems/<id>.toml`,
  `games/<id>.toml`, todos com escrita atômica). Testes `cargo`:
  - jogo, depois console, depois catálogo;
  - "Padrão" apaga a exceção;
  - "Limpar opções dos jogos";
  - uma escrita interrompida deixa o arquivo antigo inteiro.

## 5. Listas de jogos e índice (`lume-index`, D4)

- [x] 5.1 Scan e diff com o `gamelist.xml`, com fixtures em `lume/lume-index/tests/`:
  - um gamelist de scraper com campos desconhecidos é preservado byte a byte nas entradas
    existentes;
  - jogo novo entra com o nome do arquivo;
  - ROM apagada fica no XML e sai do índice, e volta com a mesma capa quando a ROM volta;
  - XML sem mudança não é regravado (mtime igual);
  - pastas de mídia são ignoradas.
- [x] 5.2 Índice binário por sistema, `GEN` e leitura por `mmap`. Testes de ida e volta do
  formato; um índice truncado é recusado e refeito sem derrubar a leitura.
- [x] 5.3 Miniaturas: validação de assinatura (PNG, JPEG, WebP), escala para o tile do perfil,
  slots RGB565 e a chave de cache. Testes: um `.png` de texto vira "sem capa", e só a imagem
  alterada é refeita.
- [x] 5.4 `lume-index --touch <id> <path>` (`playcount`, `lastplayed`) e a gravação de
  favoritos, pelo mesmo caminho atômico. Teste com um gamelist de fixture.
- [x] 5.5 Serviço OpenRC `lume-index`:
  - no boot, em segundo plano, como `game`;
  - `flock`;
  - `usb-gadget` reinicia o serviço no `disconnected`.

  Testes: um de serviço (no padrão de `tests/unit/test_*_service.py`) e o caso do `usb-gadget`
  com o `rc-service` falso. Linha de log com a contagem por sistema, sem nomes, documentada em
  `docs/LOGS.md`.

## 6. Supervisor e sessão (`lume-run`, D1, D9, D10)

- [x] 6.1 Sessão: `rc_cgroup_mode="unified"` e criação de `/sys/fs/cgroup/lume/` delegado ao
  `game` antes do frontend; `$R36OS_RUN/logs/events.pending` gravável pelo `game`. Testes do
  `session` com um sysfs falso. Verificação na VM: `stat` do diretório mostra o dono `game`.
  *(2026-11-14: `cgroup-delegated` PASS. Achados no `test-vm`: o serviço `cgroups` e o `sysfs`
  precisam estar no `sysinit`, senão nada monta o v2 e o serviço diz `started` mesmo assim; e o
  flush do `logd` apagava o `events.pending`, que o `game` não podia recriar, perdendo linhas
  `game`; agora a pasta é do grupo `game` com sticky bit e o flush recria o arquivo.)*
- [x] 6.2 Laço do `lume-run`: códigos 0, 64, 65 e outros da interface; arquivos `launch` e
  `state` em `$XDG_RUNTIME_DIR/lume/`. Testes de integração em Rust com uma interface falsa:
  - 0 sai com 0;
  - 64 roda o argv e reabre a interface;
  - falha da interface sai com 1;
  - falha do jogo não sai.
- [x] 6.3 Cgroup por jogo e encerramento:
  - `clone3` no cgroup, com a alternativa de `fork`;
  - pidfd e socket no `poll`;
  - `retroarch-cmd` (UDP `QUIT` duas vezes, com 200 ms entre elas, D7) e `sigterm`, depois
    `cgroup.kill`;
  - alternativa de `kill(-pgid)` com a linha `cgroup unavailable`.

  Testes:
  - um jogo falso que ignora SIGTERM e deixa um neto fora da sessão termina inteiro em até
    `timeout` + 2 s;
  - um jogo falso que escuta UDP recebe `QUIT` antes de qualquer sinal.
- [x] 6.4 Linha de evento do jogo (D10), `lume-index --touch` depois de cada jogo e o registro
  do core dos slots que mudaram em `states/<id>.toml` (D7; teste: só o slot alterado ganha o
  core). Ajustar o `logd`: sem `retroarch`, o estado vem do `state` do `lume`, e as métricas incluem `lume-ui`,
  `lume-run` e `r36os-input`. Testes:
  - a linha tem o formato e nunca o nome ou o caminho da ROM;
  - teste do `logd` com o RetroArch ausente.

  Documentação em `docs/LOGS.md`.
- [x] 6.5 `frontends/lume`, `FRONTEND="lume"` em `etc/conf.d/frontend` e `docs/FRONTEND.md`
  (lume como padrão, retroarch como reserva e runner). Verificação: o teste `frontend-swap` do
  self-test continua passando, e o boot da VM sobe o `lume-run` como `game`. *(2026-11-14:
  `frontend-swap`, `frontend-up` e `frontend-not-root` PASS; frontend em 2,6 s do kernel.)*

## 7. Interface (`lume-ui`, D3, D6, D7, D10, D11)

- [x] 7.1 Motor:
  - trait `Canvas` com o backend escolhido em 2.1;
  - laço em `SDL_WaitEvent`, com teto de 30 fps em animação;
  - atlas de glifos com `fontdue`;
  - mapeamento do controle pelos códigos do Linux.

  Teste: com o backend falso, nenhum quadro é desenhado sem evento.
- [x] 7.2 Tema TOML: tokens, `extends`, `features` e Modo lite. Portar os 2 temas Material de
  `docs/lume-launcher/prototipo/temas/`. Documentar o formato em
  `docs/lume-launcher/formato-de-tema.md`. Testes: herança; tema inválido cai no padrão com log;
  Modo lite zera animações e transparência.
- [x] 7.3 Dock infinito (Favoritos, sistemas com jogos, Recentes, Configurações) com tiles de
  sigla, grade com miniaturas do índice, cache LRU com teto em bytes, L1/R1 acelerado e busca
  com teclado na tela. Testes de lógica:
  - a rotação;
  - o salto proporcional;
  - o filtro sem acento e com todas as palavras;
  - o LRU nunca passa do teto.
- [x] 7.4 Menu do jogo e opções:
  - Iniciar;
  - save states do core efetivo, com "N em outro core";
  - Emulador, Aspecto e Shader (só `libretro`);
  - Favoritos;
  - opções do console no Y e selo na grade;
  - montagem do argv do RetroArch (`--set-shader`, aspecto e `-e`, conforme o resultado da
    1.2).

  Testes do argv para os casos de jogo, console e padrão.
- [x] 7.5 Configurações:
  - Idioma, que grava também o `user_language` do RetroArch;
  - Tema e Modo lite;
  - Volume e Brilho (regra do udev do backlight para o grupo `video`);
  - Sistema sob demanda, com o RSS próprio;
  - Atualizar listas de jogos (roda o `lume-index` com progresso);
  - RetroArch (código 65);
  - Desligar com Cancelar como padrão;
  - Wi-Fi e Bluetooth só com adaptador.

  Testes: o adaptador de sistema falso mostra e esconde Wi-Fi e Bluetooth, e o
  `user_language` gravado é lido pelo `ui_lang` de `lib.sh`.
- [x] 7.6 Textos em en, pt e es, com as mesmas chaves, e um teste que falha com uma chave
  faltando ou não usada (no papel do `check-i18n.js` do protótipo). Verificação: as
  Configurações em espanhol a 640x480 sem corte, numa captura do backend falso.
- [x] 7.7 Volta ao mesmo lugar: gravar e ler o `state` (tela, sistema, foco pela chave do jogo,
  filtro). Teste: depois de um ciclo "abrir e voltar" com o `lume-run` falso, o foco está no
  mesmo jogo.
- [x] 7.8 Guia do usuário do launcher em `docs/LAUNCHER.md`: controles, Fn+Start, como
  adicionar um runner ou sistema pelo cartão e o formato do `gamelist.xml`. Ligar o guia no
  `README.md`. Verificação: o exemplo de runner do guia é aceito pelo teste de 4.2.

## 8. Integração na VM

- [x] 8.1 Self-test da VM, com checagens novas:
  - o `lume` sobe como frontend;
  - um runner falso abre e volta;
  - F1+Enter (Fn+Start do perfil `vm`) encerra um jogo falso que ignora SIGTERM e tem um neto;
  - um jogo novo copiado para `roms/` aparece depois de "Atualizar listas";
  - as linhas `game` aparecem no `events.log` sem nome de jogo.

  Verificação: `r36os vm` com o self-test verde. *(2026-11-14: `r36os test-vm` 80/80 em 400 s,
  com 10 checagens `lume-*`/`input-daemon`/`cgroup-delegated`; o teste dirige o `lume-ui` pelo
  arquivo `state` e teclas do QMP. O `logd` ficou em 0,95% de um núcleo, perto da meta de 1%,
  depois de trocar `pidof`/`awk` por builtins nas métricas do lume.)*
- [ ] 8.2 Na VM, com as ROMs de teste do usuário: abrir um jogo de cada sistema libretro pelo
  launcher, sair por Fn+Start e conferir que a SRAM foi gravada. Anotar só "validado com ROMs de
  teste do usuário".

## 9. Medição no aparelho (GA36 e R36S)

- [ ] 9.1 GA36: RSS e CPU do `lume-ui` parado na grade (meta: CPU abaixo de 1% de um núcleo
  em 60 s) e RSS do `lume-run` e do `r36os-input` durante um jogo (meta: abaixo de 2 MB cada),
  pelas métricas do `logd`. Comparar com o menu atual do RetroArch e preencher a tabela de
  `docs/lume-launcher/orcamento-de-performance.md`.
- [ ] 9.2 GA36: tempo do boot até o Dock e tempo do fim do jogo até a grade (meta: até 1 s),
  medidos pelo `events.log` e pelas métricas. Anotar em `docs/BRINGUP-GA36.md`.
- [ ] 9.3 GA36: tempo do scan inicial e do scan sem mudança numa coleção grande (ROMs de teste
  do usuário), com o total de jogos por sistema só em contagem agregada.
- [ ] 9.4 GA36: latência de entrada com e sem o `r36os-input` (mesma medição do jogo antes e
  depois) e mapeamento real de A, B, X, Y, L1, R1 e Fn no launcher.
- [ ] 9.5 GA36: Fn+Start em cada tipo de runner (RetroArch, LÖVE, um script de `ports` e um
  emulador falso travado): todos voltam ao launcher. Fn sozinho abre o menu do RetroArch. O
  volume funciona nos três.
- [ ] 9.6 R36S: repetir de 9.1 a 9.5 quando o aparelho estiver em mãos e anotar em
  `docs/BRINGUP-R36S.md`. Se o aparelho não estiver disponível antes do fim do change, mover a
  tarefa para a `r36s-usb-proof`, como foi feito na `push-boot-swap`.

## Workflow follow-up

- Commits pequenos (Conventional Commits) na `feature/lume-launcher`, juntos perto do fim do
  bloco de trabalho, com o OK do usuário.
- Arquivar com `/opsx:archive`. O P-44 vai para "Concluídas" com o change; o P-56 (PortMaster)
  continua aberto.
