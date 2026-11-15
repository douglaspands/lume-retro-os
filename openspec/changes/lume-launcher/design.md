# Design

## Context

A motivação está em `proposal.md`. O planejamento da interface (telas, tema, metas e protótipo
candidato `20261114-033157`) está em `docs/lume-launcher/`. Estas notas supõem o dArkOS; as
decisões abaixo valem sobre elas. Estado atual relevante:

- **Sessão** (`docs/FRONTEND.md`, `usr/libexec/r36os/session`): roda
  `/usr/libexec/r36os/frontends/$FRONTEND` como `game` no `tty1`, sem X11 nem Wayland.
  - Saída 0: `persist flush` e `poweroff`.
  - Saída diferente de 0: reinicia; na 3ª falha em 60 s, mostra a tela de erro.
  - SIGTERM do serviço: encerra sem desligar.
- **RetroArch** (`frontends/retroarch`): grava as chaves fixas (`retroarch-lume.cfg` mais
  `retroarch-<board>.cfg`) na configuração do usuário e roda `exec retroarch`.
  - `network_cmd_enable` está ligado na porta 55355, e o `logd` usa `GET_STATUS` e
    `pidof retroarch`.
  - O Fn (`BTN_MODE`) abre o menu pela autoconfiguração; Start+Select também.
  - `input_exit_emulator*` está desligado.
  - Os botões de volume são teclas de teclado que o RetroArch trata.
- **Entrada**: os dois consoles já usam os mesmos códigos de tecla.
  - R36S: o `r36os-padmerge` (C, `aports/r36os-padmerge`) captura `gpio-keys` e `adc-joystick`
    com exclusividade e publica "R36S Gamepad" por `uinput`.
  - GA36: o controle vem direto do driver de kernel (`ga36mb-gamepad`, "GA36-MB Gamepad"), sem
    camada no meio.
- **Catálogo** (`systems.json` esquema 2, `docs/CATALOG.md`): `core`, `core_by_arch` e
  `alt_cores` por sistema. O `r36os-playlists` gera as playlists do RetroArch.
- **Cartão**: a `ROMS` é exFAT montada com `uid=1000` (usuário `game`). A configuração
  persistente do frontend vai em `ROMS/system/<frontend>/`, com escrita atômica.
- **Logs**: o `event` de `logs.sh` acrescenta linhas a `$R36OS_RUN/logs/events.pending`, copiado
  em lote para `ROMS/logs/events.log`. Logs e código são sempre em inglês.
- **Hardware**: GA36 com A33, 4x Cortex-A7, 512 MiB a 1 GiB e Mali-400 (`lima`, GLES2). R36S
  com RK3326, 4x Cortex-A35, 1 GiB e Mali-G31 (`panfrost`). zram ligado nos dois. Tela 640x480.
- **Toolchain**: não há nenhum pacote Rust no projeto. Os `aports/` de armv7 e aarch64 são
  compilados sob `qemu-user`, o que é lento (P-36).

## Goals / Non-Goals

**Goals:**
- Nenhum processo da interface na memória durante o jogo; o que fica tem tamanho de daemon
  (menos de 2 MB cada).
- Fn+Start que nenhum programa consegue ignorar.
- Emulador novo é dado, não código.
- Listas compatíveis com o `gamelist.xml` do EmulationStation, para aproveitar scraping existente.
- Medir de verdade no GA36 e no R36S antes de fechar o change.

**Non-Goals:**
- Laço de emulação próprio (carregar o core libretro no launcher). O RetroArch continua sendo o
  provedor.
- Scraping, PortMaster (P-56), navegador de Arquivos e Capturas.
- Trocar o conteúdo do menu do RetroArch.
- Apagar arquivos do usuário: o scan nunca apaga nada.

## Decisions

### D1. Interface sai durante o jogo (supervisor + interface em processos separados)

```
 session --> frontends/lume --> lume-run (supervisor, sempre vivo, sem SDL)
                                  |
                                  +--> lume-ui -----> exit 0   (Desligar)   --> lume-run exit 0
                                  |                   exit 64  (abrir jogo) --> roda o jogo
                                  |                   exit 65  (menu do RetroArch, sem jogo)
                                  |                   outro    (falha)      --> lume-run exit 1
                                  |
                                  +--> jogo (cgroup próprio) --> termina --> lume-ui de novo
```

- O `lume-ui` decide o que abrir. Ele resolve as 3 camadas e o modelo do runner, grava o pedido
  já resolvido (argv, runner, sistema, chave do jogo) em `$XDG_RUNTIME_DIR/lume/launch` e sai.
- A posição da tela (tela, sistema, foco, filtro) fica em `$XDG_RUNTIME_DIR/lume/state`.
- O `lume-run` não sabe nada de tema nem de catálogo. Ele só roda o argv recebido, aplica a
  política de encerramento e reabre a interface.
