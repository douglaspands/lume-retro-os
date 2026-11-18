# Mapa de nomes: `r36os` para `lume`

Mapa da tarefa 1.1 da change `device-fixes` (decisão D7 do design). Tudo o que o projeto criou
com o nome `r36os` passa a se chamar `lume`; o que fica como está aparece na última tabela, com o
motivo. **Este arquivo só descreve a troca: nada foi renomeado.** As tarefas 1.2 (console), 1.3
(ferramenta do PC) e 1.4 (documentação, specs e tarefas das outras changes) fazem a troca, uma de
cada vez, e o `tests/unit/test_lume_names.py` fecha na 1.4.

Como ler: cada tabela tem as colunas `Antes | Depois | Tipo` (mais `Observação`). O teste
`tests/unit/test_lume_names.py` lê as tabelas pelo cabeçalho, exige `Antes` único em todo o
arquivo e lista as ocorrências de `r36os` que sobram no repositório fora da tabela `Fica como está`.
Onde o nome está num caminho de pacote (`aports/lume-core/files/usr/libexec/r36os/...`), vale o
caminho instalado da tabela, e a pasta do repositório acompanha (`.../libexec/lume/...`).

Regras gerais (D7): `r36os-<x>` vira `lume-<x>`; `r36os` sozinho vira `lume`; `R36OS_<X>` vira
`LUME_<X>`; `/usr/libexec/r36os`, `/etc/r36os`, `/run/r36os`, `/usr/share/r36os` e
`/usr/lib/r36os` viram o mesmo caminho com `lume`. Nenhum nome muda de sentido, só de prefixo.

## 1. Pacotes (aports e APKs do console)

Os pacotes `lume-*` (`lume-audio`, `lume-core`, `lume-diag`, `lume-games`, `lume-launcher`,
`lume-launcher-data`, `lume-logd`, `lume-net`, `lume-power`, `lume-retroarch-cfg`, `lume-saves`,
`lume-shaders`, `lume-usb`, `lume-bootsel`) já têm o nome novo; só o conteúdo deles ainda usa
`r36os` (tabelas 2 a 7).

| Antes | Depois | Tipo | Observação |
|---|---|---|---|
| `aports/r36os-input` | `aports/lume-input` | aport | pasta inteira: `APKBUILD`, `input.c`, `evrec.c`, `shot.c`, `ga36.conf`, `r36s.conf`, `vm.conf` |
| `r36os-input` | `lume-input` | apk | `pkgname`; `rootfs/packages.txt`, `rootfs/configure.sh`, lista de pacotes do console |
| `aports/r36os-powerctl` | `aports/lume-powerctl` | aport | pasta inteira: `APKBUILD`, `powerctl.c` |
| `r36os-powerctl` | `lume-powerctl` | apk | `pkgname`; `rootfs/packages.txt` |
| `aports/r36os-devmem` | `aports/lume-devmem` | aport | pasta inteira: `APKBUILD`, `devmem.c`; só no GA36 (`board/ga36/hw-packages.txt`) |
| `r36os-devmem` | `lume-devmem` | apk | `pkgname`; binário `/usr/bin/r36os-devmem` na tabela 4 |
| `aports/r36os-initramfs-static` | `aports/lume-initramfs-static` | aport | pasta inteira: só o `APKBUILD` |
| `r36os-initramfs-static` | `lume-initramfs-static` | apk | `pkgname`; `src/r36os/initramfs.py`, `fragment_build.py` (`STAGE1_FRAGMENTS`) |
| `r36os-*` | `lume-*` | grupo | `rootfs/slots.toml`, grupo `lume`: a linha `"r36os-*"` sai (o `"lume-*"` já cobre) |
| `r36os-series.index` | `lume-series.index` | git-pc | índice do git da árvore do kernel em `.cache` (`kernel.py`); refeito sozinho |
| `refs/r36os/applied` | `refs/lume/applied` | git-pc | ref do git da árvore do kernel em `.cache` (`kernel.py`, `APPLIED_REF`) |
| `r36os patches` | `lume patches` | git-pc | mensagem do commit dos patches na árvore do kernel (`kernel.py`) |

## 2. Serviços OpenRC (`/etc/init.d`)

O `push` troca o sistema inteiro, então os serviços antigos somem sozinhos. `rootfs/configure.sh`
(linhas do `rc-update add`) e `rootfs/slots.toml` acompanham.

| Antes | Depois | Tipo | Observação |
|---|---|---|---|
| `/etc/init.d/r36os-audiotest` | `/etc/init.d/lume-audiotest` | servico | `lume-audio`, só no R36S |
| `/etc/init.d/r36os-jack` | `/etc/init.d/lume-jack` | servico | `lume-audio`, só no R36S |
| `/etc/init.d/r36os-mixer` | `/etc/init.d/lume-mixer` | servico | `lume-audio` |
| `/etc/init.d/r36os-logd` | `/etc/init.d/lume-logd` | servico | `lume-core`; o pacote `lume-logd` (daemon em C) já tem o nome |
| `/etc/init.d/r36os-hwsummary` | `/etc/init.d/lume-hwsummary` | servico | `lume-diag` |
| `/etc/init.d/r36os-selftest` | `/etc/init.d/lume-selftest` | servico | `lume-diag`; a chave `service-r36os-jack` do selftest vira `service-lume-jack` |
| `/etc/init.d/r36os-playlists` | `/etc/init.d/lume-playlists` | servico | `lume-games` |
| `/etc/init.d/r36os-hostshare` | `/etc/init.d/lume-hostshare` | servico | `lume-net`, só na `vm` |
| `/etc/init.d/r36os-ssh-wifi` | `/etc/init.d/lume-ssh-wifi` | servico | `lume-net` |
| `/etc/init.d/r36os-vmnet` | `/etc/init.d/lume-vmnet` | servico | `lume-net`, só na `vm` |
| `/etc/init.d/r36os-power` | `/etc/init.d/lume-power` | servico | `lume-power`; o pacote já se chama `lume-power` |
| `/etc/init.d/r36os-zram` | `/etc/init.d/lume-zram` | servico | `lume-power` |
| `/etc/init.d/r36os-persist` | `/etc/init.d/lume-persist` | servico | `lume-saves` |
| `/etc/init.d/r36os-savesync` | `/etc/init.d/lume-savesync` | servico | `lume-saves` |
| `/etc/init.d/r36os-usb` | `/etc/init.d/lume-usb` | servico | `lume-usb`; o pacote já se chama `lume-usb` |
| `/etc/init.d/r36os-input` | `/etc/init.d/lume-input` | servico | origem `aports/r36os-input/r36os-input.initd` |
| `r36os-input.initd` | `lume-input.initd` | arquivo | arquivo do `aports/lume-input/` que o `APKBUILD` instala |
| `/run/r36os-logd.pid` | `/run/lume-logd.pid` | pidfile | `pidfile=` do serviço e o `selftest` |
| `/run/r36os-persist.pid` | `/run/lume-persist.pid` | pidfile | serviço `persist` |
| `/run/r36os-savesync.pid` | `/run/lume-savesync.pid` | pidfile | serviço `savesync` |
| `/run/r36os-selftest.pid` | `/run/lume-selftest.pid` | pidfile | serviço `selftest` |
| `r36os-session` | `lume-session` | rotulo | só nome em comentários e mensagens para `/usr/libexec/r36os/session` (não existe binário com esse nome) |
| `r36os-padmerge` | `lume-padmerge` | rotulo | nome histórico em comentários (substituído pelo `r36os-input`); nenhum arquivo |

## 3. Udev, sysctl, initramfs e inittab

