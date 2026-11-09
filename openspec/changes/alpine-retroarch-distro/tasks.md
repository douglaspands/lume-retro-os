# Tasks

## 1. Fundação do build

- [x] 1.1 Criar a estrutura de diretórios do D1 (`board/`, `kernel/`, `aports/`, `rootfs/`, `initramfs/`, `src/r36os/`, `tests/vm/`) e o pacote Python `r36os` no `pyproject.toml`; verificar que `uv run r36os --help` lista `build`, `vm` e `test-vm`
- [x] 1.2 Implementar a validação de alvo (`r36s`, `ga36`, `vm`) e o diretório de cache fora do repositório; verificar com teste unitário que um alvo inválido falha antes de criar arquivos e lista os alvos válidos
- [x] 1.3 Criar os Containerfiles do builder Alpine v3.24 (abuild, mtools, squashfs-tools, syslinux, jq) e do cross-compilador (gcc aarch64/armhf, dtc, bc, flex, bison); verificar que `podman build` dos dois termina sem erro
- [x] 1.4 Gerar a chave de assinatura local do abuild no cache e configurar o repositório local `out/repo/<arch>`; verificar que um APKBUILD trivial de teste é construído e instalado a partir do repositório local

## 2. Userland: RetroArch e cores

- [x] 2.1 Verificar se o `retroarch` do Alpine v3.24 tem KMS, EGL, GLES e udev (`retroarch --features` no container) e registrar o resultado em `aports/README.md`; se faltar algo, criar `aports/retroarch` com `--enable-kms --enable-egl --enable-opengles --disable-x11 --disable-wayland` e verificar `--features` de novo
- [x] 2.2 Criar APKBUILDs locais para `libretro-snes9x2010`, `-snes9x`, `-genesis-plus-gx`, `-picodrive`, `-fbneo`, `-mame2003-plus` e `-pcsx-rearmed` (partindo do `testing` quando existir); verificar que cada um compila para x86_64 e que o `.so` resultante é listado pelo `retroarch --list-cores` (ou carrega com `retroarch -L ... --max-frames=1` sem conteúdo)
- [x] 2.3 Escrever `rootfs/packages.txt` (base Alpine, OpenRC, mesa-dri-gallium, retroarch, cores, exfatprogs, jq, seatd, alsa-utils) e `board/<alvo>/hw-packages.txt`; verificar com teste que a lista comum não contém pacotes de hardware

## 3. Rootfs e SYSTEM

- [x] 3.1 Implementar o estágio de rootfs (`apk add --root` no container do arch alvo, usuário `game`, grupos `video`/`input`/`audio`, root sem senha só na serial, `rootfs/overlay/`); verificar que o rootfs x86_64 tem `/sbin/init` do OpenRC e o usuário `game` com uid 1000
- [x] 3.2 Gerar o manifesto de pacotes (nome e versão) junto com cada rootfs; verificar com teste que dois builds seguidos do mesmo alvo produzem manifestos idênticos
- [x] 3.3 Gerar o `SYSTEM` squashfs com zstd e falhar acima de 768 MiB; verificar com `unsquashfs -s` e com teste que um rootfs inflado artificialmente faz o build falhar

## 4. Initramfs e boot da VM