- O código de saída do `lume-run` mantém o contrato da sessão como está: 0 desliga e qualquer
  outro valor conta como falha do frontend. A falha de um jogo nunca chega à sessão.
- **Alternativa descartada:** a interface residente, bloqueada em `waitpid`, que é o modelo do
  EmulationStation. Durante o jogo ela manteria SDL, EGL e Mesa e o heap carregados. Também
  exigiria liberar e retomar o DRM master entre dois processos vivos.
- **Custo da escolha:** reabrir a interface a cada volta. Isso é coberto por D4 e D9 e medido
  na tarefa 9.

### D2. Workspace Rust `lume/`

| Crate | Tipo | Conteúdo | Dependências principais |
|---|---|---|---|
| `lume-core` | lib | catálogo (esquema 3), runners, 3 camadas, formato do índice, configurações, i18n | `serde`, `toml`, `serde_json` |
| `lume-index` | bin + lib | scan, diff do `gamelist.xml`, índice, miniaturas | `quick-xml`, `image` (png, jpeg, webp) |
| `lume-ui` | bin | motor de UI, tema, telas, adaptador de sistema | `sdl2`, `fontdue` (glifos em Rust, sem FreeType) |
| `lume-run` | bin | supervisor, cgroup, socket do daemon de entrada | só `std` e `libc` |

- Os binários são linkados contra o musl do Alpine, com `opt-level="s"`, `lto`, `panic=abort`
  e `strip`.
- A versão mínima do Rust é a do `rustc` do Alpine 3.24.
- As crates são fixadas pelo `Cargo.lock` e vendorizadas num tarball de `distfiles` do aport
  `aports/lume-launcher`, para o build funcionar sem rede, como os outros aports.
- O `lume-run` fica pequeno de propósito: sem SDL, sem alocador próprio e sem async.
- **Alternativa descartada:** C + SDL2, um pouco mais leve, mas sem a segurança de memória e
  com mais trabalho. O Rust é a escolha das notas (`docs/lume-launcher/opcoes-de-tecnologia.md`).

### D3. Renderização: SDL2 em KMSDRM com GLES, atrás de uma fronteira trocável

- O `lume-ui` usa o `sdl2` do Alpine (driver KMSDRM, GLES2: `lima` e `panfrost`) e o
  `SDL_Renderer`.
- O laço dorme num canal (`mpsc`) alimentado pelas threads do controle, do índice e do
  progresso: sem input, a interface não redesenha. Durante uma animação o teto é de 30 fps, e
  um tema com `anim_ms = 0` não anima (o Modo lite saiu em 2026-11-14). *(2026-11-14: era `SDL_WaitEvent`, mas no KMSDRM o SDL não
  tem espera e acorda a cada 1 ms; no GA36 isso custou 42% de um núcleo parado. A fila do SDL
  agora só é esvaziada, sem espera, uma vez por segundo parado; tarefa 8.5.)*
- O motor desenha por um trait `Canvas`, com operações de retângulo, textura e texto. Ele não
  conhece o SDL fora da implementação desse trait.
- **Risco medido antes de fechar** (tarefa 2.1): o EGL e o Mesa podem ser a maior parte da
  memória residente.
  - Um protótipo mínimo mede o RSS do SDL2 com GLES contra um backend de *dumb buffer* do DRM
    em software (640x480 RGB565, cerca de 600 KB por buffer).
  - Se o software economizar muito e mantiver o tempo de quadro, ele vira o backend padrão no
    GA36, sem mudar as telas.
- **Texto:** o `fontdue` gera um atlas de glifos em textura, com cache. A fonte é empacotada,
  com cobertura de pt, en e es: a Roboto do protótipo (pacote `font-roboto` do Alpine,
  Apache-2.0) nos pesos 400, 500 e 700, como no CSS do protótipo (títulos 700; contador,
  bateria e nome em foco 500; o resto 400). *(2026-11-15: era a Noto Sans, OFL, só regular;
  trocada a pedido do usuário para seguir o protótipo à risca. Um teste confere que a fonte
  tem todo caractere das traduções.)*
- **Achado no GA36 (2026-11-14, com o `r36os-shot` da D12):** sem pedido, o SDL escolhe o
  renderer `opengl` (GL de desktop), que no `lima` só limpa a tela: o Dock saía só com a cor de
  fundo, e o `LUME_SCREENSHOT` (software) não mostrava o problema. O `lume-ui` agora pede o
  `opengles2` (o `SDL_RENDER_DRIVER` do ambiente ainda vence), e o self-test da VM exige o
  mesmo renderer. Dois cuidados vieram junto: o `lume-ui` sai com erro se o SDL cair num
  driver sem tela (`offscreen`, `dummy`), para a sessão tentar de novo, e desliga os handlers
  de sinal do SDL, que transformavam o SIGTERM num evento ignorado (um `lume-ui` órfão ficou
  com a tela).