| Antes | Depois | Tipo | Observação |
|---|---|---|---|
| `61-r36os-input.rules` | `61-lume-input.rules` | udev | arquivo em `aports/r36os-input/` |
| `/usr/lib/udev/rules.d/61-r36os-input.rules` | `/usr/lib/udev/rules.d/61-lume-input.rules` | udev | caminho instalado pelo `APKBUILD` |
| `/etc/sysctl.d/r36os-zram.conf` | `/etc/sysctl.d/lume-zram.conf` | sysctl | `lume-power`; o `00-alpine.conf` vizinho não muda |
| `/usr/lib/r36os/initramfs/bin` | `/usr/lib/lume/initramfs/bin` | initramfs | onde `lume-initramfs-static` e `lume-bootsel` instalam os binários estáticos (`initramfs.py` copia dali) |
| `r36os-initramfs` | `lume-initramfs` | pasta-build | pasta de montagem do initramfs do kernel (`kernel.py`) |
| `/newroot/usr/share/r36os/systems.json` | `/newroot/usr/share/lume/systems.json` | initramfs | `initramfs/init` (cria as pastas de ROMS a partir do catálogo) |
| `/newroot/usr/share/r36os/LEIA-ME.txt` | `/newroot/usr/share/lume/LEIA-ME.txt` | initramfs | `initramfs/init` (copia para o cartão) |
| `:/usr/libexec/r36os/rc-tee` | `:/usr/libexec/lume/rc-tee` | inittab | `rootfs/configure.sh` (sed no `/etc/inittab`) |
| `::once:/usr/libexec/r36os/bootlog` | `::once:/usr/libexec/lume/bootlog` | inittab | `rootfs/configure.sh` (linha acrescentada ao `/etc/inittab`) |

O initramfs em si (`initramfs/init`, `lib/slots.sh`, `lib/storage.sh`) só cita `r36os` nos dois
caminhos de `/usr/share` acima, numa mensagem de erro (`r36os flash --full`) e num comentário
(`src/r36os/manifests.py`); nenhum arquivo dele tem o nome no caminho.

## 4. Ferramentas (`/usr/bin`)

| Antes | Depois | Tipo | Observação |
|---|---|---|---|
| `/usr/bin/r36os-power` | `/usr/bin/lume-power` | ferramenta | `lume-power` (serviço de perfis de energia) |
| `/usr/bin/r36os-playlists` | `/usr/bin/lume-playlists` | ferramenta | `lume-games` |
| `/usr/bin/r36os-input` | `/usr/bin/lume-input` | ferramenta | `lume-input` (daemon do gamepad virtual) |
| `/usr/bin/r36os-evrec` | `/usr/bin/lume-evrec` | ferramenta | `lume-input` (gravador de eventos; `src/r36os/evrec.py` e `dev.py` o chamam) |
| `/usr/bin/r36os-shot` | `/usr/bin/lume-shot` | ferramenta | `lume-input` (captura de tela; usado por `r36os dev shot`, `lume-ui` e `lume-menu`) |
| `/usr/bin/r36os-powerctl` | `/usr/bin/lume-powerctl` | ferramenta | `lume-powerctl` (controlador de carga) |
| `/usr/bin/r36os-devmem` | `/usr/bin/lume-devmem` | ferramenta | `lume-devmem` (só GA36; `scripts/dev/exit-timeline.sh`, `hwinfo` e `logd` o chamam) |
| `r36os-devmem-1.0-r0.apk` | `lume-devmem-1.0-r0.apk` | apk | só em fixtures de teste (`tests/unit/test_fragments.py`) |
| `/tmp/r36os-shot.png` | `/tmp/lume-shot.png` | arquivo-temp | saída padrão do `shot` no console (`shot.c`, `dev.py`) |

## 5. `/usr/libexec/r36os`

Pasta inteira vira `/usr/libexec/lume`; os nomes dos arquivos não mudam. Hoje não existe
`/usr/libexec/lume` (conferido), então não há colisão.

| Antes | Depois | Tipo | Observação |
|---|---|---|---|
| `/usr/libexec/r36os` | `/usr/libexec/lume` | pasta | raiz; no repositório `aports/*/files/usr/libexec/r36os` vira `.../libexec/lume` |
| `/usr/libexec/r36os/bootlog` | `/usr/libexec/lume/bootlog` | libexec | `lume-core` |
| `/usr/libexec/r36os/frontends` | `/usr/libexec/lume/frontends` | pasta | `frontend` em `/etc/conf.d/frontend`, `lume-run`, `lume-ui` e o catálogo de runners citam o caminho |
| `/usr/libexec/r36os/frontends/lume` | `/usr/libexec/lume/frontends/lume` | libexec | `lume-core` |
| `/usr/libexec/r36os/frontends/retroarch` | `/usr/libexec/lume/frontends/retroarch` | libexec | `lume-core`; `aports/lume-games/.../runners.d/retroarch.toml`, `lume-core/src/runner.rs`, `lume-run/src/launch.rs`, `lume-ui/src/launch.rs` |
| `/usr/libexec/r36os/frontends/failing` | `/usr/libexec/lume/frontends/failing` | libexec-teste | criado pelo `selftest` para provar o laço de reinício |
| `/usr/libexec/r36os/frontends/fake` | `/usr/libexec/lume/frontends/fake` | libexec-teste | criado pelo `selftest` |
| `/usr/libexec/r36os/frontends/meufrontend` | `/usr/libexec/lume/frontends/meufrontend` | doc | exemplo em `docs/FRONTEND.md` |
| `/usr/libexec/r36os/lib.sh` | `/usr/libexec/lume/lib.sh` | libexec | `lume-core`; lida por quase todos os scripts (`. /usr/libexec/r36os/lib.sh`) |
| `/usr/libexec/r36os/logd` | `/usr/libexec/lume/logd` | libexec | `lume-core` (script do serviço `logd`) |
| `/usr/libexec/r36os/logs.sh` | `/usr/libexec/lume/logs.sh` | libexec | `lume-core` |
| `/usr/libexec/r36os/rc-tee` | `/usr/libexec/lume/rc-tee` | libexec | `lume-core` |
| `/usr/libexec/r36os/session` | `/usr/libexec/lume/session` | libexec | `lume-core`; o serviço `frontend` o chama |
| `/usr/libexec/r36os/audiotest` | `/usr/libexec/lume/audiotest` | libexec | `lume-audio` |
| `/usr/libexec/r36os/jack` | `/usr/libexec/lume/jack` | libexec | `lume-audio` |
| `/usr/libexec/r36os/mixer` | `/usr/libexec/lume/mixer` | libexec | `lume-audio` |
| `/usr/libexec/r36os/hwinfo` | `/usr/libexec/lume/hwinfo` | libexec | `lume-diag` |
| `/usr/libexec/r36os/hwsummary` | `/usr/libexec/lume/hwsummary` | libexec | `lume-diag` |
| `/usr/libexec/r36os/selftest` | `/usr/libexec/lume/selftest` | libexec | `lume-diag` |
| `/usr/libexec/r36os/selftest-device` | `/usr/libexec/lume/selftest-device` | libexec | `lume-diag` |
| `/usr/libexec/r36os/ssh-wifi` | `/usr/libexec/lume/ssh-wifi` | libexec | `lume-net` |
| `/usr/libexec/r36os/ssh-wifi.` | `/usr/libexec/lume/ssh-wifi.` | libexec | prefixo `ssh-wifi.<n>` de arquivos auxiliares citado no serviço |
| `/usr/libexec/r36os/vm-net` | `/usr/libexec/lume/vm-net` | libexec | `lume-net` |
| `/usr/libexec/r36os/power-profiles.sh` | `/usr/libexec/lume/power-profiles.sh` | libexec | `lume-power` |
| `/usr/libexec/r36os/zram` | `/usr/libexec/lume/zram` | libexec | `lume-power` |
| `/usr/libexec/r36os/persist` | `/usr/libexec/lume/persist` | libexec | `lume-saves` |
| `/usr/libexec/r36os/persist-event` | `/usr/libexec/lume/persist-event` | libexec | `lume-saves` |
| `/usr/libexec/r36os/savesync` | `/usr/libexec/lume/savesync` | libexec | `lume-saves` |
| `/usr/libexec/r36os/savesync-event` | `/usr/libexec/lume/savesync-event` | libexec | `lume-saves` |
| `/usr/libexec/r36os/usb-gadget` | `/usr/libexec/lume/usb-gadget` | libexec | `lume-usb` |
| `/usr/libexec/r36os/usb-storage` | `/usr/libexec/lume/usb-storage` | libexec | `lume-usb`; a regra do udev `90-lume-usb-storage.rules` o chama |
| `r36os-usb-storage` | `lume-usb-storage` | rotulo | nome de log/mensagem do script `usb-storage` |
| `r36os-audiotest` | `lume-audiotest` | rotulo | nome do serviço citado em mensagens (a linha do serviço está na tabela 2) |
| `r36os-hostshare` | `lume-hostshare` | rotulo | nome do serviço em mensagens e no `selftest` (a linha do serviço está na tabela 2) |
| `r36os-vmnet` | `lume-vmnet` | rotulo | idem |
| `r36os-zram` | `lume-zram` | rotulo | idem |
| `r36os-ssh-wifi` | `lume-ssh-wifi` | rotulo | idem; `lume-core/src/settings.rs`, `lume-ui/src/app.rs` e `system.rs` citam o serviço |
| `r36os-logd` | `lume-logd` | rotulo | idem; `lume-run/src/main.rs`, comentários do `retroarch` e do `lume-bootsel` |
| `r36os-hwsummary` | `lume-hwsummary` | rotulo | idem |
| `r36os-playlists` | `lume-playlists` | rotulo | idem |
| `r36os-persist` | `lume-persist` | rotulo | idem |
| `r36os-savesync` | `lume-savesync` | rotulo | idem |
| `r36os-selftest` | `lume-selftest` | rotulo | idem |
| `r36os-usb` | `lume-usb` | rotulo | idem |
| `r36os-jack` | `lume-jack` | rotulo | idem |
| `r36os-mixer` | `lume-mixer` | rotulo | idem |
| `r36os-power` | `lume-power` | rotulo | idem |

