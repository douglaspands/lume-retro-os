# Design

## Context

O repositório está vazio (só governança e OpenSpec), então tudo é construído do zero. Os dados de hardware necessários foram copiados para os apêndices deste documento, a partir de fontes públicas:

- **R36S V5:** DTB de fábrica do kernel BSP 4.4 da Rockchip, da coleção dArkOSRE-R36 (GitHub `southoz/dArkOSRE-R36`, commit `3f372c85aa53`).
- **GA36-MB V1.2:** device tree mainline e drivers do projeto goodluckOS (GitHub `CodeZombie/goodluckOS`, commit `8d676e2327a6`, GPL-2.0), mais os dados do firmware de fábrica (FEX e módulos `lcd.ko` e `udt_joystick.ko`).

O que o Alpine v3.24 (estável) já oferece, consultado em 2026-11-09:

| Item | Alpine v3.24 |
|---|---|
| `retroarch` 1.22.2 | community, x86_64 / aarch64 / armv7 |
| `libretro-fceumm`, `-gambatte`, `-mgba`, `-gpsp`, `-nestopia` | community, nos 3 arches |
| `libretro-snes9x`, `-genesis-plus-gx`, `-picodrive`, `-pcsx-rearmed`, `-fbneo` | só `testing` do edge |
| `libretro-snes9x2005-plus`, `-snes9x2010`, `-mame2003-plus` | não existem |
| `mesa-dri-gallium` 26.1 | main, nos 3 arches |
| `exfatprogs` | community |

As opções de compilação do pacote `retroarch` (KMS, EGL, GLES, udev) não puderam ser confirmadas.

O host (Fedora, x86_64) não tem emulação de ARM registrada no binfmt.

## Goals / Non-Goals

**Goals:**
- Um único pipeline de build que gera as três imagens a partir das mesmas listas.
- Paridade máxima entre VM e consoles: o que a VM aprova é o que vai para o console, exceto a camada de hardware.
- Boot rápido e robusto a cortes de energia num cartão SD lento.
- Dados de hardware versionados neste repositório, sem depender de pastas locais externas.

**Non-Goals:**
- Construir o Alpine a partir do código-fonte: usamos os binários oficiais e só compilamos o que falta.
- Atualização pelo próprio aparelho (OTA): atualizar é trocar o `SYSTEM` pelo PC.
- Calibração fina de bateria, overclock e economia de energia avançada.

## Decisions

### D1. Estrutura do repositório

```
board/
  r36s/   dts/, kernel.config, uboot.config, extlinux.conf, hw-packages.txt
  ga36/   dts/, kernel.config, uboot.config, extlinux.conf, hw-packages.txt
  vm/     extlinux.conf, hw-packages.txt
kernel/   patches/ (driver JD9366, driver do controle serial do GA36, painel do R36S)
aports/   pacotes Alpine locais (cores ausentes, retroarch, mesa só da VM, r36os-*)
rootfs/   packages.txt (lista comum), overlay/ (arquivos de /etc, serviços)
initramfs/ init e lista de binários
src/r36os/ orquestrador do build e da VM (Python, via uv)
tests/vm/ teste de aceitação
```

O orquestrador é Python porque o repositório já usa `uv` e `.venv`. Os comandos são `uv run r36os build <alvo>`, `uv run r36os vm [--headless]` e `uv run r36os test-vm`. O nome público do sistema é **Lume Retro OS** (em `/etc/os-release`, nas mensagens de boot e na documentação); `r36os` continua como nome interno do pacote, dos comandos e dos serviços.

### D2. Pipeline de build em quatro estágios, em containers

```
 [1] kernel + U-Boot          [2] pacotes locais        [3] rootfs           [4] imagem
 cross-compile, container     abuild no container       apk --root no        BOOT FAT32 +
 x86_64 com toolchains        Alpine do arch alvo       container do arch    bootloader raw
 aarch64/armhf                (qemu-user p/ ARM)        -> SYSTEM squashfs   -> <alvo>.img
        |                            |                         |                  ^
        +-------- Image/zImage, dtbs, modules.tar ------------+------------------+
```

- **Kernel e U-Boot são compilados em cross**, num container x86_64 com `gcc-aarch64-linux-gnu` e `gcc-arm-linux-gnueabihf`. Compilar o kernel sob emulação levaria horas. Os módulos entram no `SYSTEM` e a imagem do kernel vai para a `BOOT`. Não viram pacotes apk.
- **Pacotes locais (cores, retroarch, scripts) usam `abuild`** num container Alpine da arquitetura alvo, com chave de assinatura local e cache (`ccache` e cache de distfiles fora do repositório). Para ARM isso exige `qemu-user` registrado no binfmt do host.
  - *Alternativa descartada:* cross-compilar os cores com o toolchain de bootstrap do Alpine (musl). Isso dá mais trabalho a cada core e diverge do jeito como o Alpine empacota.
  - Cada pacote local é construído só para os arches do seu `arch=`. O `mesa` local é `x86_64`: o Mesa do Alpine não compila o driver virgl, e sem ele a VM desenharia por software (llvmpipe). Nos consoles fica o Mesa do Alpine (lima e panfrost).
  - Os pacotes locais usam as flags padrão do Alpine. A única exceção é o `libretro-pcsx-rearmed` no armv7, que leva `-marm -mfpu=neon`: o dynarec dele não compila em Thumb-2 (o padrão do Alpine armv7) e a GPU NEON precisa de NEON, que o padrão `vfpv3-d16` não liga. O ajuste fino para o Cortex-A7 fica para a change de otimização.
- **O rootfs é montado com `apk add --root` dentro de um container da arquitetura alvo**, para os scripts de pós-instalação (busybox, OpenRC) rodarem de verdade. A raiz vira o squashfs `SYSTEM` com compressão `zstd`, que descomprime rápido no Cortex-A7 e comprime melhor que `lz4`.
- **A imagem final** é montada sem root nem loop mount: `mtools` grava a FAT e `dd` grava o bootloader. A assinatura MBR é fixa por alvo, para o `extlinux.conf` usar `root` por PARTUUID.