### D4. Índice e miniaturas pré-processados (`lume-index`)

- **Scan:** para cada sistema do catálogo, `readdir` recursivo de `roms/<id>/`.
  - Ignora as pastas de mídia (`images`, `img`, `media`, `videos`, `manuals`) e arquivos
    ocultos.
  - Filtra pela extensão do catálogo e faz `stat` de cada arquivo (tamanho, mtime).
- **Diff com `roms/<id>/gamelist.xml`**, com as entradas casadas por `<path>` normalizado:
  - jogo novo ganha `<game><path>./x</path><name>x</name></game>`;
  - jogo existente mantém o elemento inteiro, inclusive os campos que o launcher não entende,
    porque o XML é relido e regravado preservando os nós;
  - jogo sumido continua no XML e só fica fora do índice;
  - o XML só é regravado se mudou: temporário, `fsync`, `rename` e `fsync` do diretório.
- **Índice:** um arquivo binário por sistema em `ROMS/system/lume/cache/index/<id>.bin`.
  - Tem uma tabela de strings e um registro fixo por jogo: nome, caminho, flags de favorito e
    de opção própria, `lastplayed`, `playcount` e o deslocamento da miniatura.
  - O `lume-ui` o lê por `mmap`, sem parse.
  - Uma geração (contador) no cabeçalho de `cache/index/GEN` avisa que o índice mudou.
- **Miniaturas:**
  - para cada `<image>`, confere a assinatura (PNG, JPEG, WebP);
  - decodifica, escala para o tamanho de tile do perfil do tema e grava em
    `cache/thumbs/<id>.bin` (slots RGB565 de tamanho fixo);
  - a chave é o caminho, o tamanho e o mtime da imagem, mais o tamanho do tile; só o que mudou é
    refeito;
  - o `lume-ui` nunca decodifica imagem: copia o slot para uma textura de um cache LRU com teto
    em bytes (padrão de 4 MB, ajustável pelo tema).
- **Quando roda:**
  - no boot, pelo serviço OpenRC `lume-index` (depois de `localmount` e `r36os-persist`, em
    segundo plano, como `game`);
  - quando o cabo USB é desligado: o `usb-gadget` chama `rc-service lume-index restart` no
    `disconnected`;
  - por "Atualizar listas de jogos": o `lume-ui` roda o `lume-index` e mostra o progresso.
  - Um `flock` em `cache/lock` impede dois scans ao mesmo tempo.
- **Aviso à interface:** uma thread do `lume-ui` observa o `GEN` com `inotify` e manda um evento
  SDL. A interface recarrega o índice sem perder o foco.
- **Favoritos e Recentes** usam os campos do EmulationStation no próprio `gamelist.xml`
  (`<favorite>`, `<playcount>`, `<lastplayed>`). Assim um scraper ou outro frontend vê os mesmos
  dados.
  - O `lume-run` atualiza `playcount` e `lastplayed` depois de cada jogo, chamando
    `lume-index --touch <id> <path>`.
  - A interface grava favoritos pelo mesmo caminho atômico.
- **Alternativa descartada:** índice em SQLite. Seria mais uma biblioteca na memória, e o
  `mmap` de um binário fixo é mais barato para leitura.

### D5. Runners e catálogo esquema 3

- **Runner:** um arquivo TOML por runner. A imagem traz `/usr/share/lume/runners.d/` e o cartão
  traz `ROMS/system/lume/runners.d/`; no mesmo `id`, o do cartão vence.

  ```toml
  [runner]
  id = "retroarch"
  kind = "libretro"          # libretro mostra Aspecto e Shader e lê o core
  exec = ["/usr/libexec/r36os/frontends/retroarch", "-L", "{core_path}", "{rom}"]
  quit = "retroarch-cmd"     # retroarch-cmd | sigterm
  timeout = 3                # segundos até o encerramento forçado
  ```

- **Marcadores aceitos:** `{rom}`, `{core}`, `{core_path}`, `{system}`, `{bios_dir}`,
  `{saves_dir}`, `{states_dir}`.
  - Cada marcador vale um argumento inteiro: não há shell no meio.
  - Marcador desconhecido ou `exec` vazio recusa o runner com uma linha no log.
- **Runners da imagem:**
  - `retroarch`;
  - `love` (`exec = ["love", "{rom}"]`, `quit = "sigterm"`). A tarefa 1.3 confere se o Alpine
    empacota o LÖVE para armv7 e aarch64; se não, ele vira um aport local;
  - `sh` (`exec = ["/bin/sh", "{rom}"]`, `quit = "sigterm"`) para `roms/ports/`.