## 6. `/usr/share/r36os` e colisões com `/usr/share/lume`

Origem dos arquivos de cada pasta, conferida pacote a pacote (arquivos instalados pelos
`APKBUILD` e pelo `rootfs/configure.sh`):

- `/usr/share/lume` hoje recebe: `lume-games` (`runners.d/love.toml`, `runners.d/retroarch.toml`,
  `runners.d/sh.toml`), `lume-launcher-data` (`LEIA-ME-temas.txt`, `i18n/{en,es,pt}.toml`,
  `theme-template/_lume-original/theme.toml`, `themes/base.toml`,
  `themes/{lume,material-dark,material-light}/theme.toml`), `lume-power`
  (`power/ga36.conf`, `power/r36s.conf`) e `lume-launcher` (`fonts/*.ttf`, as três
  Roboto).
- `/usr/share/r36os` hoje recebe: `lume-games` (`systems.json`), `lume-retroarch-cfg`
  (`retroarch-lume.cfg`, `retroarch-ga36.cfg`, `retroarch-r36s.cfg`, `retroarch-core.keys`,
  `factory/retroarch/retroarch.cfg`), `r36os-input` (`input/ga36.conf`, `input/r36s.conf`,
  `input/vm.conf`), `rootfs/configure.sh` (`libretro-info/*.info`) e `src/r36os/rootfs.py`
  (`LEIA-ME.txt`).

**Resultado: nenhuma colisão de arquivo.** Nenhum caminho relativo existe nas duas pastas
(`systems.json`, `retroarch-*`, `factory/`, `input/`, `libretro-info/` e `LEIA-ME.txt` contra
`runners.d/`, `i18n/`, `themes/`, `theme-template/`, `power/`, `fonts/` e `LEIA-ME-temas.txt`).
Parecidos, mas distintos: `LEIA-ME.txt` (leia-me do cartão) e `LEIA-ME-temas.txt` (guia de
temas); `power/` (perfis de energia) e `input/` (perfis de teclas e mixer). A 1.2 só junta as
pastas; se um nome novo vier a colidir, o teste de pacotes (`test_aports.py`) o acusa. Como o
`lume-core/src/paths.rs` já usa `LUME_SHARE` (`/usr/share/lume`) para os dados do launcher e
`LUME_CATALOG` (`/usr/share/r36os/systems.json`) para o catálogo, o catálogo passa a
`/usr/share/lume/systems.json` e `LUME_SHARE` serve aos dois.

| Antes | Depois | Tipo | Observação |
|---|---|---|---|
| `/usr/share/r36os` | `/usr/share/lume` | pasta | pasta existe dos dois lados; sem colisão de arquivo (acima); no repositório `aports/*/files/usr/share/r36os` |
| `/usr/share/r36os/systems.json` | `/usr/share/lume/systems.json` | share | `lume-games`; `catalog.py`, `flash.py`, `dev_game.py`, `lume-core/src/paths.rs` (`LUME_CATALOG`), testes em Rust |
| `/usr/share/r36os/retroarch-lume.cfg` | `/usr/share/lume/retroarch-lume.cfg` | share | `lume-retroarch-cfg` |
| `/usr/share/r36os/retroarch-ga36.cfg` | `/usr/share/lume/retroarch-ga36.cfg` | share | idem |
| `/usr/share/r36os/retroarch-r36s.cfg` | `/usr/share/lume/retroarch-r36s.cfg` | share | idem |
| `/usr/share/r36os/retroarch-core.keys` | `/usr/share/lume/retroarch-core.keys` | share | idem; lido pelo `frontends/retroarch` |
| `/usr/share/r36os/retroarch-` | `/usr/share/lume/retroarch-` | share | prefixo `retroarch-<placa>.cfg` do `APKBUILD` |
| `/usr/share/r36os/factory` | `/usr/share/lume/factory` | share | pasta `factory/` (`flash.py` a usa para o primeiro cartão) |
| `/usr/share/r36os/factory/retroarch` | `/usr/share/lume/factory/retroarch` | share | pasta do `persist` (`PERSIST_FACTORY`) |
| `/usr/share/r36os/factory/retroarch/retroarch.cfg` | `/usr/share/lume/factory/retroarch/retroarch.cfg` | share | semente do `retroarch.cfg`; `rootfs.py` a ajusta (idioma) |
| `/usr/share/r36os/input/` | `/usr/share/lume/input/` | share | pasta; instalada por `lume-input`; `lume-ui/src/system.rs` e `input.c` leem |
| `/usr/share/r36os/input/ga36.conf` | `/usr/share/lume/input/ga36.conf` | share | `lume-input` |
| `/usr/share/r36os/input/r36s.conf` | `/usr/share/lume/input/r36s.conf` | share | `lume-input` |
| `/usr/share/r36os/input/.` | `/usr/share/lume/input/.` | share | glob do `APKBUILD` (perfis por placa, incluindo `vm.conf`) |
| `/usr/share/r36os/libretro-info` | `/usr/share/lume/libretro-info` | share | `rootfs/configure.sh`; o `retroarch-lume.cfg` aponta `libretro_info_path` para ele |
| `/usr/share/r36os/libretro-info/` | `/usr/share/lume/libretro-info/` | share | idem, com a barra final |
| `/usr/share/r36os/LEIA-ME.txt` | `/usr/share/lume/LEIA-ME.txt` | share | gerado por `rootfs.py` a partir de `leiame.py` |
| `/usr/share/r36os/hello` | `/usr/share/lume/hello` | fixture | pacote de teste `r36os-hello` |
| `/usr/share/r36os/greeting` | `/usr/share/lume/greeting` | fixture | pacote de teste `r36os-hello-arch` |
| `/usr/share/r36os/proof-push-boot-swap` | `/usr/share/lume/proof-push-boot-swap` | prova | arquivo marcador citado só em `openspec/changes/r36s-usb-proof/tasks.md` (1.4) |

