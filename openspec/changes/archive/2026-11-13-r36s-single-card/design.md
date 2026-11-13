# Design

## Context

Ver `proposal.md` (Why). O estado de partida:

- **GA36** (change `alpine-retroarch-distro`, arquivada): imagem `ga36` com a área de boot
  de fábrica de 128 MiB (`src/r36os/vendor.py`, `R36OS_GA36_FACTORY`, SHA256 dos setores
  1 a 262143), a imagem de boot Android no setor 172032 (zImage + DTB anexado + initramfs
  embutido + `CMDLINE_FORCE` com `root=PARTUUID=4c554d32-01`) e a `BOOT` no setor 262144.
- **R36S**: só o esqueleto: o alvo `r36s` em `targets.py`, `board/r36s/` com `disk-id`
  (`4c554d31`), `serial`, `hw-packages.txt` e um `kernel.config` com só o ZRAM;
  `image.py` levanta `NotImplementedError` e `kernel.KERNEL_TARGETS` só tem o `ga36`. As
  decisões do R36S da change anterior (kernel, DTS, painel, `r36os-padmerge`) e os dados
  de hardware (Apêndices A e C) estão em
  `openspec/changes/archive/2026-11-11-alpine-retroarch-distro/design.md` e valem aqui,
  exceto o bootloader (D4).
- **Provas no aparelho (2026-11-11, P-21):** o BROM do RK3326 só lê o `idbloader` no
  setor 64 (com ele em 1088 não inicia); o boot0 do GA36 (eGON de 32 KiB, código até o
  setor 59, resto `0xFF`) encolhido para 24 KiB com a soma recalculada inicia o GA36; o
  bloco `RSAK` dos setores 80 a 277 não é usado; com o mesmo primeiro 1 MiB, o R36S
  iniciou o ArkOS e o GA36 chegou ao menu do Lume.
- **Cartão de fábrica do R36S** (backup do usuário, ArkOS para o "R36S V5"): `idbloader`
  nos setores 64 a 405, `uboot.img` (cabeçalho `LOADER`) em 16384 com cópias a cada 2048
  setores até 22528, `trust.img` (`BL3X`) em 24576 e 28672, partição 1 (FAT, `BOOT`) em
  32768. O U-Boot é da linha Hardkernel (`odroidgoa-uboot-config`) e lê o `boot.ini` da
  partição 1 (`load mmc 1:1 ...`, `booti`). Curiosidade não resolvida: o `boot.ini` pede
  `rk3326-r35s-linux.dtb` e `uInitrd`, que não existem na partição, e mesmo assim o
  aparelho inicia (D5, tarefa 1.1).
- **Tempo de build**: o build não pode rodar em paralelo, e o ARM roda sob `qemu-user`.

## Goals / Non-Goals

**Goals:**

- Um build gera um cartão que inicia nos dois consoles, com uma `ROMS` só.
- Cada sistema continua com o próprio `SYSTEM`, kernel e camada de hardware, sem
  condicional de console dentro do userland além do que já existe (`/etc/r36os/board`).
- Todo layout de setor é conferido no build e nos testes unitários, sem precisar do
  aparelho para pegar uma regressão.

**Non-Goals:**

- U-Boot mainline (GA36: P-19; R36S: pendência nova). A cadeia de fábrica de cada um é a
  única que roda nesta versão.
- Ajuste fino de flags para Cortex-A35 (os pacotes locais do aarch64 usam as flags padrão
  do Alpine, como o armv7 na change anterior; a otimização é do P-10/P-24).
- Encolher a config do kernel arm64 além do necessário para o boot e o tamanho.

## Decisions

### D1. Imagem `console` montada a partir de duas camadas de hardware

```
 r36os build console
   |
   +-- camada ga36 (armv7):  pacotes -> initramfs -> kernel+DTBs+android-boot -> SYSTEM
   +-- camada r36s (aarch64): pacotes -> initramfs -> kernel Image + DTB      -> SYSTEM
   |        (uma depois da outra, nunca em paralelo)
   v
 imagem console: area de boot combinada (D2) + BOOT (D5) -> console.img
                 arquivada em out/images/console/<timestamp>/
```