- **`systems.json` esquema 3:** cada sistema ganha `emulators`, uma lista ordenada de
  `{runner, core?}`.
  - Para os sistemas libretro, a lista é derivada de `core`, `core_by_arch` e `alt_cores`, que
    continuam valendo, então o RetroArch e o `r36os-playlists` não mudam. Os testes conferem que
    as duas formas batem.
  - Entram os sistemas `love` (extensão `love`) e `ports` (extensão `sh`). Isso cria
    `roms/love/` e `roms/ports/` pela regra existente de recriar pastas no boot e acrescenta as
    duas ao `LEIA-ME.txt`.
- **Extensão pelo cartão:** `ROMS/system/lume/systems.d/*.toml` acrescenta emuladores a um
  sistema existente (`[[system]] id = "snes"`, `emulators = [...]`) ou cria um sistema novo
  (com `name`, `extensions` e `emulators`). O scan cria a pasta do sistema novo se faltar.
- **Validação:** o build valida o catálogo e os runners da imagem com `r36os.catalog.validate()`
  (runner citado tem de existir). Em tempo de execução, o `lume-core` aplica as mesmas regras
  aos arquivos do cartão e recusa só o arquivo inválido.

### D6. Opções em 3 camadas e persistência do launcher

Tudo fica em `ROMS/system/lume/`, gravado por temporário, `fsync` e `rename`:

| Arquivo | Conteúdo |
|---|---|
| `settings.toml` | idioma, tema, volume e brilho preferidos |
| `systems/<id>.toml` | padrão do console (emulador, aspecto, shader) |
| `games/<id>.toml` | exceções por jogo, chaveadas pelo `<path>` do gamelist (só o que difere) |

As exceções ficam fora do `gamelist.xml` para não pôr elementos estranhos no XML de outro
EmulationStation. Resolução: jogo, depois console, depois o primeiro emulador do catálogo.
"Limpar opções dos jogos" apaga o `games/<id>.toml`.

### D7. Abrir pelo RetroArch com core, aspecto, shader e slot

- O argv do runner `retroarch` passa pelo `frontends/retroarch`, que continua gravando as
  chaves fixas antes de cada execução. O `lume-ui` acrescenta:
  - `--set-shader <preset>` quando há shader efetivo. É um shader de execução, que o RetroArch
    não grava na configuração;
  - `--appendconfig $XDG_RUNTIME_DIR/lume/run.cfg` com `aspect_ratio_index` quando o aspecto
    não é o do core;
  - `-e <slot>` (`--entryslot`) para "Iniciar de um save state".