## 7. `/etc/r36os` e `/run/r36os`

Hoje não existem `/etc/lume` nem `/run/lume` (conferido): sem colisão.

| Antes | Depois | Tipo | Observação |
|---|---|---|---|
| `/etc/r36os` | `/etc/lume` | pasta | gravada por `rootfs/configure.sh` e `rootfs.py` |
| `/etc/r36os/board` | `/etc/lume/board` | etc | nome da placa (`ga36`, `r36s`, `vm`); lido por scripts e por `lume-ui` |
| `/etc/r36os/serial-tty` | `/etc/lume/serial-tty` | etc | `rc-tee`, `session` |
| `/etc/r36os/language` | `/etc/lume/language` | etc | gravado por `rootfs.py` (idioma de fábrica) |
| `/run/r36os` | `/run/lume` | pasta | RAM; `LUME_RUN` no lugar de `R36OS_RUN` (tabela 8) |
| `/run/r36os/` | `/run/lume/` | run | pasta citada com barra final |
| `/run/r36os/input.sock` | `/run/lume/input.sock` | run | socket do `lume-input` (`input.c`, `lume-core/src/input.rs`, `lume-run`, `lume-ui`) |
| `/run/r36os/hud` | `/run/lume/hud` | run | `lume-run/src/hud.rs` |
| `/run/r36os/power` | `/run/lume/power` | run | pasta do perfil de energia (`lume-core/src/power.rs`, `lume-power`) |
| `/run/r36os/power.` | `/run/lume/power.` | run | prefixo `power.<x>` no serviço de energia |
| `/run/r36os/power.default` | `/run/lume/power.default` | run | arquivo de estado do serviço de energia |
| `/run/r36os/power.early` | `/run/lume/power.early` | run | idem |
| `/run/r36os/power.manual` | `/run/lume/power.manual` | run | idem |
| `/run/r36os/power.state` | `/run/lume/power.state` | run | `lume-core/src/powerstate.rs`, `lume-power`, `power-profiles.sh` |
| `/run/r36os/powerctl.state` | `/run/lume/powerctl.state` | run | `lume-powerctl` |
| `/run/r36os/powerctl.out` | `/run/lume/powerctl.out` | run | idem |
| `/run/r36os/logs` | `/run/lume/logs` | run | RAM dos logs (`lume-logd`, `logd.c`, `lume-core/src/events.rs`) |
| `/run/r36os/logs/` | `/run/lume/logs/` | run | idem, com a barra final |
| `/run/r36os/logs/boot-n` | `/run/lume/logs/boot-n` | run | forma citada em `docs/LOGS.md` |
| `/run/r36os/logs/boot/boot-` | `/run/lume/logs/boot/boot-` | run | `push.py`, `dev.py` leem o log do boot |
| `/run/r36os/logs/events.pending` | `/run/lume/logs/events.pending` | run | `dev_run.py`, `docs/BUILD.md` |
| `/run/r36os/retroarch-extra.cfg` | `/run/lume/retroarch-extra.cfg` | run | `frontends/retroarch` (`LUME_EXTRA_CFG`), `selftest` |
| `/run/r36os/evrec` | `/run/lume/evrec` | run | gravação de eventos (`dev.py`) |
| `/run/r36os/evrec/` | `/run/lume/evrec/` | run | idem |
| `/run/r36os/evrec/current.evrec` | `/run/lume/evrec/current.evrec` | run | `dev.py`, `test_dev_record.py` |
| `/run/r36os/hwsummary` | `/run/lume/hwsummary` | run | citado no `motd` |
| `/run/r36os/usb` | `/run/lume/usb` | run | `usb-gadget` |
| `/run/r36os/usb/umtprd.log` | `/run/lume/usb/umtprd.log` | run | citado em `docs/BRINGUP-GA36.md` |
| `/run/r36os/testdata` | `/run/lume/testdata` | run | `selftest` (disco `TESTDATA`) |
| `/run/r36os/testdata/fail-service` | `/run/lume/testdata/fail-service` | run | `selftest` |
| `run/r36os/logs` | `run/lume/logs` | run | sem a barra inicial, em `tests/unit/test_dev.py` |

## 8. Variáveis `R36OS_*`

Todas viram `LUME_*` (mesmo sufixo). Nenhuma já tem o nome novo (conferido: `LUME_*` existentes
são outras: `LUME_CATALOG`, `LUME_SHARE`, `LUME_FONT*`, `LUME_RESTORE`, `LUME_LEVEL`), então não
há colisão. As do PC (`R36OS_OUT`, `R36OS_CACHE`, `R36OS_JOBS` etc.) trocam de nome de uma vez,
sem aceitar o nome antigo (decisão do usuário, 2026-11-18, Q4): quem as exporta no shell troca
o nome junto.

| Antes | Depois | Tipo | Observação |
|---|---|---|---|
| `R36OS_RUN` | `LUME_RUN` | var-console | `/run/r36os` nos scripts do console e nos testes (muda o valor padrão junto) |
| `R36OS_LIBDIR` | `LUME_LIBDIR` | var-console | `selftest-device`, `tests/selftest` |
| `R36OS_SHARE` | `LUME_SHARE` | var-console | `frontends/retroarch` (`/usr/share/r36os`). **Já existe `LUME_SHARE`** em `lume-core/src/paths.rs` (`/usr/share/lume`): com a pasta única as duas viram uma só |
| `R36OS_EXTRA_CFG` | `LUME_EXTRA_CFG` | var-console | `frontends/retroarch`, `test_retroarch_cfg.py` |
| `R36OS_MERGE_ONLY` | `LUME_MERGE_ONLY` | var-console | `frontends/retroarch` (só nos testes) |
| `R36OS_DEVMEM` | `LUME_DEVMEM` | var-console | `hwinfo`, `tests/logs/test_logs.sh` |
| `R36OS_INPUT_AMIXER` | `LUME_INPUT_AMIXER` | var-console | `input.c`, `test_r36os_input.py` |
| `R36OS_INPUT_BACKLIGHT` | `LUME_INPUT_BACKLIGHT` | var-console | idem |
| `R36OS_INPUT_RA_PORT` | `LUME_INPUT_RA_PORT` | var-console | idem |
| `R36OS_INPUT_LEVEL_COLORS` | `LUME_INPUT_LEVEL_COLORS` | var-console | idem |
| `R36OS_EVREC_DEVICES` | `LUME_EVREC_DEVICES` | var-console | `evrec.c`, `docs/BUILD.md`, `test_r36os_evrec.py` |
| `R36OS_EVREC_INPUT_DIR` | `LUME_EVREC_INPUT_DIR` | var-console | idem |
| `R36OS_EVREC_CLOCK` | `LUME_EVREC_CLOCK` | var-console | idem |
| `R36OS_OUT` | `LUME_OUT` | var-pc | pasta `out/` (`paths.py`) |
| `R36OS_CACHE` | `LUME_CACHE` | var-pc | pasta do cache (`paths.py`); ver `.cache/r36os` na tabela 10 |
| `R36OS_JOBS` | `LUME_JOBS` | var-pc | `jobs.py`, `docs/BUILD.md`, spec `build-performance` |
| `R36OS_DISTCC` | `LUME_DISTCC` | var-pc | `distcc.py`, `packages.py` |
| `R36OS_CCACHE` | `LUME_CCACHE` | var-pc | `packages.py` |
| `R36OS_LUME_CROSS` | `LUME_CROSS` | var-pc | `lume_cross.py`. Vira `LUME_CROSS`, sem repetir o `LUME` |
| `R36OS_SSH_MUX` | `LUME_SSH_MUX` | var-pc | `sshmux.py`, `push.py`, `conftest.py` |
| `R36OS_SSH_DIR` | `LUME_SSH_DIR` | var-pc | idem |
| `R36OS_TEMP_SENSOR` | `LUME_TEMP_SENSOR` | var-pc | `heat.py` |
| `R36OS_TEMP_MAX` | `LUME_TEMP_MAX` | var-pc | `heat.py` |
| `R36OS_TEMP_GUARD` | `LUME_TEMP_GUARD` | var-pc | `heat.py`, `cli.py` |
| `R36OS_GA36_FACTORY` | `LUME_GA36_FACTORY` | var-pc | **usada em código** (`src/r36os/vendor.py:36`, `ENV_VAR`): só o nome novo (ver a nota abaixo) |
| `R36OS_R36S_FACTORY` | `LUME_R36S_FACTORY` | var-pc | **usada em código** (`src/r36os/r36s_vendor.py:34`, `ENV_VAR`), mesma regra |
| `r36os_jobs` | `lume_jobs` | identificador | nome da `ContextVar` em `jobs.py` |
| `r36os_pipeline` | `lume_pipeline` | identificador | nome da `ContextVar` em `parallel.py` |