`ga36` e `r36s` continuam como `Target` em `targets.py` (arquitetura, plataforma do
container, `board/<nome>/`), mas deixam de ser alvos de imagem: a CLI de `build` e de
`flash` aceita `console` e `vm`. Os dois `SYSTEM` saem da mesma revisão e da mesma
`VERSION` (um timestamp por build), e o `build.json` registra as duas camadas (kernel,
patches, `system_bytes` de cada uma, bootloaders de fábrica).

- *Alternativa descartada:* manter `ga36.img` e `r36s.img` e uma terceira imagem
  combinada. Seriam três produtos para testar, e um cartão gravado com a imagem de um só
  console não serviria ao outro, que é o que a change quer evitar.
- *Nome:* `console` descreve o produto (o cartão dos consoles) sem amarrar a um aparelho.

### D2. Layout da área de boot (setores de 512 B)

```
 setor        conteudo                                 origem
 0            MBR (assinatura 4c554d32, so a BOOT)     build
 1-15         area de fabrica do GA36 (PHOENIX_CARD)   GA36
 16-63        boot0 encolhido: eGON 24 KiB, soma nova  GA36 (D3)
 64-405       idbloader                                R36S
 406-2047     zero (o RSAK de 80-277 some sob o idbloader e o resto fica zerado)
 2048-9216    restos da area do GA36 (mantidos como estao)
 16384-32767  uboot.img (x4) e trust.img (x2)          R36S
 38192        U-Boot 2017                              GA36
 40960        tabela softw411                          GA36
 73728        FAT "bootloader"                         GA36
 139264       env do U-Boot                            GA36
 172032       android-boot do painel 1 (nosso)         build
 262144       BOOT (FAT32, 2 GiB)                      build
```

O build parte da área de 128 MiB do GA36, aplica o boot0 encolhido e copia por cima as
regiões do R36S. Antes de copiar, confere que cada setor do R36S cai em setor zerado da
área do GA36 ou nos setores 64 a 277 (fim do boot0 original e bloco `RSAK`), e falha
listando os conflitos. As regiões são uma tabela declarativa (início, fim, origem) usada
pelo build e pelos testes.

- A assinatura e o início da `BOOT` são os do GA36 de hoje, mas a `BOOT` tem 2 GiB (antes
  1 GiB), para caber o crescimento previsto (catálogo, Wi-Fi, um terceiro sistema,
  atualização A/B) sem mudar o layout de novo. Decisão do usuário em 2026-11-11: um cartão
  do GA36 gravado antes não passa no `check_update` (tamanho da partição 1 diferente) e
  precisa de gravação completa. Entre cartões `console`, o `--update` grava de 8 KiB até o
  fim da `BOOT`. O limite de 448 MiB por `SYSTEM` fica; pode subir depois sem mudar o
  layout.
- O `board/r36s/disk-id` sai; a assinatura vira uma constante da imagem `console`.

### D3. Boot0 encolhido

O cabeçalho eGON tem o tamanho em `0x10` e a soma em `0x0C`. A soma é a soma de 32 bits
(módulo 2^32) de todas as palavras do boot0, calculada com o campo da soma valendo
`0x5F0A6C39`. O cálculo reproduz a soma de fábrica (`0x67972d80`) e, com 24 KiB,
`0x67971580`, a que iniciou o GA36. O build:

1. confere `eGON.BT0` no setor 16 e que os bytes de 24 KiB a 32 KiB são todos `0xFF`
   (senão falha: o boot0 deste aparelho não cabe);
2. grava o tamanho 24576, recalcula a soma e escreve só os setores 16 a 63.

O SHA256 da área de fábrica continua sendo o do arquivo original; o encolhimento é uma
transformação determinística no build, coberta por teste com dados sintéticos (como
`tests/unit/test_ga36_boot.py`).

### D4. Cadeia de boot do R36S: a do próprio aparelho

Como no GA36 (decisão do usuário em 2026-11-11), os binários fechados vêm de uma cópia do
cartão original, fora do git:

- `R36OS_R36S_FACTORY` aponta para uma cópia do cartão do R36S (imagem crua ou `.img.zst`;
  basta conter os primeiros 16 MiB). O build extrai as regiões `[64, 406)` e
  `[16384, 32768)`, confere o SHA256 de cada uma contra os valores do cartão medido e
  guarda o resultado no cache (`~/.cache/r36os/vendor/`), como o `vendor.py` faz.