### D3. Kernel

| Alvo | Kernel | Motivo |
|---|---|---|
| R36S | Linux mainline LTS (6.18.y) com config própria | DSI, panfrost, RK817 (codec e carregador) e SARADC já são mainline |
| GA36 | o mesmo LTS, `sunxi_defconfig` (o `multi_v7` reduzido aos Allwinner) mais o fragmento `board/ga36/kernel.config` e os patches de `kernel/patches/` | painel JD9366 (`0005`) e controle serial (`0006`) não são mainline; os dois drivers são port do goodluckOS |
| VM | `linux-virt` do Alpine | já traz virtio, virtio-gpu e `fbcon` |

Frequência da CPU e temperatura ficam nos padrões do mainline: OPPs e zonas térmicas do `.dtsi` do SoC sem alteração, `cpufreq-dt` e o governor padrão do kernel. Os ajustes medidos no GA36 (`docs/referencia/ga36-emuelec/`) vêm de um kernel sunxi antigo e serão refeitos numa change de otimização.

Ficam embutidos (não como módulo) nos consoles: `vfat`, `exfat`, `squashfs`, `loop`, `overlay`, o MMC do SoC, o DRM do painel e o `fbcon`. Assim o boot verboso aparece no painel cedo e o initramfs fica mínimo. Na VM, o initramfs carrega esses módulos.

- *Alternativa descartada:* usar o `linux-lts` do Alpine nos consoles. Ele não tem os drivers do GA36 nem os DTBs próprios, e embutir o `fbcon` e os drivers exigiria trocar a config de qualquer jeito.

### D4. Device trees

- **GA36:** port do `ga36mb.dtsi` / `ga36mb-a33.dtsi` do goodluckOS sobre o `sun8i-a33.dtsi` mainline, com os valores do Apêndice B e a correção de A/B (o goodluckOS tem PE12 e PE13 trocados). Há um DTS por painel (`…-panel1.dts` e `…-panel2.dts`), em vez de alterar o DTB no U-Boot: com extlinux é mais simples e visível ter duas entradas.
- **R36S V5:** DTS novo sobre `rk3326.dtsi` mainline, seguindo a estrutura do `rk3326-odroid-go2.dts` (hardware da mesma família), com os valores do Apêndice A.
  - **Painel:** o controlador responde à assinatura `B9 F1 12 87` (família Sitronix ST7703). O painel entra como uma nova variante no driver mainline `panel-sitronix-st7703`, com a sequência do Apêndice C.
  - **Controle:** botões em `gpio-keys` e analógicos em `adc-joystick` sobre um `io-channel-mux` (GPIOs de mux no Apêndice A). Os dois dispositivos são unidos em espaço de usuário (D9).

### D5. Bootloaders

- **R36S:** U-Boot mainline baseado no `odroid-go2_defconfig` (mesmo SoC). O `idbloader` é TPL+SPL. Se o TPL aberto do PX30/RK3326 não inicializar a DDR deste aparelho, usamos o blob de DDR do `rkbin` da Rockchip, que é redistribuível. Esse é o único binário fechado admitido.
- **GA36: bootloader do fabricante** (boot0 e U-Boot 2017 da Allwinner), a mesma cadeia do firmware de fábrica e do goodluckOS, a única comprovada neste aparelho. Os primeiros 128 MiB do cartão são a área de boot de fábrica (boot0 no setor 16, U-Boot, tabela `softw411` no setor 40960, FAT "bootloader", env no setor 139264), lida da imagem de fábrica (`R36OS_GA36_FACTORY`) e conferida por SHA256, fora do git por ser binário fechado. No setor 172032 (a partição "boot" da tabela da Allwinner) vai a nossa imagem de boot Android: `zImage` com o DTB anexado (`ARM_APPENDED_DTB`), o initramfs embutido no kernel e a linha de comando fixa no kernel (`CMDLINE_FORCE`); a memória real chega por ATAG (`ARM_ATAG_DTB_COMPAT`), com 512 MiB no DTS como reserva. A `BOOT` começa no setor 262144 (128 MiB). O painel 1 é o padrão, e a imagem de boot do painel 2 fica em `BOOT/android-boot/`. Esta é a segunda exceção a binários fechados, depois do blob de DRAM do R36S.
  - *Tentativa registrada:* U-Boot mainline v2025.10 (`Sinlinx_SinA33_defconfig` + `board/ga36/u-boot.config`, DRAM do Apêndice B, DTS da placa via `OF_UPSTREAM`). Compila, mas o aparelho não deu sinal de vida e, sem serial, não há como ver onde parou. Voltar a ele é a pendência 12.2 (FEL pela USB-C ou marcadores no LED).
- **VM:** SYSLINUX no MBR e na `BOOT`. Ele lê `extlinux/extlinux.conf` com a mesma sintaxe usada pelo U-Boot nos consoles.
- Os três usam `console=` com a serial e `tty1`, e nenhum `quiet`. Velocidade da serial: GA36 `ttyS1` a 115200 e R36S `ttyS2` a 1500000, igual à do TPL e do blob de DDR, para não trocar de velocidade no meio do boot.

### D6. Initramfs próprio, mínimo

O initramfs é um `init` em shell (busybox) com `sfdisk`, `mkfs.exfat` e `fsck.exfat` estáticos. Ele não usa o `mkinitfs` do Alpine, cujo fluxo (`nlplug-findfs`, modloop) não prevê o `SYSTEM` como arquivo.