**`R36OS_GA36_FACTORY` e `R36OS_R36S_FACTORY`.** O design deixa o nome da *área de fábrica do
GA36* (o arquivo fora do git) como está e só renomeia se houver uso em código. **Há uso em
código** nos dois módulos de vendor (`ENV_VAR`), e o mesmo vale para a variável irmã do R36S.
Decisão do usuário (2026-11-18, "tudo padronizado"): a 1.3 troca para `LUME_GA36_FACTORY` e
`LUME_R36S_FACTORY` sem alias, como as outras variáveis do PC. O arquivo de fábrica no disco do
usuário (fora do git) passa a ser apontado pelo nome novo da variável.

## 9. Ferramenta do PC (`src/r36os`, comando `r36os`)

| Antes | Depois | Tipo | Observação |
|---|---|---|---|
| `r36os` | `lume` | comando | comando do PC (`.venv/bin/r36os`, `uv run r36os`, `prog="r36os"` em `cli.py`); o mesmo nome aparece como rótulo em `change-status/status.py` |
| `src/r36os` | `src/lume_tool` | pacote-pc | pasta do pacote Python, todos os módulos (`git mv` da pasta) |
| `src/r36os/` | `src/lume_tool/` | pacote-pc | com a barra final |
| `r36os.cli` | `lume_tool.cli` | import | `pyproject.toml`: `[project.scripts]` |
| `r36os = "r36os.cli:main"` | `lume = "lume_tool.cli:main"` | pyproject | entrada de comando em `pyproject.toml` (e o pacote a empacotar em `[tool.*]`, se houver) |
| `name = "r36os"` | `name = "lume-tool"` | pyproject | nome do projeto; o `uv.lock` é refeito com `uv sync --inexact` (a linha `name = "r36os"` do lock muda junto) |
| `src/r36os/lume.py` | `src/lume_tool/launcher_stage.py` | modulo-pc | **o módulo `lume.py` de hoje** (prepara os fontes do `lume-launcher` para o `abuild`: `stage()`, `ensure_vendor()`) ganha outro nome para não ser confundido com o pacote/comando `lume`. Proposta: `launcher_stage` |
| `r36os.lume` | `lume_tool.launcher_stage` | import | importado por `packages.py`, `lume_cross.py`, `tests/unit/test_lume_stage.py` |
| `r36os.lume.stage` | `lume_tool.launcher_stage.stage` | import | citado em `aports/lume-launcher/APKBUILD` e `.gitignore` |
| `r36os.lume_cross` | `lume_tool.lume_cross` | import | `lume_cross.py` mantém o nome (já não tem `r36os`) |
| `r36os.archive` | `lume_tool.archive` | import | os demais módulos seguem a mesma regra: só o prefixo do pacote muda (linhas abaixo) |
| `r36os.build` | `lume_tool.build` | import | |
| `r36os.catalog` | `lume_tool.catalog` | import | citado também em comentários do `lume-core` (`r36os.catalog.validate_runner`, `r36os.catalog.emulators`) |
| `r36os.catalog.validate` | `lume_tool.catalog.validate` | import | `docs/CATALOG.md` |
| `r36os.catalog.validate_runner` | `lume_tool.catalog.validate_runner` | import | comentário em `lume-core/src/runner.rs` |
| `r36os.catalog.emulators` | `lume_tool.catalog.emulators` | import | `docs/CATALOG.md`, `lume-core/src/catalog.rs` |
| `r36os.clean` | `lume_tool.clean` | import | |
| `r36os.container` | `lume_tool.container` | import | |
| `r36os.dev` | `lume_tool.dev` | import | |
| `r36os.dev_game` | `lume_tool.dev_game` | import | |
| `r36os.dev_run` | `lume_tool.dev_run` | import | |
| `r36os.dev_watch` | `lume_tool.dev_watch` | import | |
| `r36os.distcc` | `lume_tool.distcc` | import | |
| `r36os.flash` | `lume_tool.flash` | import | |
| `r36os.heat` | `lume_tool.heat` | import | |
| `r36os.image` | `lume_tool.image` | import | |
| `r36os.initramfs` | `lume_tool.initramfs` | import | |
| `r36os.jobs` | `lume_tool.jobs` | import | |
| `r36os.kernel` | `lume_tool.kernel` | import | |
| `r36os.kernel.build_dtbs` | `lume_tool.kernel.build_dtbs` | import | testes de DTS |
| `r36os.lang` | `lume_tool.lang` | import | comentário em `lume-core/src/settings.rs` |
| `r36os.manifests` | `lume_tool.manifests` | import | |
| `r36os.packages` | `lume_tool.packages` | import | |
| `r36os.parallel` | `lume_tool.parallel` | import | |
| `r36os.paths` | `lume_tool.paths` | import | 91 arquivos (scripts, testes, módulos) |
| `r36os.power_report` | `lume_tool.power_report` | import | |
| `r36os.push` | `lume_tool.push` | import | |
| `r36os.push_hot` | `lume_tool.push_hot` | import | |
| `r36os.qmp` | `lume_tool.qmp` | import | |
| `r36os.release` | `lume_tool.release` | import | |
| `r36os.rootfs` | `lume_tool.rootfs` | import | |
| `r36os.scripts` | `lume_tool.scripts` | import | |
| `r36os.scripts.` | `lume_tool.scripts.` | import | prefixo citado em `dev_run.py` |
| `r36os.selftest` | `lume_tool.selftest` | import | |
| `r36os.shots` | `lume_tool.shots` | import | |
| `r36os.slots` | `lume_tool.slots` | import | |
| `r36os.sshmux` | `lume_tool.sshmux` | import | |
| `r36os.stage_inputs` | `lume_tool.stage_inputs` | import | |
| `r36os.stages` | `lume_tool.stages` | import | |
| `r36os.targets` | `lume_tool.targets` | import | |
| `r36os.vendor_dtb` | `lume_tool.vendor_dtb` | import | |
| `r36os.vendor_dtb.default_sources` | `lume_tool.vendor_dtb.default_sources` | import | `cli.py` (texto de ajuda) |
| `r36os.vendor.ANDROID_BOOT_SECTOR` | `lume_tool.vendor.ANDROID_BOOT_SECTOR` | import | `push.py` (comentário) |
| `r36os.version` | `lume_tool.version` | import | |
| `r36os.vm` | `lume_tool.vm` | import | |
| `r36os/kernel.py` | `lume_tool/kernel.py` | caminho | citado na mensagem de erro `KERNEL_RELEASE_DATES in r36os/kernel.py` |
| `src/r36os/bootarea.py` | `src/lume_tool/bootarea.py` | caminho | citado em `docs/BRINGUP-R36S.md`, `PENDENCIAS.md` |
| `src/r36os/bootimg.py` | `src/lume_tool/bootimg.py` | caminho | citado em `lume-bootsel.c` |
| `src/r36os/cli.py` | `src/lume_tool/cli.py` | caminho | |
| `src/r36os/clean.py` | `src/lume_tool/clean.py` | caminho | skills `repo-clean` |
| `src/r36os/dev.py` | `src/lume_tool/dev.py` | caminho | |
| `src/r36os/dev_game.py` | `src/lume_tool/dev_game.py` | caminho | |
| `src/r36os/dev_run.py` | `src/lume_tool/dev_run.py` | caminho | |
| `src/r36os/distcc.py` | `src/lume_tool/distcc.py` | caminho | |
| `src/r36os/evrec.py` | `src/lume_tool/evrec.py` | caminho | |
| `src/r36os/flash.py` | `src/lume_tool/flash.py` | caminho | |
| `src/r36os/jobs.py` | `src/lume_tool/jobs.py` | caminho | |
| `src/r36os/leiame.py` | `src/lume_tool/leiame.py` | caminho | |
| `src/r36os/manifests.py` | `src/lume_tool/manifests.py` | caminho | comentário em `initramfs/lib/slots.sh` |
| `src/r36os/power_report.py` | `src/lume_tool/power_report.py` | caminho | |
| `src/r36os/push.py` | `src/lume_tool/push.py` | caminho | |
| `src/r36os/r36s_vendor.py` | `src/lume_tool/r36s_vendor.py` | caminho | |
| `src/r36os/scripts.py` | `src/lume_tool/scripts.py` | caminho | |
| `src/r36os/stage_inputs.py` | `src/lume_tool/stage_inputs.py` | caminho | |
| `src/r36os/testdata.py` | `src/lume_tool/testdata.py` | caminho | |
| `src/r36os/vendor_dtb.py` | `src/lume_tool/vendor_dtb.py` | caminho | |
| `.venv/bin/r36os` | `.venv/bin/lume` | comando | caminho do executável no venv (README, `docs/BRINGUP-*.md`, `policy.toml`, `.claude/settings`) |
| `bin/r36os` | `bin/lume` | comando | reconhecimento de processos no `.claude/skills/change-status/status.py` |
| `r36os-heat` | `lume-heat` | rotulo | nome da thread do guarda de calor (`heat.py`) |
| `r36os.build=1` | `lume.build=1` | rotulo-container | rótulo dos containers de build (`heat.py`, `BUILD_LABEL`); o guarda de calor acha os containers por ele. Containers antigos ainda rodando na hora da troca ficam sem proteção até acabarem: fazer a troca sem build em andamento |
| `r36os.selftest=1` | `lume.selftest=1` | cmdline | parâmetro do kernel da `vm` (selftest, `vm.py`, `selftest.py`, `lume-selftest`); só existe na linha de comando da `vm` |
| `r36os-test-vm` | `lume-test-vm` | container | nome do container do `test-vm` (`selftest.py`) |
| `r36os-distccd-` | `lume-distccd-` | container | prefixo do container do `distcc` (`distcc.py`) |
| `r36os-builder` | `lume-builder` | imagem | imagem `localhost/r36os-builder:<arch>` (`container.py`, `containers/cross-gcc.sh`, `distcc.py`) |
| `localhost/r36os-builder` | `localhost/lume-builder` | imagem | idem, com o `localhost/` |
| `r36os-cross` | `lume-cross` | imagem | imagem `localhost/r36os-cross` |
| `localhost/r36os-cross` | `localhost/lume-cross` | imagem | idem |
| `localhost/r36os-distcc` | `localhost/lume-distcc` | imagem | `distcc.py`, `test_distcc.py` |
| `localhost/r36os-vm` | `localhost/lume-vm` | imagem | `vm.py`, `test_vm_args.py` |
| `PACKAGER="r36os <r36os@localhost>"` | `PACKAGER="lume <lume@localhost>"` | containerfile | `containers/builder.Containerfile` (identidade do abuild; não muda o nome da chave) |
| `r36os@localhost` | `lume@localhost` | identidade | e-mail (e nome `r36os`, que vira `lume`) dos commits internos da árvore do kernel em `kernel.py` (`GIT_AUTHOR_*`, `GIT_COMMITTER_*`) |
| `.r36os-ready` | `.lume-ready` | arquivo-pc | carimbo da árvore do U-Boot em `.cache` (`uboot.py`); refeito se faltar |
| `/.cache/r36os` | `/.cache/lume` | cache-pc | **pasta de cache do PC** (`$XDG_CACHE_HOME/r36os`, ou `<repo>/.cache/r36os`); README e spec `build-cache`. Ver a pergunta Q3 (mover o cache existente ou refazer) |
| `/.cache/r36os/` | `/.cache/lume/` | cache-pc | idem, com a barra final |
| `/.cache/r36os/src` | `/.cache/lume/src` | cache-pc | fontes e árvores de build (README) |
| `XDG_CACHE_HOME/r36os` | `XDG_CACHE_HOME/lume` | cache-pc | `spec build-cache`, README |
| `/aports/r36os` | `/aports/lume` | cache-pc | dentro do container: `.cache/.../aports/r36os/lume-launcher/stage` (`lume_cross.py`, testes) |
| `/aports/r36os/` | `/aports/lume/` | cache-pc | idem, com a barra final |
| `/aports/r36os/lume-launcher/stage/` | `/aports/lume/lume-launcher/stage/` | cache-pc | `lume_cross.py` |
| `/aports/r36os/lume-launcher/stage/lume` | `/aports/lume/lume-launcher/stage/lume` | cache-pc | `lume_cross.py` |
| `/aports/r36os/lume-launcher/stage/lume/target` | `/aports/lume/lume-launcher/stage/lume/target` | cache-pc | `test_lume_stage.py` |
| `/repo/r36os` | `/repo/lume` | cache-pc | repositório local de APKs nos testes de integração |
| `/data/r36os/kbuild` | `/data/lume/kbuild` | cache-pc | exemplo em `docs/ctx/MELHORIAS.md` (histórico, 1.4) |
| `/data/r36os/src` | `/data/lume/src` | cache-pc | idem |
| `/data/r36os/src/...` | `/data/lume/src/...` | cache-pc | idem |
| `/data/r36os/src/linux-` | `/data/lume/src/linux-` | cache-pc | idem |

