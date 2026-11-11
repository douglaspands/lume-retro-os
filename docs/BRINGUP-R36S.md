# R36S "V5": gravar, subir e conferir

Guia da primeira subida e da conferência do R36S V5 (Rockchip RK3326, aarch64) com a
imagem `console`, o cartão único do GA36 e do R36S (change `r36s-single-card`).

> **Estado:** a imagem ainda não foi testada no aparelho. As seções marcadas com
> *a medir* são preenchidas com os resultados das tarefas 1.1, 4.4 e 9.x da change.

## 1. Gerar e gravar

```sh
uv run r36os build console                          # 1ª vez: R36OS_GA36_FACTORY e R36OS_R36S_FACTORY (README)
uv run r36os flash console /dev/sdX --full --eject  # cartão novo: imagem + ROMS no resto do cartão
uv run r36os flash console /dev/sdX --update --eject   # cartão do GA36 que já existe: vira cartão único, a ROMS fica
```

O mesmo cartão serve aos dois consoles: basta trocar de aparelho.

## 2. A cadeia de boot de fábrica

O R36S sobe pela cadeia do próprio aparelho, a mesma do cartão que veio com ele (um ArkOS
para o "R36S V5"). Ela é binário fechado, fica fora do git e o build a lê da cópia do
cartão original (`R36OS_R36S_FACTORY`), conferida por SHA256 (`src/r36os/r36s_vendor.py`).

| Etapa | Onde está no cartão | O que faz |
|---|---|---|
| BROM do RK3326 | (no SoC) | lê o `idbloader` **só no setor 64** (provado: no 1088 não inicia) |
| `idbloader` | setores 64 a 405 | inicializa a DDR e carrega o U-Boot |
| `uboot.img` (`LOADER`) | setor 16384, cópias a cada 2048 até 22528 | U-Boot da linha Hardkernel (`odroidgoa-uboot-config`) |
| `trust.img` (`BL3X`) | setores 24576 e 28672 | BL31 (ARM Trusted Firmware): PSCI para ligar os núcleos e desligar |
| `boot.ini` | raiz da `BOOT` | script lido pelo U-Boot: carrega o kernel e o DTB e chama `booti` |

O `boot.ini` de fábrica carrega `Image`, `uInitrd` e `rk3326-r35s-linux.dtb` de
`mmc 1:1`. O nosso (`board/r36s/boot.ini`) carrega `r36s/Image` (kernel com o initramfs
embutido) e `r36s/rk3326-r36s-v5.dtb`, sem `uInitrd`; a linha de comando fica no kernel
(`CONFIG_CMDLINE_FORCE`: `root=PARTUUID=4c554d32-01`, `ttyS2` a 1500000 e `tty1`).

**Tarefa 1.1, o U-Boot lê o nosso `boot.ini`?** *A medir.* O primeiro boot da imagem
`console` responde: se o LED azul acende (o initramfs liga o LED de status ao chegar ao
`init`) ou as mensagens do kernel aparecem no painel, o `boot.ini` foi lido.

## 3. O cartão único

| Setores | Conteúdo | Origem |
|---|---|---|
| 0 | MBR (assinatura `4c554d32`, só a `BOOT`) | build |
| 1 a 15 | área de fábrica do GA36 | GA36 |
| 16 a 63 | boot0 do GA36 encolhido para 24 KiB (soma eGON recalculada) | GA36 |
| 64 a 405 | `idbloader` | R36S |
| 16384 a 32767 | `uboot.img` (x4) e `trust.img` (x2) | R36S |
| 38192 em diante | U-Boot 2017, tabela `softw411`, FAT "bootloader", env | GA36 |
| 172032 | imagem de boot Android do painel 1 do GA36 | build |
| 262144 | `BOOT` (FAT32, 1 GiB): `VERSION`, `boot.ini`, `ga36/`, `r36s/` | build |
| depois | `ROMS` (exFAT): jogos, saves, configuração e logs dos dois | `flash` ou 1º boot |