```
init:
  monta proc/sys/dev; espera o cartao pelo PARTUUID da BOOT (timeout 10 s)
  se o disco nao tem particao 2 e ha espaco livre depois da BOOT:
      cria p2 ate o fim do disco (sfdisk), relê a tabela, mkfs.exfat -L ROMS
  se p2 existe e e exFAT: fsck.exfat -p (reparo automatico)
  se p2 existe e nao e exFAT: avisa e segue sem ROMS (nunca formata)
  monta BOOT ro em /boot; monta /boot/SYSTEM (loop, ro)
  overlay: lower=SYSTEM, upper/work em tmpfs (size=32m) -> /newroot
  monta ROMS em /newroot/storage (uid/gid do usuario game, noatime)
  move /boot para /newroot/boot; switch_root /newroot /sbin/init
```

A partição de jogos é criada antes de qualquer montagem do cartão, porque o kernel não relê a tabela de um disco com partição montada.

### D7. Persistência e sincronização segura

O RetroArch grava direto nos próprios arquivos de configuração, o que não é atômico e não serve num exFAT sem journal. Por isso:

- No boot, o serviço `r36os-persist` copia `/storage/system/retroarch/` para `~game/.config/retroarch/`, que fica na camada em RAM. No primeiro boot, ou depois de restaurar a fábrica, copia os padrões de fábrica do `SYSTEM`.
- Ele observa o diretório com `inotifyd` e, 2 s após a última mudança, sincroniza de volta cada arquivo alterado: grava um temporário, faz `fsync` e renomeia. Na saída do frontend, sincroniza tudo antes de desligar.
- Fuso horário e hostname são **lidos** de `system/etc/timezone` e `system/etc/hostname`, que o usuário edita no PC. Nesta versão não há tela para mudá-los.
- **Saves:** o RetroArch grava saves e estados em `/storage/saves` e `/storage/states`, com uma pasta por sistema (ordenação pelo diretório do conteúdo). O `inotifyd` observa essas pastas e roda `sync -f` em cada gravação concluída.

### D8. Catálogo de sistemas e listas de jogos

`/usr/share/r36os/systems.json` é a fonte única. Usamos JSON porque `jq` existe no Alpine e é pequeno; TOML exigiria um parser no sistema.

| id | Nome no menu | Extensões | Core padrão | Padrão armv7 | Alternativos |
|---|---|---|---|---|---|
| nes | NES | nes, fds, unf, zip, 7z | fceumm | — | nestopia |
| snes | Super Nintendo | sfc, smc, fig, swc, zip, 7z | snes9x2005_plus | — | snes9x |
| mastersystem | Master System | sms, zip, 7z | genesis_plus_gx | picodrive | — |
| megadrive | Mega Drive | md, gen, bin, smd, zip, 7z | genesis_plus_gx | picodrive | — |
| gb | Game Boy | gb, zip, 7z | gambatte | — | — |
| gbc | Game Boy Color | gbc, zip, 7z | gambatte | — | — |
| gba | Game Boy Advance | gba, zip, 7z | gpsp | — | — |
| arcade | Arcade | zip, 7z | fbneo | mame2003_plus | mame2003_plus |
| psx | PlayStation | cue, chd, pbp, m3u | pcsx_rearmed | — | — |

- Cores do Alpine v3.24: fceumm, nestopia, gambatte e gpsp. O `mgba` ficou fora desta versão: o GBA usa o `gpsp` em todos os alvos.
- PSP: fora desta versão. O `aports/libretro-ppsspp` existe, mas está desativado (`arch=""`) e é pendência (tarefa 12.1).
- Pacotes locais: snes9x2005_plus (o core de SNES de fábrica do GA36, no lugar do snes9x2010 desde 2026-11-11; build padrão, a otimização para o A33 fica para uma change futura), snes9x, genesis_plus_gx, picodrive, fbneo, mame2003_plus e pcsx_rearmed. Partem dos APKBUILDs do `testing` quando existem, atualizados para o código atual.
- O `r36os-playlists` é ash + jq e gera `/storage/system/retroarch/playlists/<Nome no menu>.lpl` no boot, antes do frontend subir. O nome do arquivo é o rótulo da lista no menu.
- Cada entrada da lista fixa o core pelo caminho, então o RetroArch não pergunta qual core usar.
- BIOS do PS1: `bios/scph5500.bin`, `scph5501.bin`, `scph5502.bin` e `scph1001.bin`. O `pcsx_rearmed` tem BIOS HLE como alternativa, que vai explicada no `LEIA-ME.txt`.

### D9. Entrada: um controle por console

- **GA36:** o driver de kernel do controle serial (serdev em `uart1`, 9600 baud) gera um único dispositivo de entrada com os botões GPIO e os dois analógicos. O protocolo está no Apêndice B. O driver é port do goodluckOS com o handshake do módulo de fábrica.
- **R36S:** o `r36os-padmerge` é um daemon pequeno em C que abre os dispositivos `gpio-keys` e `adc-joystick` do DT e publica, via `uinput`, um único controle chamado "R36S Gamepad".
  - O mesmo daemon é testado na VM com dispositivos falsos criados por `uinput`.
  - *Alternativa descartada:* um driver de kernel próprio, que seria mais código fora da árvore mainline.
- Um arquivo de autoconfiguração do RetroArch por controle: "R36S Gamepad" e o controle do GA36. O teclado da VM é mapeado no `retroarch-lume.cfg`.

### D10. Sessão do frontend

- `/etc/conf.d/frontend` contém `FRONTEND="retroarch"`, e cada frontend instala `/usr/libexec/r36os/frontends/<nome>`.
- O serviço OpenRC `frontend` (sem `supervise-daemon`) roda o `r36os-session` no `tty1` como o usuário `game` (grupos `video`, `input`, `audio`). O laço de controle fica no script:

```
loop:
  roda o frontend
  saida 0              -> r36os-persist flush; poweroff
  saida != 0           -> registra a falha com hora; se for a 3a em 60 s:
                          mostra o erro e o caminho do log no tty1 e para
                          senao recomeca o loop
```