- **Medido no backup** (`sd_r36s_20261102.img.zst`, 2026-11-11): os únicos dados não
  nulos do primeiro 16 MiB são o MBR, o `idbloader` (64 a 405), restos de uma FAT antiga
  (`MSDOS5.0`, setores 2048 a 4566, fora da cadeia) e o `uboot.img`/`trust.img` (16384 a
  29578). Na área do GA36, debaixo das duas regiões só há dados nos setores 64 a 277. Com
  a cadeia real, o primeiro 1 MiB montado pelo build é igual ao provado no aparelho (soma
  do boot0 `0x67971580`).
- Uma cópia com SHA256 diferente (outro cartão de fábrica, outra revisão do U-Boot) é
  recusada com uma mensagem que explica o que foi medido. Aceitar outras cadeias fica para
  quando houver outro aparelho para testar.
- *Alternativa descartada (por ora):* U-Boot mainline (`odroid-go2_defconfig`, TPL/SPL e
  o blob de DDR do `rkbin`). É o caminho aberto, mas foi exatamente o que não deu sinal de
  vida no GA36 (P-19); começar pela cadeia que já inicia este aparelho tira esse risco do
  caminho do cartão único. Vira pendência nova.

### D5. BOOT da imagem console e o `boot.ini`

```
BOOT/
  VERSION
  boot.ini                     lido pelo U-Boot do R36S (cabecalho odroidgoa-uboot-config)
  rg351mp-kernel.dtb           exigidos pelo U-Boot do R36S antes do boot.ini (fabrica)
  rg351p-kernel.dtb
  ga36/SYSTEM                  squashfs armv7
  ga36/dtbs/*.dtb              referencia (o DTB vai anexado no android-boot)
  ga36/android-boot/*.img      paineis 1 e 2 (troca de painel pelo PC)
  r36s/SYSTEM                  squashfs aarch64
  r36s/Image                   kernel arm64 com o initramfs embutido
  r36s/rk3326-r36s-v5.dtb
```

- O `boot.ini` só carrega `r36s/Image` e o DTB e chama `booti ${loadaddr} - ${dtb_loadaddr}`
  (sem `uInitrd`: o initramfs vai embutido no kernel, como no GA36). A linha de comando
  fica no kernel (`CMDLINE_FORCE`, `root=PARTUUID=4c554d32-01`, `console=ttyS2,1500000`,
  `console=tty1`), então a do `boot.ini` não conta.
- **Medido no backup (2026-11-11):** a `BOOT` de fábrica tem, sim, o
  `rk3326-r35s-linux.dtb` e o `uInitrd` (no FAT eles aparecem também pelos nomes curtos
  `RK3326~1.DTB` e `UINITRD`, o que explica a "curiosidade" abaixo), além do `Image`, do
  `boot.ini`, do `logo.bmp` e de dois DTBs do RG351 (que o U-Boot exige; ver abaixo). O `boot.ini` começa
  com `odroidgoa-uboot-config`, define `loadaddr` 0x02000000, `initrd_loadaddr` 0x01100000 e
  `dtb_loadaddr` 0x01f00000, carrega os três arquivos de `mmc 1:1` e chama `booti`. O DTB
  de fábrica é a fonte dos valores do DTS (D7) que o Apêndice A não tinha: tensões do RK817,
  interrupção do PMIC em `gpio0 7`, *io-domains*, `vcc_lcd` a 1,8 V e os botões de volume
  (`gpio3 22` e `gpio3 21`). A tarefa 1.1 continua valendo para confirmar que o U-Boot lê
  um `boot.ini` alterado.