- A tarefa 1.2 conferiu a fonte do RetroArch 1.22.2 ("Resultados das verificações"). Decisões
  do usuário em 2026-11-14, a partir dela:
  - **Chaves de uma execução só (restaurar depois):** o `--appendconfig` vaza para o
    `retroarch.cfg`. O `frontends/retroarch`, quando recebe chaves de execução do launcher,
    guarda os valores do usuário das chaves tocadas (`aspect_ratio_index` e `state_slot`, que o
    `-e` também muda) num arquivo de pendência em `ROMS/system/lume/`, roda o RetroArch sem
    `exec` e devolve os valores ao `retroarch.cfg` quando ele termina. Se o jogo for morto antes
    (`cgroup.kill`), a devolução acontece no início da próxima execução do `frontends/retroarch`.
    O override de jogo temporário foi descartado: ele apagaria um override do próprio usuário e
    impediria gravar mudanças do menu durante a partida.
  - **`QUIT` duplo:** o `QUIT` de rede respeita o `quit_press_twice`, então o `retroarch-cmd`
    do `lume-run` manda `QUIT` duas vezes, com 200 ms entre elas (dentro dos 3 s do
    RetroArch). Com a opção desligada, o segundo não encontra ninguém e é ignorado.
  - **Rótulo de "Sair" pelo frontend:** os patches 0001 e 0002 passam a escolher o texto e a
    confirmação por uma variável de ambiente (`LUME_RETROARCH_QUIT`) que o `frontends/retroarch`
    define. Aberto pelo lume, o item volta ao texto do upstream ("Sair"/"Quit"/"Cerrar
    RetroArch"), sem a confirmação dupla do item de menu, porque sair volta ao launcher. Como
    frontend de reserva, continua "Desligar" com confirmação, como hoje.
- **Item "RetroArch" das Configurações:** o mesmo runner sem conteúdo (código 65 em D1). Ele
  abre o menu completo e volta ao launcher ao sair.
- **Save states por core (registro do lume):** o RetroArch grava em
  `states/<pasta do conteúdo>/<jogo>.state<N>`, sem o core no caminho nem no arquivo. Depois de
  cada jogo libretro, o `lume-run` compara o mtime dos slots do jogo com o de antes da execução
  e grava o core usado nos slots que mudaram em `ROMS/system/lume/states/<id>.toml` (chave: o
  `<path>` do gamelist; valor: slot e core), com escrita atômica. A lista de "Iniciar de um save
  state" mostra os slots do core efetivo. Os de outro core contam no "N em outro core". Slot sem
  registro (anterior ao launcher) aparece para qualquer core. Os states existentes não mudam de
  lugar.

### D8. Daemon de entrada `r36os-input` (o `padmerge` generalizado)

- O `aports/r36os-padmerge` vira `aports/r36os-input`, C, root, um processo por console.
  - Um perfil por placa em `/usr/share/r36os/input/<board>.conf` lista os dispositivos de
    origem (por nome) e o mapa de códigos. O GA36 passa a ter o mesmo caminho que o R36S.
  - O daemon captura com exclusividade (`EVIOCGRAB`) todos os dispositivos de origem: controle e
    botões de volume.
  - Publica por `uinput` o controle virtual com o **mesmo nome de hoje** ("GA36-MB Gamepad",
    "R36S Gamepad"), para a autoconfiguração do RetroArch não mudar.
  - A regra do udev esconde as origens como hoje, e o serviço sobe antes do frontend.
- **Acorde com o Fn:**
  - ao apertar `BTN_MODE`, o daemon não o repassa e espera;
  - Start antes de soltar o Fn: é Fn+Start. O daemon manda `quit` no socket e não repassa nem o
    Fn nem o Start;
  - Fn solto sem outra tecla: o daemon repassa `BTN_MODE` (pressionar e soltar), e o menu do
    RetroArch abre;
  - qualquer outra tecla com o Fn segurado: o daemon repassa o Fn e a tecla, preservando os
    atalhos que já usam o Fn.
- **Socket:** `/run/r36os/input.sock` (`SOCK_SEQPACKET`, grupo `game`). O `lume-run` se conecta
  e recebe `quit`. Sem cliente conectado, o evento é descartado, e é isso que faz o Fn+Start
  fora de um jogo não fazer nada. O `lume-ui` também fica conectado, ignora o `quit` e recebe
  `volume` depois de cada Vol+ ou Vol- aplicado, inclusive quando o nível já estava no limite;
  então lê o nível pelo mesmo controle do Settings. Os clientes ignoram mensagens que não
  conhecem.
- **Volume:** `KEY_VOLUMEUP` e `KEY_VOLUMEDOWN` mudam o volume do ALSA pelo mesmo controle que o
  `r36os-mixer` usa, em passos fixos, e não são repassados. O `input_volume_*` sai da
  configuração de fábrica do RetroArch. A tarefa 3.4 confere que o `test_retroarch_cfg.py` muda
  junto.
- **VM:** o perfil `vm` usa o teclado. F1 faz o papel de Fn, Enter o de Start, e as teclas de
  volume são as do teclado. Assim o self-test exercita o mesmo código.
- **Alternativa descartada:** um vigia passivo, sem `EVIOCGRAB`. Ele fica cego quando um
  programa captura o controle, e não consegue impedir que o Fn abra o menu do RetroArch antes do
  Start.

### D9. Supervisor `lume-run`: cgroup e encerramento

- **Delegação:** a sessão (root) cria `/sys/fs/cgroup/lume/` antes de rodar o frontend e a
  passa ao `game` (`chown` de `cgroup.procs`, `cgroup.subtree_control` e do diretório). Isso
  exige cgroup v2 montado: `rc_cgroup_mode="unified"` no `rc.conf`.
- **Cada jogo:**
  1. o `lume-run` cria `lume/game-<n>/`;
  2. faz `clone3(CLONE_INTO_CGROUP | CLONE_PIDFD)`, com `fork` e escrita no `cgroup.procs` como
     alternativa;
  3. o filho faz `setsid` e `exec` do argv;
  4. o `lume-run` faz `poll` no pidfd e no socket do `r36os-input`. Parado, usa 0% de CPU.
- **Encerramento por `quit`:**
  1. pedido educado: `retroarch-cmd` manda `QUIT` por UDP para `127.0.0.1:55355`; `sigterm`
     manda `kill(-pgid, SIGTERM)` (o SDL2 transforma SIGTERM em `SDL_QUIT`);
  2. espera `timeout`;
  3. escreve `1` em `cgroup.kill` e espera `cgroup.events` mostrar `populated 0`.
- **Sem cgroup v2** (o kernel não tem `cgroup.kill`, ou a delegação falhou): o `lume-run` usa
  `kill(-pgid, SIGKILL)` e registra `cgroup unavailable` no log. Um processo que saiu da sessão
  pode escapar; a tarefa 1.1 confere o kernel para isso não acontecer.
- **Depois do jogo:**
  - o `lume-run` remove o cgroup;
  - grava a linha de evento (D10);
  - chama `lume-index --touch`;
  - reabre o `lume-ui`, que lê o `state` e volta ao mesmo lugar.
  - O console de texto não precisa ser restaurado: a interface reabre em KMS na hora.

### D10. Integração com sessão, logs e sistema

- **Frontend:** `frontends/lume` é um script de uma linha (`exec lume-run`), com
  `FRONTEND="lume"` em `etc/conf.d/frontend`. O `frontends/retroarch` continua instalado, porque
  é o runner e também o frontend de reserva.
- **Eventos:** o `lume-run` acrescenta linhas no mesmo formato do `event` de `logs.sh` em
  `$R36OS_RUN/logs/events.pending`. A sessão cria esse arquivo gravável pelo `game`. Exemplo:
  `game OK snes retroarch snes9x exit=0 end=quit-combo secs=812`. Nunca há nome nem caminho de
  jogo.
- **`logd`:** sem `retroarch` rodando, o estado do frontend é o do `lume` (`ui`, `game:<runner>`
  ou `off`), lido de `$XDG_RUNTIME_DIR/lume/status`, e não falha. O `status` é gravado pelo
  `lume-run`, separado do `state` (posição da tela), que é da interface. Na coluna `frontend`
  das métricas, `ui` vira `launcher`. Sob o lume, o `logd` não grava as linhas `game` de
  abertura e fecho nem o nome do conteúdo; quem grava é o `lume-run`. As métricas passam a
  registrar RSS e CPU do `lume-ui`, do `lume-run` e do `r36os-input`. O resumo de cada scan do
  `lume-index` vira um evento `index` (contagem por sistema, sem nomes).
- **Idioma:** a escolha fica em `settings.toml`. O `lume-ui` também grava o `user_language`
  correspondente no `retroarch.cfg` do usuário, de forma atômica. Assim o `ui_lang` de `lib.sh`
  (mensagens do sistema) e o menu do RetroArch seguem a mesma escolha, sem mudar o `lib.sh`.
- **Wi-Fi, Bluetooth, brilho e desligar:**
  - Wi-Fi pelo `nmcli`;
  - Bluetooth pelo `bluetoothctl`, já na imagem (spec `wireless`);
  - brilho por `/sys/class/backlight/*/brightness`, com uma regra do udev dando escrita ao grupo
    `video`, como o P-32 previa;
  - os comandos são chamados só quando a tela é usada.
  - Desligar é o código 0 de D1.

### D11. Ícones, tema e fonte

- O tema padrão desenha cada item do Dock como um tile com a sigla do sistema, em `abbr` no
  catálogo esquema 3 (por exemplo "SNES", "MD", "PS1").
- O formato do tema é o de `docs/lume-launcher/formato-de-tema.md` em TOML: tokens, `extends` e
  `name` opcionais (sem `features`: o Modo lite saiu em 2026-11-14).
  - Um tema do cartão (`ROMS/system/lume/themes/<id>/`) pode trazer `icons/<id>.png`; a distro
    não traz nenhum.
  - Os 2 temas Material são portados de `docs/lume-launcher/prototipo/temas/`.
  - O tema padrão é o `lume` (pedido do usuário, 2026-11-14): os tons azuis do Lume TV
    launcher (`themes/lume/theme.css` do `douglaspands/lume-tv-launcher`, do mesmo autor;
    só os valores das cores são copiados), sobre as formas e tamanhos do `material-dark`
    (`extends`).
- O motor (`lume-ui`) não conhece nenhum tema pelo nome, como no protótipo. O tema padrão e o
  valor-base de cada token ficam em `/usr/share/lume/themes/base.toml`, e o nome de exibição
  de cada tema no próprio `theme.toml` (`name`, por idioma): um tema novo é só uma pasta, sem
  código nem tradução (pedido do usuário, 2026-11-14).

### D13. Régua do protótipo (regra do usuário, 2026-11-15)

- Toda tela do `lume-ui` é feita "com régua" a partir do protótipo aprovado
  (`docs/lume-launcher/prototipo/`, a cópia com os logos fica fora do git): posições,
  tamanhos, espaços, tamanho e peso das fontes e proporções dos ícones são medidos no
  navegador a 640x480 (`getBoundingClientRect` relativo ao `#stage`) e copiados.
- As regras de espaçamento do protótipo valem mais que as do Material Design 3 para
  portáteis: o Material só deu as cores e as formas; as medidas são as do protótipo, para o
  frontend ficar coeso.
- Os números viram `em` (1/40 da largura, 16 px a 640x480) e tokens do tema; as posições são
  calculadas em fração de pixel e arredondadas só no desenho. O y de um texto é o topo da
  caixa da linha no navegador (Roboto, altura de linha normal).
- Cada tela medida ganha um teste de régua com 1 px de tolerância
  (`grid_matches_the_prototype_ruler`, `dock_matches_the_prototype_ruler`,
  `settings_match_the_prototype_ruler`).
- O que o usuário pediu diferente do protótipo fica como ele pediu e anotado na tarefa:
  contador no meio do cabeçalho da lista, busca no estilo de launcher de TV, menu do jogo em
  quatro itens, Configurações em duas colunas com o painel maior, a bateria num lugar só em
  todas as telas (o da lista de jogos: 1,75em da direita, topo do texto a 1em; o protótipo a
  movia de tela para tela), com o Wi-Fi e o Bluetooth logo à esquerda dela (o protótipo
  punha a rede à esquerda da barra do Dock), o volume como a linha da borda direita, o
  painel das Configurações com o texto num tamanho só (as linhas do painel têm a métrica dos
  itens da lista: 1,669em a cada 1,769em, texto 1,05em; o nível de volume e brilho é uma
  linha "60%" sobre a barra; a nota é mais uma linha, apagada; só o título do painel é
  maior), "Atualizar listas" dentro do item Games (uma linha do painel, A atualiza) e, nas
  Configurações, a mesma margem em cima e embaixo: a lista e o painel começam 0,894em abaixo
  da linha do cabeçalho (fim da caixa do título, 35,25 px, onde termina a bateria), o mesmo
  espaço entre o fim do painel e os botões do rodapé (o protótipo tinha 0,553em em cima).

### D12. Captura da tela pelo cabo (`r36os-shot`, parte remota do P-57)

Incluída em 2026-11-14: as validações visuais (rótulo "Sair" da 3.6, Dock e grade da 9.x)
precisam de imagem com o usuário longe do aparelho, e o `LUME_SCREENSHOT` do `lume-ui` só
redesenha a própria interface.

- Binário em C no pacote `r36os-input` (o pacote de utilitários do console, já nos três
  alvos), sem `libdrm`: só as ioctls de `linux/drm*.h` e a `zlib`.
- Como root: para cada CRTC ativo, o framebuffer do plano primário por
  `DRM_IOCTL_MODE_GETFB2` (o handle só sai para quem tem `CAP_SYS_ADMIN`), exportado por PRIME
  e lido por `mmap` do dma-buf, com `DMA_BUF_IOCTL_SYNC` em volta da leitura.
- Formatos aceitos: `XRGB8888`, `ARGB8888` e `RGB565`, os de varredura dos drivers dos dois
  consoles; outro formato sai com erro e o nome dele, sem imagem errada.
- Saída: PNG RGB de 8 bits com a `zlib`, do tamanho do framebuffer (sem girar: a rotação do
  painel, se houver, aparece na imagem e é dita no log).
- Uso: `r36os-shot [arquivo.png]` (padrão `/tmp/r36os-shot.png`), por `ssh` pelo cabo. A
  conversão de pixels e o PNG são testados no PC com `--raw` (um framebuffer em arquivo).
- Na VM, com virgl, a imagem fica no host e o buffer do convidado pode vir vazio; o self-test
  usaria o `screendump` do QMP, não esta ferramenta.
- Fica para o P-57: atalho no aparelho (Fn+Select), gravação em `ROMS/screenshots/`, cópia para
  o PC sem `ssh` e a decisão entre imagem do jogador e de debug.

## Risks / Trade-offs

- **O EGL e o Mesa podem ocupar a maior parte do RSS do `lume-ui`.** Mitigação: o backend fica
  atrás do trait `Canvas` (D3), o protótipo mínimo da tarefa 2.1 mede as duas opções, e a escolha
  é por console.
- **O tempo de reabrir a interface pode ficar acima de 1 s no GA36.** Mitigação: `mmap` do
  índice, miniaturas prontas, fonte com atlas pequeno pré-gerado e nenhum scan no caminho da
  primeira tela. Isso é medido na tarefa 9.2. Se não bastar, só nesse caso, o modelo residente de
  D1 volta a ser avaliado.
- **O `--appendconfig` pode vazar o aspecto para a configuração do usuário.** Mitigação: conferir
  na tarefa 1.2 e, se vazar, usar o override temporário de jogo (D7).
- **O cgroup v2 pode estar ausente num dos kernels.** Mitigação: a tarefa 1.1 confere e liga as
  opções no `.config` da placa (`CGROUPS`, `CGROUP_PIDS` e o `cgroup.kill` do 5.14 em diante),
  com a alternativa de grupo de processos registrada no log.
- **O acorde do Fn atrasa o menu do RetroArch para a hora em que o Fn é solto.** É aceito: o
  menu abre ao soltar, o que o usuário quase não nota, e esse atraso é o que impede o menu de
  abrir no Fn+Start.
- **Uma camada `uinput` a mais no GA36 aumenta a latência de entrada.** A mitigação é medir:
  a tarefa 9.4 compara a latência com e sem o daemon. O R36S já usa essa camada hoje.
- **O build Rust sob `qemu-user` é lento.** Mitigação: crates vendorizadas e compiladas uma vez
  por arquitetura (cache em `out/repo/<arch>/`). O cross completo fica para o P-36.
- **Um `gamelist.xml` muito grande pode deixar o scan lento no A33.** Mitigação: o XML só é
  relido quando o mtime dele ou o conjunto de arquivos da pasta mudou. O tempo de scan entra nas
  métricas (tarefa 9.3).
- **O LÖVE pode não estar empacotado para armv7.** Mitigação: um aport local (tarefa 1.3) ou o
  runner só no aarch64, registrado no catálogo por arquitetura.

## Resultados das verificações

### Kernel (tarefa 1.1)

- Os dois kernels são 6.18, então o `cgroup.kill` (5.14 em diante) está no núcleo do cgroup v2.
- `.config` final de 2026-11-14 (`.cache/kbuild/*-302c8ffa02fd6ba8`):
  - R36S: `CGROUPS`, `CGROUP_PIDS` e `MEMCG` ligados pelo defconfig de arm64;
  - GA36: só `CGROUPS`. `CGROUP_PIDS` e `MEMCG` estavam desligados no `sunxi_defconfig`.
- Os três entram nos fragmentos `board/ga36/kernel.config` e `board/r36s/kernel.config`. O build
  falha se algum deles não ficar ligado.

### RetroArch 1.22.2 (tarefa 1.2)

Lido no tarball do `aports/retroarch` (`.cache/distfiles/retroarch-1.22.2.tar.gz`):

- **(a) `-e/--entryslot`:** existe (`retroarch.c`, de 0 a 999) e é ignorado sem conteúdo. Ao
  carregar o conteúdo, `command_event_load_entry_state` procura o arquivo de entrada e, se ele
  não existir, o caminho normal do slot (`runloop_get_savestate_path`). O slot carregado também
  vira o `state_slot` corrente (`runloop.c`, `configuration_set_int`).
- **(b) `--appendconfig` vaza:** `config_save_file` grava o `settings` inteiro no
  `retroarch.cfg` ao sair (`config_save_on_exit = "true"` na configuração de fábrica). Só não
  grava quando há um override ativo (`RUNLOOP_FLAG_OVERRIDES_ACTIVE`). Logo, uma chave do
  `--appendconfig` acaba no arquivo do usuário. O `state_slot` do `-e` vaza do mesmo jeito.
- **(c) `QUIT` não ignora o `quit_press_twice`:** o comando de rede `QUIT` liga o bit
  `RARCH_QUIT_KEY` (`command.h`) e passa pelo mesmo teste da tecla de atalho (`runloop.c`): com
  `quit_press_twice` ligado, o primeiro `QUIT` só mostra "Press again" e o segundo, até 3 s
  depois, fecha. O self-test já desliga a opção por isso. O SIGTERM fecha de forma limpa
  (`frontend_unix_sighandler`: o 1º sinal pede a saída normal, que grava a SRAM).
- **(d) Não há subpasta por core:** com `sort_savestates_by_content_enable = "true"` e
  `sort_savestates_enable = "false"` (chaves fixas de `retroarch-lume.cfg`), o state fica em
  `states/<nome da pasta do conteúdo>/<jogo>.state<N>`, por exemplo `states/snes/`. O nome do
  core (`library_name`) só entra no caminho com `sort_savestates_enable`. O arquivo de state
  também não guarda o core.

### LÖVE e Rust no Alpine 3.24 (tarefa 1.3)

- `love` 11.5-r1 está no `community` para x86_64, armv7 e aarch64, e o `apk` o instala (com
  as 17 dependências) num rootfs vazio de armv7 e de aarch64. Ele entra em `rootfs/packages.txt`
  e não precisa de aport local.
- O Alpine 3.24 traz `rust` e `cargo` 1.96.1 e `sdl2` 2.32.10 nos três alvos. A versão mínima
  do workspace é `rust-version = "1.96"`.

## Migration Plan

1. A imagem nova traz `FRONTEND="lume"`. Cartões existentes não perdem nada:
   - `gamelist.xml` e `ROMS/system/lume/` são criados no primeiro scan;
   - a configuração do RetroArch e os saves não mudam.
2. Os `gamelist.xml` de um cartão vindo do dArkOS são lidos e completados, nunca substituídos.
3. **Rollback:** uma imagem com `FRONTEND="retroarch"` volta ao menu do RetroArch no boot. Os
   arquivos do launcher no cartão ficam lá, sem efeito.