- Para virar mestre do DRM sem root, o caminho preferido é o `seatd` (pacote do Alpine) com libseat. Se o RetroArch do Alpine não usar libseat no KMS, o frontend recebe a capability necessária no wrapper. Ver Riscos.
- O RetroArch roda com `--appendconfig /usr/share/r36os/retroarch-lume.cfg` (o nome é o do sistema, não de um tema). A configuração do usuário continua separada da configuração fixa da distro.

### D11. Menu padrão do RetroArch (Ozone)

- Sem tema próprio nesta change: o menu é o Ozone, com os assets oficiais do pacote `retroarch-assets` do Alpine em `/usr/share/libretro/assets/`. A autoconfiguração de controles comuns vem do `retroarch-joypad-autoconfig` (`/usr/share/libretro/autoconfig`); os arquivos dos controles dos consoles entram no mesmo diretório. O teclado da VM é mapeado no próprio `retroarch-lume.cfg` (`input_player1_*`).
  - *Alternativa descartada:* o tema Lume no XMB (ícones, fonte e wallpaper gerados no build). Ficou para uma change futura, junto com o Lume Console.
- O `retroarch-lume.cfg` contém só o que a distro precisa:
  - vídeo e entrada: `video_driver = gl`, contexto `kms`, `alsa`, `udev`;
  - pastas do contrato de jogos;
  - menu: `menu_driver = ozone`. O idioma de fábrica (`user_language`, do `--lang` do build) e a legibilidade numa tela de 3,5" a 640x480 (`menu_scale_factor = 1.5`, `ozone_font_scale_factor_global = 1.2`) ficam na configuração de fábrica do usuário (`factory/retroarch/retroarch.cfg`), porque no `--appendconfig` venceriam o ajuste feito no menu;
  - menu completo, sem modo kiosk. A exceção é o Core Updater, oculto porque os cores do buildbot são compilados para glibc e não rodam no Alpine (musl);
  - atalhos: `menu_pause_libretro = true`; Start + Select abre o menu (`input_menu_toggle_gamepad_combo = 4`); no teclado da VM, Shift direito (Select) + S também abre; nenhuma combinação encerra o RetroArch.
- O pacote `retroarch` local troca o rótulo "Sair do RetroArch" por "Desligar" (en, pt_BR e es), porque sair desliga o console (D10). O patch `0002-shut-down-asks-confirmation.patch` faz o item pedir confirmação por segurança: é preciso selecioná-lo duas vezes em até 3 s, e a primeira só mostra "Pressione novamente para desligar...". Segue o `quit_press_twice` (ligado no `retroarch-lume.cfg`); o atalho e o comando de rede `QUIT` não mudam, e o self-test desliga a confirmação só para si.
- Sem transparência no menu (hardware simples, Mali-400): `menu_framebuffer_opacity`, `menu_wallpaper_opacity`, `menu_header_opacity`, `menu_footer_opacity` e `video_msg_bgcolor_opacity` em 1.0 e `menu_rgui_transparency` desligado, no `retroarch-lume.cfg` (fixos, para valerem também em cartões que já têm configuração salva).

### D12. VM

- QEMU `x86_64`/KVM rodando dentro de container (podman), com o disco `vm.img` em raw, copiado a cada execução para o original não mudar.
- **Modo janela:** `virtio-vga-gl` com virgl, `-display gtk,gl=on`, resolução forçada a 640x480 pelo cmdline do kernel (`video=640x480`), áudio pelo PipeWire ou PulseAudio do host e teclado do host.
- **Modo sem tela (`--headless`):** `egl-headless` com serial no terminal. Capturas de tela pelo QMP `screendump`.
- **Controles do PC:** os controles em `/dev/input/by-id/*-event-joystick` que o usuário pode capturar são repassados à VM como `virtio-input-host-pci` (detecção automática, `--gamepad EVDEV` explícito ou `--no-gamepad`).
- **Pasta do PC (`--roms DIR` / `--share DIR`):** a pasta é exportada por virtio-9p, **somente leitura**. Na VM, o serviço `r36os-hostshare` (só com `board = vm`) a monta em `/mnt/host` e, se ela tiver as pastas dos sistemas (ou `roms/`), faz bind em `/storage/roms` e de `bios/` em `/storage/bios`, antes das listas de jogos. Saves e estados continuam na `ROMS` da VM.
- **Teste de aceitação:** cmdline com `r36os.selftest=1`. O serviço `r36os-selftest` roda as verificações dentro da VM e imprime marcadores (`SELFTEST <nome> PASS|FAIL`) na serial. O teste no host:
  1. faz o primeiro boot e verifica a criação da `ROMS`;
  2. copia ROMs de teste para a `ROMS` com a VM desligada (`mtools` não lê exFAT, então isso é feito pela própria VM, a partir de um segundo disco FAT só de teste);
  3. abre um jogo por core via `retroarch -L ... --max-frames=600` com log e verifica `core loaded`;
  4. muda uma opção, reinicia e confere a persistência;
  5. confirma que um arquivo em `/var/tmp` sumiu;
  6. pede a saída do frontend pelo QMP e confere o desligamento.
- **ROMs de teste:** compiladas no build a partir de fontes livres (programas mínimos para cada sistema, montados com `cc65` para NES, `rgbds` para GB/GBC e similares) ou homebrew com licença que permita redistribuir. Ficam só no segundo disco da VM.

### D14. Logs de diagnóstico (base para decisões futuras)

O objetivo é medir o comportamento real do sistema e do hardware, como clock, temperatura, memória, bateria e falhas, antes de otimizar. As medições do projeto anterior (`docs/referencia/ga36-emuelec/`) vinham de um kernel antigo; estas passam a ser a base da change de otimização.

- **Destino único:** todos os logs do sistema ficam em `ROMS/logs/`, legível no PC, incluindo o log de boot e o do frontend, que antes iam para `BOOT/logs/`. Apagar a pasta inteira é a forma de limpar. É seguro: ela é recriada no boot seguinte e a numeração dos boots recomeça. A `BOOT` fica somente leitura o tempo todo.
  - **Exceção, só sem `ROMS`** (partição 2 ausente ou não exFAT): o log de boot vai para `BOOT/logs/`, mantendo 10, porque é justamente o caso que precisa de diagnóstico. Os demais logs ficam só na RAM.