- [x] 4.1 Escrever `initramfs/init` (D6): espera do cartão por PARTUUID, montagem da BOOT somente leitura, loop do `SYSTEM`, overlay com tmpfs de 32 MiB e `switch_root`; incluir os binários estáticos (`sfdisk`, `mkfs.exfat`, `fsck.exfat`) e, na VM, os módulos necessários; verificar com teste de shell (busybox em container) a lógica de decisão de partições sobre imagens de disco falsas
- [x] 4.2 Implementar a criação da partição 2 no primeiro boot, a regra de nunca formatar dados existentes e o `fsck.exfat -p` a cada boot; verificar nos testes do 4.1 os casos sem p2, p2 exFAT existente, p2 não exFAT e p2 suja
- [x] 4.3 Montar a `ROMS` em `/storage` (dono `game`, `noatime`) e criar a estrutura de pastas e o `LEIA-ME.txt`; verificar no teste que pastas apagadas voltam sem perder o conteúdo das outras
- [x] 4.4 Criar `board/vm/extlinux.conf` (serial + `tty1`, `video=640x480`, sem `quiet`) e o estágio de imagem: MBR com assinatura fixa, BOOT FAT32 de 1 GiB em 16 MiB via `mtools` e SYSLINUX no MBR; verificar com `sfdisk -d` que a tabela é MBR com uma única partição no setor 32768 e com `mdir` que a BOOT tem kernel, initramfs, `extlinux/` e `SYSTEM` (a pasta `logs/` saiu da BOOT na 5.1)
- [x] 4.5 Implementar `uv run r36os vm` (QEMU/KVM em container, cópia descartável do disco, janela com `virtio-vga-gl`/virgl, áudio do host) e `--headless` (serial no terminal, QMP); verificar que a VM sobe até o prompt de login da serial e que o boot é verboso nos dois modos
- [x] 4.6 Criar o serviço `r36os-selftest` (ativado por `r36os.selftest=1`, marcadores `SELFTEST <nome> PASS|FAIL`) e o `uv run r36os test-vm`, que sobe a VM sem tela, coleta os marcadores, guarda o log serial e informa o tempo até o frontend; verificar com as primeiras checagens: criação da `ROMS`, `/boot` somente leitura e perda de escrita em `/var/tmp` após reboot
- [ ] 4.7 Documentar em `docs/VM.md` como gerar e rodar a VM, os atalhos de teclado e como ler o log do teste; verificar executando os comandos documentados numa build limpa

## 5. Serviços de sistema: logs, resumo e persistência

- [ ] 5.1 Criar o serviço de log de boot (dmesg + log do OpenRC + resumo de hardware) em `ROMS/logs/boot/boot-<n>.log`, com o contador de boot comum a todos os logs (`ROMS/logs/.boot`) e `keep_boots` do `logs.conf`; só sem `ROMS`, cair para `BOOT/logs/` (remontagem gravável só durante a escrita, mantendo 10). Tirar `logs/` da imagem da BOOT, mover o log de falha do frontend para `ROMS/logs/frontend/` e atualizar `motd`, `docs/VM.md` e `docs/FRONTEND.md`. Verificar no self-test, com `keep_boots=10`, que após 11 boots existem exatamente 10 logs em `ROMS/logs/boot/`; que apagar `ROMS/logs/` não afeta o boot e a pasta volta; e que a BOOT não tem `logs/`
- [x] 5.2 Criar o resumo de hardware antes do frontend (vídeo, áudio, controle, bateria, ROMS, cada um ok ou falha); adicionar checagem ao self-test e verificar que na VM a bateria aparece ausente sem bloquear o boot
- [x] 5.3 Implementar o `r36os-persist` (D7): semente de `system/retroarch` com os padrões de fábrica, sincronização atômica com `inotifyd` e debounce de 2 s, `flush` sob demanda, leitura de `system/etc/timezone` e `system/etc/hostname`; adicionar ao self-test a persistência de uma opção após reboot e a restauração de fábrica ao apagar `system/`
- [x] 5.4 Adicionar o `sync -f` em saves e estados concluídos (`/storage/saves`, `/storage/states`); verificar no self-test que um state criado e seguido de reset abrupto da VM (QMP `system_reset`) ainda existe e carrega
- [ ] 5.5 Criar o `r36os-logd` (D14): diretório em RAM, descarga em lote para `ROMS/logs/` a cada `flush` s e no desligamento, `logs.conf` com os padrões no primeiro boot, marcador de desligamento limpo e rotação por tipo com teto total; verificar com teste de shell (busybox em container) a rotação e o teto, e no self-test que após um `system_reset` o boot seguinte registra "desligamento abrupto" e as métricas do último lote existem
- [ ] 5.6 Criar o retrato do hardware por boot (`hw/boot-<n>.txt`) e os eventos de boot, serviços, ROMS, kernel e desligamento (`eventos.log`); verificar no self-test que o retrato tem CPU, frequências, memória, zonas térmicas, bateria e armazenamento, e que um serviço com falha forçada aparece como `FALHA`
- [ ] 5.7 Criar o amostrador de métricas (`metricas/boot-<n>.csv` a cada `interval` s, com estado do frontend pelo `GET_STATUS` local) e os eventos de jogo aberto e fechado, temperatura e bateria baixa, guardando também o log do frontend por boot; verificar no self-test que um jogo aberto gera amostras em jogo e os dois eventos com core e duração, e medir na VM o custo de CPU do amostrador
- [ ] 5.8 Documentar o formato em `docs/LOGS.md` (colunas, categorias, rotação, `logs.conf`); verificar no self-test que `enable=0` desliga os coletores e que o cabeçalho do CSV bate com o documento (teste)