Observação: as linhas `r36os.<módulo>` acima são a forma `import`; vale também para
`from r36os import <módulo>`. A forma `uv run r36os <subcomando>` nos docs é a linha `r36os` do
topo da tabela (1.4).

### 9.1 `scripts/dev`, `containers`, `policy.toml`, ctx e skills

| Antes | Depois | Tipo | Observação |
|---|---|---|---|
| `scripts/dev/put.py` | `scripts/dev/put.py` | script-pc | só o conteúdo: `from r36os import dev` vira `from lume_tool import dev` |
| `scripts/dev/vm_qmp.py` | `scripts/dev/vm_qmp.py` | script-pc | só o conteúdo (`from r36os.paths`, `r36os.qmp`, `r36os.vm`) |
| `scripts/dev/exit-timeline.sh` | `scripts/dev/exit-timeline.sh` | script-console | só o conteúdo: chama `r36os-devmem` (vira `lume-devmem`) |
| `containers/builder.Containerfile` | `containers/builder.Containerfile` | containerfile | só o conteúdo (`PACKAGER`) |
| `containers/cross-gcc.sh` | `containers/cross-gcc.sh` | script-pc | só o conteúdo (`localhost/r36os-builder`, `src/r36os/distcc.py`) |
| `.venv/bin/r36os dev shot` | `.venv/bin/lume dev shot` | policy | `policy.toml`: lista de comandos permitidos |
| `.venv/bin/r36os dev keys` | `.venv/bin/lume dev keys` | policy | idem |
| `.venv/bin/r36os dev run` | `.venv/bin/lume dev run` | policy | idem |
| `.venv/bin/r36os dev wait` | `.venv/bin/lume dev wait` | policy | idem |
| `.venv/bin/r36os dev log` | `.venv/bin/lume dev log` | policy | idem |
| `.venv/bin/r36os dev shot {saida}` | `.venv/bin/lume dev shot {saida}` | receita-ctx | `policy.toml`, receita `steps` |
| `.venv/bin/r36os dev keys {teclas}` | `.venv/bin/lume dev keys {teclas}` | receita-ctx | idem |
| `.venv/bin/r36os dev run {roteiro}` | `.venv/bin/lume dev run {roteiro}` | receita-ctx | idem |
| `r36os dev` | `lume dev` | comando | comentários do `policy.toml` e docs (`r36os dev sh` etc.) |
| `r36os clean` | `lume clean` | comando | comentário do `policy.toml` |
| `r36os vm` | `lume vm` | comando | comentários e mensagens (`vm.py`, `cli.py`) |