- **Numeração:** um contador `<n>` por boot, guardado em `ROMS/logs/.boot`, é o mesmo em todas as pastas, para cruzar os arquivos de um boot. Cada arquivo também traz a data e o `boot_id` do kernel.
- **Idioma:** os logs são sempre em inglês: conteúdo, nomes de arquivos e pastas, categorias de evento (`OK`/`FAIL`), colunas do CSV e as mensagens do kernel, do initramfs e dos serviços. Assim um log é comparável entre aparelhos e serve para pedir ajuda fora do Brasil. Só as mensagens para o usuário seguem o idioma escolhido no menu do RetroArch (`user_language`, persistido pelo D7): a tela de falha do frontend tem texto em inglês, português e espanhol (os idiomas do rótulo "Desligar" da 7.7), e os outros idiomas caem no inglês.
- **Escrita em lote:** cada coletor escreve em `/run/r36os/logs/` (RAM). O serviço `r36os-logd` descarrega no cartão a cada 60 s e no desligamento, com append, `fsync` e temporário com `rename` nos arquivos inteiros. Um corte de energia perde no máximo o último intervalo. O desligamento limpo grava o marcador `.clean`; se o boot seguinte não o encontrar, registra `shutdown FAIL previous abrupt`.
- **Conteúdo** (`<n>` é o contador de boot):

| Arquivo (em `ROMS/logs/`) | Quando | O que tem |
|---|---|---|
| `boot/boot-<n>.log` | uma vez por boot, no fim do runlevel default | mensagens do kernel (`dmesg`), log do OpenRC e resumo de hardware (era `BOOT/logs/boot-<n>.log`) |
| `hw/boot-<n>.txt` | uma vez por boot, depois do frontend subir | versão do sistema, kernel e cmdline, modelo do DT; CPU (núcleos, governor, frequências mín./máx./disponíveis); memória e swap; zonas térmicas e trip points; reguladores (nome, tensão, estado); bateria (todos os campos de `power_supply`); cartão e partições (tamanho, uso da ROMS, resultado do `fsck`); vídeo (modo DRM, driver da GPU); placas de áudio; dispositivos de entrada; tempo até o frontend; se o desligamento anterior foi limpo |
| `metrics/boot-<n>.csv` | a cada 5 s | data, uptime, temperatura de cada zona, frequência atual de cada política, ocupação de cada núcleo, memória disponível, swap usado, bateria (%, tensão, corrente, estado) e estado do frontend (menu ou jogo, core, conteúdo) |
| `events.log` | quando acontece | uma linha por evento, `time boot category OK/FAIL detail`: boot concluído e tempo até o frontend; serviço com falha; frontend iniciado ou encerrado (código de saída, falhas seguidas); jogo aberto ou fechado (core, conteúdo, duração); ROMS criada ou reparada; temperatura acima do trip passivo; bateria abaixo de 10%; desligamento limpo ou abrupto; erros do kernel no boot (`dmesg` nível err ou pior, resumidos) |
| `frontend/boot-<n>.log` | no fim da sessão e na descarga | log do frontend (o RetroArch com `--verbose`). Também é o log indicado na tela quando o frontend falha 3 vezes (era `BOOT/logs/frontend-erro.log`; sem `ROMS`, `BOOT/logs/frontend-error.log`) |

- **Estado do frontend:** lido pelo comando de rede do RetroArch (`GET_STATUS` em UDP 55355, consultado em `127.0.0.1`), ligado no `retroarch-lume.cfg`. Os consoles não têm rede nesta versão; se uma change futura trouxer Wi-Fi, isso precisa ser revisto. A mudança menu→jogo gera os eventos de jogo aberto e fechado.
- **Rotação:**
  - `boot/`, `hw/` e `frontend/`: os 30 boots mais recentes (`keep_boots` no `logs.conf`);
  - `metrics/`: os 30 boots mais recentes, e cada arquivo para de crescer em 4 MiB (cerca de 30 h a 5 s);
  - `events.log`: vira `events.1.log` em 1 MiB, mantendo 3;
  - acima de 64 MiB no total, apaga primeiro as métricas mais antigas, depois os logs do frontend.
- **Custo:** coletores em ash + awk lendo `/proc` e `/sys`, sem processos novos por campo além do necessário. A meta é menos de 1% de CPU no A33, medida na primeira subida.
- **Configuração:** `ROMS/system/etc/logs.conf`, criado com os padrões no primeiro boot e editável no PC: `enable=1`, `interval=5`, `flush=60`, `keep_boots=30`, `max_mb=64`. Com `enable=0` não rodam o amostrador nem o retrato do hardware, e ficam só o log de boot e os eventos.
- O formato está documentado em `docs/LOGS.md` (colunas do CSV e categorias de evento), para análise no PC.

### D15. Versão das imagens

Cada build recebe um identificador, o timestamp `AAAAMMDD-HHMMSS`. O mesmo valor vai para `/etc/os-release` (`BUILD_ID`, e portanto para o retrato do hardware nos logs), para `BOOT/VERSION` (legível no PC, para saber qual build está no cartão) e para o arquivo da imagem. Cada build fica guardado em `out/images/<alvo>/<timestamp>/`: a imagem comprimida (`.img.zst`), o `manifest.txt`, o `build.json` (commit do repositório, se havia alterações não commitadas, kernel e patches, U-Boot, Alpine e tamanhos) e o `SHA256SUMS`. `out/images/<alvo>/latest` aponta para o mais recente. As imagens não vão para o git; o `out/` continua ignorado.

### D13. Usuário e permissões

Usuário `game` (uid 1000) sem senha e sem login interativo. `root` sem senha só na serial de debug, nesta fase de validação. Sem SSH nesta versão.