## 6. Catálogo de sistemas e listas de jogos

- [x] 6.1 Escrever `/usr/share/r36os/systems.json` conforme a tabela do D8, com core padrão, padrão por arquitetura e alternativos; verificar com teste que cada core referenciado tem pacote em `packages.txt` e que o JSON segue o esquema documentado
- [x] 6.2 Implementar o `r36os-playlists` (ash + jq): uma `.lpl` por sistema com jogos, filtrando por extensão, nome sem extensão e core fixo pelo arquivo, usando o padrão por arquitetura; verificar com testes de fixture que extensões fora do catálogo são ignoradas, sistemas vazios não geram lista e armv7 usa `gpsp` no GBA
- [x] 6.3 Escrever o `LEIA-ME.txt` (pastas, extensões e BIOS do PS1 com nomes aceitos e a opção HLE) e o documento do esquema do catálogo em `docs/CATALOG.md`; verificar que todo sistema do `systems.json` aparece no `LEIA-ME.txt` (teste)
- [x] 6.4 Produzir as ROMs de teste livres no build (fontes mínimos com `cc65`, `rgbds` e equivalentes, ou homebrew com licença de redistribuição) num disco FAT só da VM; verificar que o self-test abre um jogo por core instalado com `--max-frames=600` e encontra `core loaded` no log, e que nenhum jogo de teste está nas imagens `r36s`/`ga36`

## 7. Sessão do frontend e menu do RetroArch

- [x] 7.1 Criar o serviço OpenRC `frontend`, `/etc/conf.d/frontend` e o `r36os-session` (D10): roda como `game` no `tty1`; saída 0 faz `flush` e `poweroff`; 3 falhas em 60 s param e mostram o erro com o caminho do log; verificar no self-test o desligamento ao sair e com um frontend falso que falha sempre que a terceira falha para o laço
- [x] 7.2 Configurar o acesso ao DRM e à entrada sem root (`seatd`/libseat, ou capability no wrapper se o RetroArch não usar libseat) e, só para `x86_64`, o `aports/mesa` local com llvmpipe e virgl (D2); verificar na VM que o processo do RetroArch roda como `game` e renderiza por GLES no virgl (`video_driver=gl`, contexto KMS, sem llvmpipe), e com teste que o `mesa` local só entra no alvo `vm`
- [x] 7.3 Mapear o teclado da VM e escrever o `retroarch-lume.cfg` (D11: Ozone, `retroarch-assets`, menu completo sem kiosk e sem Core Updater, pausa no menu, Start + Select abre o menu, nenhuma combinação encerra, diretórios de saves e estados por sistema); verificar no self-test, via QMP `send-key`, que Start + Select abre o menu sem encerrar, que Shift direito + S abre o menu e que Esc não encerra
- [x] 7.4 Trocar o tema Lume pelo menu padrão do RetroArch (D11): remover `theme/lume/`, `retroarch-theme-lume` e o código do tema, e instalar `retroarch-assets` e `retroarch-joypad-autoconfig`; verificar com teste que o `retroarch-lume.cfg` usa Ozone e os assets oficiais, sem opções `xmb_`, e que a lista de pacotes não tem pacote de tema
- [ ] 7.5 Calibrar `menu_scale_factor` e `ozone_font_scale_factor_global` na VM a 640x480 com capturas (`tests/vm/capture_menu.py`, QMP `screendump`, em `out/vm/capturas/`); verificar visualmente que nenhum texto do menu fica cortado
- [x] 7.6 Documentar em `docs/FRONTEND.md` como trocar de frontend (contrato de pastas, `systems.json` e `/etc/conf.d/frontend`); verificar no self-test, com um frontend falso instalado e configurado, que ele sobe no lugar do RetroArch
- [ ] 7.7 Trocar no `aports/retroarch` o rótulo e a descrição de "Sair do RetroArch" por "Desligar" (en, pt_BR, es), com falha do `prepare()` se a troca não acontecer; verificar que o pacote compila e que o menu da VM mostra "Desligar"
- [ ] 7.8 Repassar à VM os controles do PC (`virtio-input-host-pci`, detecção automática, `--gamepad`, `--no-gamepad`) e compartilhar uma pasta do PC somente leitura (`--roms`/`--share`, virtio-9p e o serviço `r36os-hostshare`, só na `vm`); verificar com teste dos argumentos do QEMU/podman e, na VM, que os jogos da pasta aparecem nas listas e que a pasta está montada `ro`