- **Medido no aparelho (tarefa 1.1, 2026-11-12):** o U-Boot de fábrica (Hardkernel
  odroidgoa 2017.09) mede a revisão da placa pelo ADC e define `dtb_name`
  (`rg351mp-kernel.dtb`, `rg351p-kernel.dtb` ou `rg351v-kernel.dtb`); o `bootcmd` é
  `mmc dev 1; cfgload; run setbootargs; load mmc 1:1 0x02000000 Image; load mmc 1:1
  ${fdt_addr_r} ${dtb_name}; booti`. Antes disso ele carrega `${dtb_name}` da raiz da
  `BOOT`: **sem o arquivo, grava `dtb load fail` em `BOOT/error.log` e para** (o primeiro
  cartão `console` não iniciou no R36S por isso). Com o arquivo presente, o `cfgload` lê o
  nosso `boot.ini`, que carrega o nosso kernel e o nosso DTB (o log mostra
  `Machine model: R36S V5`), e o `bootcmd` padrão nunca chega a rodar. Por isso a `BOOT` da
  `console` leva na raiz os dois DTBs do RG351 do cartão de fábrica (`rg351mp-kernel.dtb`
  e `rg351p-kernel.dtb`, idênticos, 61797 bytes); eles são binário de fábrica: o build os
  extrai de `R36OS_R36S_FACTORY` e confere o SHA256, como a cadeia de boot (tarefa 4.5).
  O caminho B (dar ao kernel os nomes que o U-Boot procura) não é necessário.
- O FAT da `BOOT` aceita nomes longos; o U-Boot da Hardkernel lê FAT32 com VFAT.

### D6. Initramfs escolhe o `SYSTEM` do próprio console

O initramfs é construído por camada e embutido no kernel de cada console. O build grava
nele o nome do console (`/etc/board` do initramfs), e o `init` monta
`/boot/<console>/SYSTEM` em vez de `/boot/SYSTEM`. Na VM o caminho continua
`/boot/SYSTEM`. Se o arquivo faltar, o `init` cai na tela de recuperação com o nome do
console e do arquivo. A busca do disco pela assinatura (`PARTUUID=4c554d32-01`) é a mesma
nos dois consoles.

### D7. Kernel do R36S

Linux da mesma série LTS do GA36 (6.18.y), `ARCH=arm64`, cross-compile com
`aarch64-linux-gnu-`, a partir do `defconfig` mais o fragmento `board/r36s/kernel.config`:
DSI e VOP da Rockchip, `panel-sitronix-st7703`, `panfrost`, RK817 (PMIC, codec, carregador
e regulador), SARADC, `io-channel-mux`, `adc-joystick`, `gpio-keys`, `pwm-backlight`,
`simple-battery`, LEDs; embutidos: MMC do RK3326, `vfat`, `exfat`, `squashfs`, `loop`,
`overlay`, DRM do painel e `fbcon`; `INITRAMFS_SOURCE` e `CMDLINE_FORCE` como no GA36.

- O painel entra como uma variante nova no `panel-sitronix-st7703`, num patch numerado em
  `kernel/patches/` (com o binding), a partir da sequência do Apêndice C. Se o driver não
  aceitar a variante, a alternativa é o `panel-mipi-dsi` genérico com a sequência em
  firmware (Risks da change anterior).
- O DTS `board/r36s/dts/rk3326-r36s-v5.dts` segue a estrutura do `rk3326-odroid-go2.dts`
  com os valores do Apêndice A; OPPs e zonas térmicas do `rk3326.dtsi` sem alteração.
- A `trust.img` de fábrica traz o BL31; o kernel mainline usa PSCI dele para ligar os
  núcleos e desligar. Se o BL31 antigo não servir ao kernel novo, aparece logo no primeiro
  boot (núcleos que não sobem ou desligamento que não corta a energia).

### D8. Controle, áudio e configuração do R36S

- `r36os-padmerge` (C, `uinput`) junta `gpio-keys` e `adc-joystick` num "R36S Gamepad",
  como previsto na change anterior (D9 de lá), com teste na VM usando dispositivos falsos.
- Autoconfiguração do RetroArch para o "R36S Gamepad" (ordem F1-F5 a confirmar no
  aparelho).
- `/usr/libexec/r36os/mixer` ganha os padrões do RK817 (caminho do DAC até o fone e o
  alto-falante).
- `retroarch-r36s.cfg` com as chaves fixas do R36S. A regra do `frontend-session` (toda
  chave fixa num console tem valor fixo no outro) vira teste: hoje o GA36 fixa
  `input_enable_hotkey` e `video_refresh_rate`, então o R36S também fixa as duas. A taxa
  do painel do R36S pelo timing do Apêndice A é 27 MHz / (890 × 514) ≈ 59,02 Hz, e o
  valor final é medido no aparelho, como foi no GA36 (tarefa 9.12 da change anterior).