## Risks / Trade-offs

- **[Driver do painel do R36S não casa com o ST7703]** → A sequência do Apêndice C é de um driver "simple-panel-dsi" da Rockchip. Se o `panel-sitronix-st7703` não aceitar a variante, criamos uma entrada no `panel-mipi-dsi` genérico, que lê a sequência de um arquivo de firmware. A primeira subida usa a serial para diagnosticar.
- **[Mux dos analógicos do R36S]** → O `odroidgo3-joypad` faz o mux por GPIO em driver próprio. Se `io-channel-mux` + `adc-joystick` não fecharem o timing, o `r36os-padmerge` lê o IIO direto e faz o mux em espaço de usuário. O custo é latência e CPU um pouco maiores.
- **[Inicialização da DDR do RK3326]** → O TPL aberto pode não suportar a DDR do R36S. A mitigação é o blob `rkbin`, versionado com hash.
- **[RetroArch do Alpine sem KMS/GLES ou libseat]** → A primeira tarefa verifica `retroarch --features`. Se faltar algo, empacotamos um `retroarch` local com `--enable-kms --enable-egl --enable-opengles --disable-x11 --disable-wayland`.
- **[DRM master sem root]** → `seatd` como caminho principal e capability no wrapper como alternativa. A VM detecta isso porque usa o mesmo caminho.
- **[Build ARM sob emulação é lento]** → `ccache` e cache de pacotes fora do repositório. Kernel e U-Boot ficam fora da emulação.
- **[qemu-user no host exige instalação]** → É a única dependência de host e precisa de confirmação explícita do usuário antes de instalar.
- **[exFAT sem journal]** → Mitigado com `fsck.exfat` no boot, escrita atômica da configuração e `sync` após saves. Mesmo assim, um corte no exato momento de gravar pode perder o último save.
- **[virgl diferente de lima/panfrost]** → A VM valida a lógica e o GLES, não o desempenho nem bugs de driver. O desempenho do A33 se mede no próprio GA36.
- **[Tamanho do SYSTEM]** → mesa, RetroArch e 12 cores devem ficar em 300-500 MB. O build falha acima de 768 MiB.

## Migration Plan

Não há instalação anterior para migrar. A sequência de liberação de cada build:

1. Gerar a imagem `vm` e rodar o teste de aceitação.
2. Só depois gerar e marcar como liberadas as imagens `r36s` e `ga36`.
3. A primeira subida em cada console é manual, com adaptador serial, seguindo as checagens do resumo de hardware.

Para voltar atrás, basta regravar o cartão com a build anterior. Restaurar a fábrica é apagar `ROMS/system/`.

## Open Questions

- Botões F1-F5 do R36S: a ordem esperada é F1 = Select, F2 = Start, F3 = L3, F4 = R3 e F5 = Fn. Isso só se confirma no aparelho e afeta apenas a autoconfiguração.
- Os valores finais de `menu_scale_factor` e `ozone_font_scale_factor_global` saem da calibração na VM e se confirmam no painel real.

---

## Apêndice A: R36S "V5" (RK3326), dados do DTB de fábrica

Fonte: DTB `rk3326-r35s-linux.dtb` (SHA-256 `205c7ef6…ab`), dArkOSRE-R36.

**SoC e memória:** RK3326 (4x Cortex-A35), GPU Mali-G31 (Bifrost), PMIC RK817 em `i2c@ff180000`, endereço 0x20.

**Painel** (`dsi@ff450000/panel@0`): 640x480, DSI 4 lanes, `dsi,flags = 0xa03`, formato RGB888.

| Item | Valor |
|---|---|
| Alimentação | RK817 `LDO_REG8` |
| reset | `gpio3 16`, ativo baixo |
| enable | `gpio1 18`, ativo baixo |
| stbyb | `gpio3 15`, ativo alto |
| Atrasos (ms) | prepare 100, reset 100, init 20, enable 200, disable 200, unprepare 20 |
| Timing 60 Hz (nativo) | clock 27,0 MHz; h 640 / fp 120 / sync 10 / bp 120; v 480 / fp 17 / sync 4 / bp 13 |
| Timing 50 Hz | clock 25,5 MHz; h fp 188 / sync 2 / bp 190; v fp 13 / sync 2 / bp 5 |
| Timing 75 Hz | clock 30,6 MHz; h fp 87 / sync 2 / bp 87; v fp 13 / sync 2 / bp 5 |
| Sequência de saída | `05 78 01 28` (display off, 120 ms), `05 78 01 10` (sleep in, 120 ms) |

**Luz de fundo:** PWM `pwm@ff200010` (pwm1), período 40000 ns, 161 níveis (0-160), padrão 80.

**Controle:** 17 botões em GPIO, ativos baixos, intervalo de polling 10 ms.

| Botão | GPIO | Código |
|---|---|---|
| D-pad cima / baixo / esquerda / direita | gpio3 7 / 8 / 10 / 9 | 0x220 / 0x221 / 0x222 / 0x223 |
| A | gpio3 14 | 0x131 (BTN_EAST) |
| B | gpio3 12 | 0x130 (BTN_SOUTH) |
| X | gpio3 13 | 0x133 (BTN_NORTH) |
| Y | gpio3 11 | 0x134 (BTN_WEST) |
| L1 / R1 | gpio3 3 / 0 | 0x136 / 0x137 |
| L2 / R2 | gpio3 2 / 1 | 0x138 / 0x139 |
| F1 / F2 / F3 / F4 / F5 | gpio3 5 / gpio3 6 / gpio0 11 / gpio3 27 / gpio3 4 | 0x2c0 / 0x2c1 / 0x2c2 / 0x2c3 / 0x2c4 |

**Analógicos:** SARADC `saradc@ff288000`, canal 1, multiplexado em 4 eixos. Mux A em `gpio0 13`, mux B em `gpio0 12`, enable do mux em `gpio0 17` (todos ativos baixos). Escala 2, zona morta 64, fuzz 32, flat 32, tuning ±200 em todos os eixos; X e Y do analógico esquerdo invertidos.