> **Marco: VM validada.** Os grupos 1 a 7 entregam a imagem `vm` completa, com `uv run r36os vm` e `uv run r36os test-vm` passando. Parar aqui para o usuário testar a VM antes de seguir para os consoles. Nada até este ponto precisa de emulação de ARM no host.

## 8. Preparação ARM

> **Ordem de execução:** o único console disponível é o GA36. Depois da 8.1, as tarefas 8.2 e 8.3 são feitas primeiro para `armv7`, seguidas do grupo 9 até um cartão testável no GA36. `aarch64` e o grupo 10 vêm depois. As tarefas 8.2 e 8.3 só são marcadas quando os dois arches estiverem feitos.

- [x] 8.1 Pedir confirmação ao usuário e registrar `qemu-user` no binfmt do host; verificar que `podman run --rm --arch arm64 alpine:3.24 uname -m` imprime `aarch64` e que `--arch arm/v7` imprime `armv7l`
- [ ] 8.2 Compilar os pacotes locais para aarch64 e armv7 sob emulação, com `ccache` no cache; verificar que os três repositórios locais têm o mesmo conjunto de pacotes e versões
- [ ] 8.3 Gerar o rootfs e o `SYSTEM` de aarch64 e armv7 com os estágios do grupo 3; verificar com teste que os manifestos de userland coincidem com o da `vm`, exceto a arquitetura

## 9. GA36-MB V1.2 (A33)

- [ ] 9.1 Portar para `kernel/patches/` o driver do painel JD9366 com as sequências 1 (Apêndice C) e 2 (goodluckOS); verificar que o kernel ARM compila sem warnings novos e que o teste de host compara a tabela do painel 1 com o Apêndice C
- [ ] 9.2 Portar o driver do controle serial (serdev, handshake, parser, botões GPIO, um único dispositivo de entrada) com o protocolo do Apêndice B; verificar com teste de host do parser (pacotes válidos, lixo, ressincronização, resposta do handshake e inversão do analógico esquerdo)
- [x] 9.3 Escrever os DTS `sun8i-a33-ga36-mb-v1.2-panel1.dts` e `-panel2.dts` em `board/ga36/dts/` com os valores do Apêndice B (A em PE13 e B em PE12), `cpu-supply` no `dcdc3` e as OPPs e zonas térmicas do `sun8i-a33.dtsi` mainline sem alteração; verificar com `dtc` e `dt-validate` sem erros e com teste que compara pinos e reguladores com o Apêndice B e que o DTS não redefine OPPs nem trip points
- [ ] 9.4 Criar `board/ga36/kernel.config` (LTS, fbcon e drivers de boot embutidos, lima, sun4i DSI, AXP22x, LRADC, codec, `cpufreq-dt` com o governor padrão do kernel e o thermal do sun8i) e compilar `zImage`, DTBs e módulos no container de cross; verificar que o `zImage` e os dois DTBs aparecem em `out/ga36/` e, com teste do `.config`, que `CPUFREQ_DT` e `SUN8I_THERMAL` estão ligados e o governor padrão não foi trocado
- [ ] 9.5 Compilar o U-Boot sunxi do A33 com a DRAM do Apêndice B e gravá-lo em 8 KiB na imagem `ga36`; verificar por teste que a MBR do setor 0 continua intacta e que o binário começa em 8 KiB
- [ ] 9.6 Criar `board/ga36/extlinux.conf` com as entradas do painel 1 (padrão) e do painel 2, serial `ttyS1` 115200 e `tty1`; gerar `ga36.img`; verificar com teste que as duas entradas existem e apontam para DTBs presentes na BOOT
- [ ] 9.7 Criar a autoconfiguração do RetroArch para o controle do GA36 e escrever `docs/BRINGUP-GA36.md` (gravar o cartão, serial, checagens do resumo de hardware e como trocar o painel); verificar o checklist na primeira subida real: painel, controle com handshake, áudio, volume, bateria e desligamento