### D9. Logs na ROMS compartilhada

A numeração de boots já vem da `ROMS`, então os dois consoles seguem uma única
sequência. O retrato de hardware já registra o console (`hwinfo`, campo `board`); o log de
boot e o `events.log` passam a registrar o console no início de cada boot. O
`docs/LOGS.md` explica a mistura.

### D10. Pacotes aarch64

Os pacotes locais (`aports/`) são compilados para aarch64 sob `qemu-user`, com as mesmas
flags padrão do Alpine. O `libretro-pcsx-rearmed` usa o dynarec aarch64 (a exceção
`-marm -mfpu=neon` é só do armv7). O `libretro-ppsspp` continua desativado (P-18). As
playlists são geradas a cada boot com os caminhos dos cores do sistema que está rodando,
então trocar de console não deixa lista apontando para core de outra arquitetura.

## Risks / Trade-offs

- **[O U-Boot do R36S não lê o nosso `boot.ini`]** → Tarefa 1.1 antes de qualquer outra
  coisa do R36S; o caminho B (nomes que o U-Boot procura) muda só o conteúdo da `BOOT`.
- **[U-Boot ou BL31 de fábrica não iniciam o kernel mainline]** → Tarefa 1.2: subir o
  kernel do build com um DTB mínimo antes do painel e do controle. Se falhar, a saída é o
  U-Boot mainline, que hoje é pendência; a change pararia aqui e voltaria a ser discutida.
- **[Um U-Boot grava no cartão (env) e corrompe a área do outro]** → Teste no aparelho:
  SHA256 dos primeiros 128 MiB antes e depois de iniciar em cada console (tarefa 9.3). O
  env do U-Boot do R36S, se existir, cai perto de 4 MiB, onde a área do GA36 tem restos
  não usados.
- **[Bring-up sem serial]** → Sem adaptador, um kernel que não sobe fica mudo. Mitigação:
  o `fbcon` no painel desde cedo, o LED (`gpio0 5`/`gpio0 0`) aceso pelo initramfs como
  marcador de que o kernel chegou ao `init`, e os logs da `ROMS` assim que o userland
  sobe. Se houver um adaptador USB-serial de 3,3 V, ele encurta muito o diagnóstico.
- **[Painel ou mux dos analógicos]** → Alternativas registradas no D7 e na change anterior
  (`panel-mipi-dsi`; mux em espaço de usuário no `padmerge`).
- **[A cadeia de fábrica do R36S só vale para este cartão]** → Recusada com SHA256
  diferente; outros cartões ficam para quando houver aparelho para testar.
- **[Build mais longo]** → Duas camadas ARM por build. O cache de pacotes e do kernel
  continua por camada; só o que mudou é refeito.
- **[Save states entre armv7 e aarch64]** → Podem não ser compatíveis; os saves `.srm`
  costumam ser. Documentado no `LEIA-ME.txt` e no `README.md`.
- **[Cartões do GA36 gravados antes]** → A `BOOT` de 2 GiB não cabe no layout antigo: o
  `--update` recusa e pede gravação completa, que apaga a `ROMS` (copiar jogos e saves
  antes). Cartões de 2 GB deixam de servir. Coberto por teste do `flash`.

## Migration Plan

1. `vm` → `test-vm` → `console`, nessa ordem (a imagem `console` só é liberada se a VM
   passar).
2. Cartão do GA36 que já existe: copiar jogos e saves, `r36os flash console <dispositivo>`
   (gravação completa) e devolver os arquivos à `ROMS`. Cartão novo: o mesmo comando.
   Cartões `console` seguintes: `--update` (a `ROMS` fica).
3. Voltar atrás: com o `r36os` de uma revisão anterior a esta change,
   `r36os flash ga36 <dispositivo> --build <timestamp>` (gravação completa) grava uma build
   antiga do GA36; ele deixa de iniciar o R36S.

## Open Questions

- Ordem dos botões F1-F5 do R36S e o valor final da taxa do painel: medidos no aparelho,
  afetam só a autoconfiguração e o `retroarch-r36s.cfg`.
- Se os restos de exFAT/FAT nos setores 2048 a 9216 da área do GA36 são usados: hoje
  ficam como estão; zerá-los seria só uma limpeza.