**Áudio:** codec do RK817 por I2S (`simple-audio-card`, mclk-fs 256). Rotas: Headphone Jack ← HPOL/HPOR, MIC_IN ← Mic Jack. Habilitação do alto-falante em `gpio3 20`, ativo alto. Detecção de fone em `gpio2 22`, ativo baixo (revisões V21).

**Bateria:** 3188 mAh, qmax 3506 mAh, resistência 113 mΩ, desligamento a 3300 mV. Curva OCV (mV, 0 a 100% em passos de 5%): 3400, 3444, 3493, 3529, 3559, 3582, 3599, 3615, 3634, 3660, 3701, 3759, 3809, 3852, 3886, 3911, 3961, 4012, 4028, 4075, 4182.

**LEDs:** vermelho em `gpio0 5`, azul em `gpio0 0`.

## Apêndice B: GA36-MB V1.2 (Allwinner A33)

Fontes: goodluckOS (GPL-2.0) e o firmware de fábrica (FEX, `lcd.ko`, `udt_joystick.ko`).

**SoC e memória:** A33 (4x Cortex-A7), Mali-400 MP2, DRAM em `0x40000000`. O tamanho diverge entre as fontes: 512 MiB no FEX, no goodluckOS e no handhelds.wiki ("Ram 512mb + ~480 swap"), e 1 GiB segundo o dono do aparelho de teste. Por isso o DTS não tem nó `memory`: o U-Boot detecta a DRAM e preenche o tamanho, e a serial do U-Boot (`DRAM: ...`) confirma na primeira subida. O handhelds.wiki também registra placas V1.0 e V1.1 e variantes A23 (2 núcleos), fora desta versão. PMIC AXP223 em RSB, endereço `0x3a3`. No Linux 6.18 o driver `axp20x` corta a energia no poweroff sem precisar de `system-power-controller`, que o binding nem aceita para a AXP223. O goodluckOS usava `x-powers,system-power-controller` num kernel anterior.

**DRAM (U-Boot):** clock 552 MHz, tipo DDR3, ZQ 15291, ODT habilitado, para1 284295680, mr0 6208, mr1 64, mr2 8, tpr0 4759954, tpr1 28422541, tpr2 483410, tpr12 168, tpr13 67840.

**Reguladores:**

| Regulador | Função | Configuração |
|---|---|---|
| dcdc1 | vcc-io (PB/PF/PG/PH, MMC) | sempre ligado |
| dcdc2 | vdd-sys | sempre ligado |
| dcdc3 | vdd-cpu | 1,04-1,32 V, sempre ligado |
| dcdc5 | vcc-dram | sempre ligado |
| dc1sw | vcc-lcd (painel) | ligado no boot |
| dldo3 | DSI / D-PHY | 3,0 V |
| aldo1, aldo2, aldo3, dc5ldo | — | sempre ligados |

Tensões lidas no boot do firmware de fábrica: dcdc1 3000, dcdc2 1100, dcdc3 1200, dcdc4 1100, dcdc5 1500 (DDR3), aldo1 3000, aldo2 2500, aldo3 3000, dldo3 3000 e dc5ldo 1100 mV. Trip points térmicos de fábrica: 75 e 90 °C ativos, 110 °C crítico. No uso, o clock cai de 1200 para 1104 MHz por volta de 56 °C. Medições e scripts do aparelho em `docs/referencia/ga36-emuelec/`.

**OPPs da CPU:** nesta versão vale a tabela do `sun8i-a33.dtsi` mainline sem alteração: de 120 MHz a **1008 MHz @ 1,20 V** (648 @ 1,04 V; 816 @ 1,10; 912 e 1008 @ 1,20). O firmware de fábrica (FEX) vai até 1200 MHz @ 1,32 V. Os níveis 1104 e 1200 MHz, e os de 1344 e 1536 MHz, ficam para a change de otimização.

**Painel:** controlador JD9366, 640x480, DSI 2 lanes, 71x53 mm, reset `PH7` ativo baixo, alimentação dc1sw. Timing nativo do FEX: clock 30 MHz, htotal 1040, hbp 120, hsync 40, vtotal 518, vbp 12, vsync 6. Na convenção Allwinner o `hbp` inclui o sync; converter ao escrever o modo DRM. Sequências: Apêndice C (painel 1) e `jd9366_panel_2_init_sequence` do goodluckOS (painel 2).

**Luz de fundo:** PWM0 em `PH0`, 50000 ns (20 kHz), não invertido. Níveis 0-100 em passos de 10, padrão 80.

**Controle (driver serial, um único dispositivo):** botões ativos baixos, polling 16 ms.

| Botão | Pino | Código |
|---|---|---|
| D-pad cima / baixo / esquerda / direita | PE9 / PE8 / PE7 / PE6 | 0x220 / 0x221 / 0x222 / 0x223 |
| A / B | **PE13 / PE12** (o goodluckOS os tem invertidos) | 0x130 / 0x131 |
| X / Y | PE11 / PE10 | 0x133 / 0x134 |
| L1 / L2 | PE15 / PE14 | 0x136 / 0x138 |
| R1 / R2 | PE17 / PE16 | 0x137 / 0x139 |
| L3 / R3 | PB3 / PB2 | 0x13D / 0x13E |
| Start / Select | PE4 / PE5 | 0x13B / 0x13A |
| Fn | PE1 | 0x13C |

**Protocolo dos analógicos:** microcontrolador em `uart1` (PG6/PG7), 9600 baud.