## 10. R36S "V5" (RK3326)

- [ ] 10.1 Adicionar ao `panel-sitronix-st7703` (em `kernel/patches/`) a variante do painel do R36S V5 com a sequência e os atrasos dos Apêndices A e C; verificar que o kernel arm64 compila e que o teste de host compara a sequência com o Apêndice C
- [ ] 10.2 Escrever `board/r36s/dts/rk3326-r36s-v5.dts` (painel, luz de fundo, `gpio-keys`, `adc-joystick` sobre `io-channel-mux`, RK817 com codec, carregador e `simple-battery` com a curva OCV, LEDs, SD, `cpu-supply` e as OPPs e zonas térmicas do `rk3326.dtsi` mainline sem alteração); verificar com `dtc` e `dt-validate` sem erros e com teste que compara pinos e códigos com o Apêndice A
- [ ] 10.3 Implementar o `r36os-padmerge` (C, uinput, "R36S Gamepad") e empacotá-lo; verificar com teste na VM usando dispositivos `uinput` falsos que botões e eixos de dois dispositivos saem num único controle
- [ ] 10.4 Criar `board/r36s/kernel.config` (LTS, fbcon e drivers de boot embutidos, panfrost, DSI Rockchip, RK817, SARADC, iio-mux, `cpufreq-dt` com o governor padrão do kernel e o thermal da Rockchip) e compilar `Image`, DTB e módulos no container de cross; verificar que os artefatos aparecem em `out/r36s/`
- [ ] 10.5 Compilar o U-Boot a partir do `odroid-go2_defconfig` (com o blob de DDR do `rkbin` registrado com hash, se necessário) e gravar `idbloader` no setor 64 e `u-boot.itb` no setor 16384; verificar por teste os offsets na imagem
- [ ] 10.6 Criar `board/r36s/extlinux.conf` (entrada padrão R36S V5, serial `ttyS2` a 1500000 no U-Boot e no kernel, `tty1`) e gerar `r36s.img`; verificar com teste o layout e a presença do DTB
- [ ] 10.7 Criar a autoconfiguração do "R36S Gamepad" (F1 = Select, F2 = Start, F3 = L3, F4 = R3, F5 = Fn, a confirmar) e escrever `docs/BRINGUP-R36S.md`; verificar o checklist na primeira subida real: painel, botões (incluindo a ordem de F1-F5), analógicos, áudio com alto-falante, bateria e desligamento

## 11. Integração e liberação

- [x] 11.1 Implementar a regra de liberação: `uv run r36os build --all` gera e testa a `vm` primeiro e só marca `r36s`/`ga36` como liberadas se o `test-vm` passar; verificar com um defeito injetado na VM que as imagens de console não são marcadas
- [ ] 11.2 Verificar com teste a paridade entre os manifestos `vm`, `r36s` e `ga36` do mesmo build (diferenças só em pacotes de hardware e na arquitetura) e que todos os cores do catálogo estão nos três
- [ ] 11.3 Rodar o `test-vm` completo numa build limpa e registrar no `README.md` o tempo de boot até o frontend, o tamanho do `SYSTEM` e as instruções para gravar o cartão e restaurar a fábrica; verificar que um cartão de 4 GB fica com pelo menos 2 GB livres na `ROMS`