Observação: a edição do `policy.toml` mexe no guardrail do ctx; a 1.3 a faz como um nó `TREE`
sozinho, e o `.venv/bin/lume` precisa existir (`uv sync --inexact`) antes de a política ser
trocada, senão as receitas `dev-*` ficam sem comando. Os arquivos `.claude/skills/*`,
`.agents/skills/*`, `CLAUDE.md`, `README.md` e `openspec/config.yaml` citam o comando e
`/usr/libexec/r36os/frontends/`: são da 1.4.

## 10. Testes e fixtures com `r36os` no nome

| Antes | Depois | Tipo | Observação |
|---|---|---|---|
| `tests/unit/test_r36os_evrec.py` | `tests/unit/test_lume_evrec.py` | teste | |
| `test_r36os_evrec.py` | `test_lume_evrec.py` | teste | citado em `aports/r36os-input/APKBUILD` e `docs/BUILD.md` |
| `tests/unit/test_lume_stage.py` | `tests/unit/test_launcher_stage.py` | teste | só acompanha o módulo `lume.py` -> `launcher_stage.py` (nome sem `r36os`, mas já confunde com os `test_lume_*` do console) |
| `tests/unit/test_r36os_input.py` | `tests/unit/test_lume_input.py` | teste | |
| `tests/unit/test_r36os_powerctl.py` | `tests/unit/test_lume_powerctl.py` | teste | |
| `test_r36os_powerctl.py` | `test_lume_powerctl.py` | teste | citado em `test_r36os_powerctl_auto.py` |
| `tests/unit/test_r36os_powerctl_auto.py` | `tests/unit/test_lume_powerctl_auto.py` | teste | |
| `tests/unit/test_r36os_shot.py` | `tests/unit/test_lume_shot.py` | teste | |
| `test_r36os_shot.py` | `test_lume_shot.py` | teste | citado em `aports/r36os-input/APKBUILD` |
| `tests/fixtures/aports/r36os-hello` | `tests/fixtures/aports/lume-hello` | fixture | pasta com `APKBUILD` |
| `r36os-hello` | `lume-hello` | fixture | `pkgname` do fixture |
| `r36os-hello-1.0-r0.apk` | `lume-hello-1.0-r0.apk` | fixture | testes de integração |
| `tests/fixtures/aports/r36os-hello-arch` | `tests/fixtures/aports/lume-hello-arch` | fixture | pasta com `APKBUILD` e `greeting` |
| `r36os-hello-arch` | `lume-hello-arch` | fixture | `pkgname` e `cmd_name` |

Os testes que só têm `r36os` no conteúdo (imports `from r36os import ...`, caminhos do console,
variáveis) trocam só o conteúdo: `tests/unit/*.py` (116 arquivos), `tests/integration/*.py`,
`tests/vm/*.py`, `tests/device/*`, e os `.sh` de `tests/audio`, `cores`, `initramfs`, `logs`,
`net`, `playlists`, `selftest`, `session` e `usb`. `tests/cores/*.sh` e `tests/initramfs/test_storage.sh`
usam a versão do kernel `6.18.6x-r36os` (ver `Fica como está`).

## 11. Apps em `lume/` (workspace Rust)

O workspace `lume/` já tem nome novo (`lume-core`, `lume-ui`, `lume-run`, `lume-menu`,
`lume-index`). Só o conteúdo cita `r36os`: caminhos do console (`/run/r36os/input.sock`,
`/run/r36os/hud`, `/run/r36os/power*`, `/usr/libexec/r36os/frontends/retroarch`,
`/etc/r36os/board`, `/usr/share/r36os/input/<placa>.conf`, `/usr/share/r36os/systems.json`),
nomes de serviço (`r36os-input`, `r36os-ssh-wifi`, `r36os-logd`, `r36os-power`), o executável
`r36os-shot` e, nos testes, `aports/lume-games/files/usr/share/r36os/systems.json` e
`../../aports/r36os-input`. Todos estão nas tabelas 2 a 7; nenhum arquivo nem pasta do
`lume/` muda de nome. Os testes em Rust leem os caminhos do repositório (`aports/.../usr/share/r36os/`),
por isso a 1.2 muda as pastas e esses testes no mesmo passo.

| Antes | Depois | Tipo | Observação |
|---|---|---|---|
| `../../aports/r36os-input` | `../../aports/lume-input` | rust-teste | `lume-ui/src/system.rs` (teste) |
| `../../aports/lume-games/files/usr/share/r36os/systems.json` | `../../aports/lume-games/files/usr/share/lume/systems.json` | rust-teste | `lume-core`, `lume-index`, `lume-ui` |
| `aports/lume-games/files/usr/share/r36os/systems.json` | `aports/lume-games/files/usr/share/lume/systems.json` | rust-teste | `lume-ui/tests/ui.rs`, `lume-index/tests/cli.rs` |
| `aports/r36os-input/input.c` | `aports/lume-input/input.c` | rust-comentario | citado em `lume-core/src/input.rs` |
| `aports/r36os-input/ga36.conf` | `aports/lume-input/ga36.conf` | caminho | `docs/PENDENCIAS.md`, `openspec/...` |
| `aports/r36os-input/r36s.conf` | `aports/lume-input/r36s.conf` | caminho | idem |
| `aports/r36os-input/vm.conf` | `aports/lume-input/vm.conf` | caminho | `dev.py` |
| `aports/r36os-input/evrec.c` | `aports/lume-input/evrec.c` | caminho | `docs/BUILD.md` |
| `aports/r36os-padmerge` | `aports/lume-padmerge` | caminho | só em um comentário de teste; a pasta já não existe |
| `aports/r36os-` | `aports/lume-` | caminho | prefixo citado em `openspec/changes/device-fixes/proposal.md` |
| `aports/r36os-input/` | `aports/lume-input/` | caminho | citado em `openspec/changes/virtual-gamepad/proposal.md` |
| `aports/lume-core/files/usr/libexec/r36os` | `aports/lume-core/files/usr/libexec/lume` | caminho | testes (`test_logs_doc.py`, `test_power_service.py`) |
| `PWD/aports/lume-core/files/usr/libexec/r36os` | `PWD/aports/lume-core/files/usr/libexec/lume` | caminho | `tests/logs`, `tests/selftest` |
| `aports/lume-diag/files/usr/libexec/r36os` | `aports/lume-diag/files/usr/libexec/lume` | caminho | testes |
| `aports/lume-saves/files/usr/libexec/r36os` | `aports/lume-saves/files/usr/libexec/lume` | caminho | testes |
| `aports/lume-retroarch-cfg/files/usr/share/r36os` | `aports/lume-retroarch-cfg/files/usr/share/lume` | caminho | testes |

## 12. Caminhos persistidos no cartão (`ROMS/system`) que contêm `r36os`

A busca por `r36os` em todo caminho que o código grava ou lê no cartão (`/storage/system/...`,
`ROMS/system/...`, `/storage/logs`, `/storage/saves`, `/storage/states`, `/storage/roms`)
**não achou nenhum caminho com `r36os`**. O que o `persist` e os outros serviços guardam hoje:

| Caminho no cartão | Quem grava | Contém `r36os`? | Decisão |
|---|---|---|---|
| `ROMS/system/retroarch/retroarch.cfg` | `persist` (`/usr/libexec/r36os/persist`) | no conteúdo: a linha `libretro_info_path = "/usr/share/r36os/libretro-info"` | **sem migração**: o `frontends/retroarch` regrava, a cada início, as linhas fixas do `retroarch-lume.cfg` no lugar (`merge_fixed`), então o valor novo `/usr/share/lume/libretro-info` entra no primeiro boot e o `persist` o salva |
| `ROMS/system/lume/retroarch-restore.cfg` | `lume-ui` (restaurar o RetroArch) | só se copiar linhas fixas antigas | sem migração: depois de restaurado, passa pelo mesmo `merge_fixed` |
| `ROMS/system/etc/timezone`, `ROMS/system/etc/hostname` | `persist` | não | caminho igual |
| `ROMS/system/etc/logs.conf` | `logs.sh`, `logd` | não (só o nome `logs.conf`) | caminho igual |
| `ROMS/system/etc/dtb-<soc>[-<serial>].conf` | `logd` (escolha do DTB) | não | caminho igual |
| `ROMS/system/etc/audiotest` | `lume-audiotest` | não | caminho igual |
| `ROMS/system/lume/power.conf` | `lume-power` (`PW_CARD`) | não | caminho igual |
| `ROMS/system/lume/settings.toml`, `lume/level-colors`, `lume/themes/`, `lume/runners.d/`, `lume/cache/` | `lume-ui`, `lume-index`, `lume-input` | não | caminho igual |
| `ROMS/system/ssh/{wifi-code,authorized_keys,dropbear_ed25519_host_key}` | `ssh-wifi` | não | caminho igual |
| `ROMS/logs/`, `ROMS/saves/`, `ROMS/states/`, `ROMS/roms/`, `ROMS/usb/` | `lume-logd`, `savesync`, `usb-gadget` | não | caminho igual |
| `ROMS/LEIA-ME.txt` | `initramfs/init` | não | caminho igual |

Runlevels e `conf.d`: não são persistidos no cartão. O que o `persist` guarda está na lista acima;
os `/etc/runlevels/*/r36os-*` são links criados na imagem por `rootfs/configure.sh` (`rc-update add`)
e refeitos a cada `push`. O `/etc/conf.d/frontend` (`FRONTEND=...`) é da imagem e só tem o valor
de `/usr/libexec/r36os/frontends/<nome>` num comentário. Logo, **nenhum caminho persistido precisa
da migração única `persist OK migrated <antigo> -> <novo>`**. A 1.2 mantém o código da migração
pronto só para o caso de a revisão achar um caminho que escapou (nenhum hoje); a prova J0 (1.5)
confirma com um `lume push` sobre o GA36 com os nomes antigos, olhando que o `retroarch.cfg` do
cartão ganha a linha nova e que nada em `ROMS/system` foi recriado.

Um risco a vigiar, fora do cartão: o **estado em RAM** (`/run/r36os/...`) some a cada boot e não é
migrado; um `push --hot` sobre uma imagem antiga, com os serviços já rodando, deixa `/run/r36os`
sem uso até o próximo boot (o `lume-power` e o `lume-input` novos criam `/run/lume` no início).

## Fica como está

Itens que **não** entram na troca. O teste não conta as ocorrências de `r36os` nestes itens. A
coluna `Item` lista o caminho (pasta com `/` no fim, ou arquivo) ou o texto exato que fica; o
teste usa o que está entre crases: um caminho tira o arquivo da busca, um texto tira só essa
ocorrência.

| Item | Motivo |
|---|---|
| `openspec/changes/archive/` | Changes arquivadas são histórico: não se reescreve |
| `docs/referencia/` | Material de referência medido (dados do GA36 e de outros projetos), copiado com crédito; não é nome do projeto |
| `openspec/changes/device-fixes/` | A própria change que descreve a troca precisa dos nomes antigos para explicar o que muda (design, proposta, tarefas e specs) |
| `docs/NOMES.md` | Este mapa lista os nomes antigos |
| `tests/unit/test_lume_names.py` | O teste-guarda cita o prefixo antigo |
| `uv.lock` | Arquivo gerado: o `uv sync --inexact` o refaz depois da troca do nome do projeto |
| `# r36os-evrec` | Cabeçalho das gravações de entrada feitas antes da troca (`evrec.LEGACY_MAGIC`): a ferramenta ainda as lê (compatibilidade de dados, 1.3) |
| `.SIGN.RSA.r36os.rsa.pub` | Assinatura dos pacotes feitos antes da troca da chave: o teste da reassinatura única (`test_resign_published.py`, 1.3) a reconhece |
| `OLD_BOOT_N = "/run/r36os/logs/boot-n"` | Console com um build de antes da troca (J0, 1.5): o `push` lê o número do boot no caminho antigo para mandar os nomes novos (`push.py`, compatibilidade) |
| `cat /etc/r36os/board 2>/dev/null` | Idem, a placa do console no caminho antigo (`push.py`, compatibilidade) |

Nome do repositório (pasta `r36s_all`, nome no GitHub): fica como está; é o nome do repositório,
que não aparece em nenhum código (o D7 já o exclui). Nenhum arquivo do repositório tem
`r36os` como parte do nome do repositório.

## 13. Itens decididos pelo usuário (2026-11-18: "mude tudo, quero tudo padronizado")

Os itens que o mapa deixava como está por custo de build também trocam de nome. Ficam como estão
só o histórico e o material de terceiros da tabela acima.

| Antes | Depois | Tipo | Observação |
|---|---|---|---|
| `CONFIG_LOCALVERSION="-r36os"` | `CONFIG_LOCALVERSION="-lume"` | kernel | Q1: versão `6.18.62-lume` e `/lib/modules/<versão>-lume/`; refaz kernel e módulos dos dois consoles (build da 1.5 e da 10.1). Os textos `6.18.6x-r36os` em `tests/initramfs/test_storage.sh`, `tests/unit/test_stage_inputs.py` e `docs/BRINGUP-GA36.md` acompanham |
| `r36os.rsa.pub` | `lume.rsa.pub` | chave | Q2: chave de assinatura dos APKs (`rootfs.py`, `initramfs.py`, `lume_cross.py`, `/keys/`, `/root/.abuild/`, `.SIGN.RSA.*` nos testes); reassina e refaz todos os pacotes e o repositório local, e a imagem passa a confiar na chave nova |
| `board/r36s/dts-vendor/` | `board/r36s/dts-vendor/` | dts | comentários `r36os` dos DTS convertidos e o `SOURCES.tsv`: a ferramenta de conversão passa a gerar `lume`, e os arquivos atuais são regenerados (ou trocados no mesmo texto) |
| `kernel/patches/` | `kernel/patches/` | patch | só o texto `r36os` das mensagens de commit (`0017`, `0021`); o código dos patches não muda; refaz a árvore do kernel |
| `aports/retroarch/*.patch` | `aports/retroarch/*.patch` | patch | texto de commit de `0001`, `0004`, `0009`, `0011` e os comentários do `APKBUILD` (`r36os-logd`, `r36os-session`); refaz o RetroArch nas duas arquiteturas (recurso `CPU` da 10.1) |

Respostas às perguntas do mapa:
- **Q1** e **Q2**: trocar (tabela acima).
- **Q3**: o cache do PC vira `.cache/lume` e `~/.cache/lume`; a 1.3 move a pasta existente (sem
  refazer o que já está pronto).
- **Q4**: as variáveis `R36OS_*` trocam sem alias, incluindo `R36OS_GA36_FACTORY` e
  `R36OS_R36S_FACTORY`.
- **Q5**: `lume.py` vira `launcher_stage.py`.