- **Pacotes:** 8 bytes, `A7 10 ?? LX LY RX RY 00`. Descartar se o último byte não for `00`; ressincronizar no próximo `A7`.
- **Handshake** (sem ele não chegam eixos): o host envia `A6 01 00 R1 R2 R3`, com três bytes aleatórios. O microcontrolador responde dentro do pacote: com `k` = byte 6, `R1 = ((b3 ^ k ^ 0x5A) - 1)`, `R2 = ((b4 ^ k ^ 0x5A) - 2)`, `R3 = ((b5 ^ k ^ 0x5A) - 3)`, módulo 256. Se a resposta conferir, o host envia uma vez o keepalive `A6 01 01 01 01 01`. São até 3 tentativas.
- **Eixos:** 0-255 com repouso perto de 128. O analógico esquerdo é montado espelhado: `LX = 255 - b3`, `LY = 255 - b4`, `RX = b5`, `RY = b6`.

**Outros periféricos:**

- botões de volume no LRADC: volume+ a 200 mV, volume- a 400 mV, com `vref` fixo de 3,0 V;
- áudio pelo codec interno, com amplificador em `PH9`, ativo alto. Rotas: HP → amplificador → alto-falante, e HP/HPCOM → fone. Sem detecção de fone;
- serial de debug `uart2` em PB0/PB1, 115200;
- `mmc0` é o cartão (cd em `PB4`) e `mmc1` fica em PG;
- LEDs: azul em `PL4` e vermelho em `PG13`;
- USB OTG com id em `PH8`;
- bateria de 3000 mAh, 119 mΩ, 4200 mV cheia, desligamento a 3300 mV.

## Apêndice C: sequências de inicialização dos painéis

**R36S V5:** formato Rockchip `[tipo, atraso_ms, tamanho, dados...]`, em que tipo 0x39 é DCS longo, 0x15 é DCS curto com 1 parâmetro e 0x05 é DCS curto sem parâmetro (375 bytes):

```
39 00 04 b9 f1 12 87
39 00 04 b2 78 04 70
39 00 0b b3 10 10 fc fc 03 ff 00 00 00 00
15 00 02 b4 80
39 00 03 b5 0a 0a
39 00 03 b6 7a 7a
39 00 05 b8 26 22 f0 13
39 00 1c ba 33 81 05 f9 0e 0e 20 00 00 00 00 00 00 00 44 25 00 91 0a 00 00 01 4f 01 00 00 37
15 00 02 bc 47
39 00 06 bf 02 11 00 80 04
39 00 0a c0 73 73 50 50 00 00 12 73 00
39 00 12 c1 73 00 32 32 77 f4 77 77 cc cc ff ff 11 11 00 00 32
39 00 0d c7 b8 00 0a 10 01 09 00 00 ed c5 00 a5
39 00 05 c8 10 40 1e 03
15 00 02 cc 0b
39 00 23 e0 00 07 0d 3f 3f 3f 44 49 06 0b 0c 0f 13 0f 12 16 1f 00 07 0d 3f 3f 3f 44 49 06 0b 0c 0f 13 0f 12 16 1f
39 00 08 e1 11 11 91 00 00 00 00
39 00 0f e3 07 07 0b 0b 0b 0b 00 00 00 00 ff 04 c0 10
39 00 40 e9 c8 10 02 00 00 b0 b1 11 31 23 28 80 b0 b1 27 08 00 04 02 00 00 00 00 04 02 00 00 00 88 88 ba 60 24 08 88 88 88 88 88 88 88 ba 71 35 18 88 88 88 88 88 00 00 00 01 00 00 00 00 00 00 00 00 00
39 00 3e ea 97 0a 82 02 03 07 00 00 00 00 00 00 81 88 ba 17 53 88 88 88 88 88 88 80 88 ba 06 42 88 88 88 88 88 88 23 00 00 02 a5 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
39 00 04 ef ff ff 01
05 fa 01 11
05 32 01 29
```

O fim da sequência é: sleep out (`11`) seguido de 250 ms, depois display on (`29`) seguido de 50 ms.

**GA36 painel 1** (JD9366, tabela do `lcd.ko`): cada página é selecionada com `FF 30 52 <página>` e cada par é `registrador=valor`, enviado como DCS de 1 parâmetro.

```
página 01: E3=00 20=90 25=10 28=6F 29=01 2A=DF 30=58 37=9C 38=A7 39=53 44=00 49=3C 59=FE 5C=00
           60=8F 80=20 91=77 92=77 A0=55 A1=50 A3=58 A4=9C A7=02 A8=01 A9=21 AA=FC AB=28 AC=06
           AD=06 AE=06 AF=03 B0=08 B1=26 B2=28 B3=28 B4=03 B5=08 B6=26 B7=08 B8=26
página 02: B0=0B B1=16 B2=17 B3=2C B4=32 B5=3B B6=29 B7=40 B8=0D B9=05 BA=12 BB=10 BC=12 BD=15
           BE=19 BF=0E C0=16 C1=0A D0=0C D1=17 D2=14 D3=2E D4=32 D5=3C D6=22 D7=3D D8=0D D9=07
           DA=13 DB=13 DC=11 DD=15 DE=19 DF=10 E0=17 E1=0A
página 03: 00=00 01=00 02=00 03=00 04=61 05=80 06=C7 07=01 08=82 09=83 30=00 31=00 32=00 33=00
           34=61 35=C5 36=80 37=23 40=82 41=83 42=80 43=81 44=11 45=E2 46=E1 47=11 48=E4 49=E3
           50=02 51=01 52=04 53=03 54=11 55=E6 56=E5 57=11 58=E8 59=E7 7E=08 81=0F 84=0C 85=0D
           86=07 87=04 88=05 89=06 8A=00 97=0F 9A=0C 9B=0D 9C=07 9D=04 9E=05 9F=06 A0=00 E0=02
           E1=52
página 00: 36=02, depois 11 (sleep out) + 120 ms, depois 29 (display on) + 20 ms
```

**GA36 painel 2:** a sequência `jd9366_panel_2_init_sequence` do goodluckOS, commit `8d676e2327a6`. Ela não foi verificada contra um firmware de fábrica.