O build monta a área a partir das duas cadeias e confere que nenhuma região do R36S cai
sobre dados do GA36 (`src/r36os/bootarea.py`). O initramfs de cada console monta o próprio
sistema: `BOOT/r36s/SYSTEM` no R36S, `BOOT/ga36/SYSTEM` no GA36.

## 4. Primeiro boot

- **Sinais de vida, em ordem:** o logo do fabricante (U-Boot de fábrica), depois as
  mensagens do kernel no painel, o **LED azul** aceso (o kernel chegou ao `init`) e o menu
  do RetroArch. *Tempo até o menu: a medir.*
- **Tela preta depois do logo:** o kernel não subiu ou o painel não acendeu. Se o LED
  azul acende, o kernel está rodando e o problema é o painel: os logs vão para a `ROMS`
  mesmo assim (`ROMS/logs/boot/`, pelo PC).
- **Serial (opcional):** `ttyS2` (UART2, pinos m1), **1500000 baud**, a velocidade do
  bootloader de fábrica do início ao fim. Um adaptador USB-serial de 3,3 V encurta muito
  o diagnóstico.

**Tarefa 4.4, primeira subida (risco do BL31 de fábrica com o kernel mainline):** *a
medir.* Registrar aqui se os quatro núcleos sobem (`nproc` = 4 no `hw/boot-<n>.txt`) e se
o desligamento corta a energia.

## 5. Controle

Os botões (`gpio-keys`) e os dois analógicos (`adc-joystick`, SARADC canal 1 atrás de um
multiplexador) são unidos pelo serviço `r36os-padmerge` num único **"R36S Gamepad"**, com
os mesmos códigos de botão do GA36, então a autoconfiguração do RetroArch tem os mesmos
índices (`/usr/share/libretro/autoconfig/udev/R36S Gamepad.cfg`). Os botões de volume são
um dispositivo à parte (`volume-keys`), como no GA36.

| Tecla no DTS | Função provisória | Confirmar |
|---|---|---|
| F1 | Select | *a medir* |
| F2 | Start | *a medir* |
| F3 | L3 | *a medir* |
| F4 | R3 | *a medir* |
| F5 | menu (como o Fn do GA36) | *a medir* |

A ordem e a inversão dos eixos dos analógicos seguem o DTS de fábrica e o Odroid Go3:
*a medir* (tarefa 9.5).

## 6. Checklist de conferência

| Item | Como conferir | Onde ver |
|---|---|---|
| Boot | LED azul e menu do RetroArch | aparelho; `boot/boot-<n>.log` com `== console: r36s` |
| Núcleos e desligamento | 4 núcleos; desligar pelo menu corta a energia | `hw/boot-<n>.txt`; aparelho |
| Painel e brilho | imagem desde as mensagens do kernel, 640x480 | tela |
| GPU | renderer `Panfrost` (não `llvmpipe`) | `frontend/boot-<n>.log` |
| Controle | todos os botões, F1-F5 e os dois analógicos no menu e num jogo | tela |
| Áudio | som no alto-falante; com fone, a troca é a tarefa 6.6 | ouvido; `events.log` sem `audio FAIL` |
| Taxa do painel | ~59,02 Hz (`video_refresh_rate` do `retroarch-r36s.cfg`) | métricas (`fps`) |
| Bateria | porcentagem e corrente | `metrics/boot-<n>.csv` (`bat_*`) |
| Temperatura | dentro das zonas do `rk3326.dtsi` | `metrics/boot-<n>.csv` |
| Cartão único | o mesmo cartão no GA36 e de volta no R36S; um save passa entre os dois | tarefas 9.1 a 9.4 |

## 7. Medido no aparelho

*A preencher com os resultados das tarefas 1.1, 4.4 e 9.1 a 9.5.*
