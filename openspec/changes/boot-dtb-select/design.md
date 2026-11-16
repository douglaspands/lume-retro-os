# Design

## Context

Ver `proposal.md` (Why). O estado que molda o desenho:

- **GA36**: boot0 + U-Boot 2017.09 da Allwinner (área de fábrica, `src/r36os/vendor.py`). O
  `bootcmd` do env é `run setargs_mmc boot_normal`, e `boot_normal` lê a partição `boot`
  (setor 172032) com `sunxi_flash read` e chama `boota`. O kernel é um `zImage` com o DTB
  anexado (`ARM_APPENDED_DTB`), o initramfs embutido e a linha de comando fixa
  (`CMDLINE_FORCE`). O env tem `recovery_key_value_min/max=0x10–0x13` e
  `fastboot_key_value_min/max=0x2–0x8` (faixas do LRADC que desviam o boot). O binário traz
  `fatload`, `fatls`, `mmc part`, `bootm` (sem `bootz`) e `sunxi_bmp_display addr`. O logo
  é o `bootlogo.bmp` da FAT "bootloader" interna (setor 73728): BMP 640x480, 24 bits.
- **R36S**: `idbloader` + U-Boot 2017.09 da linha Hardkernel (`odroidgoa`) + `trust.img`. O
  U-Boot escolhe um DTB do RG351 pelo ADC (`hwrev`/`dtb_name`), carrega o `logo.bmp` da raiz
  da `BOOT` e roda o `boot.ini`, que carrega `r36s/Image` e o DTB do R36S. O binário traz
  `fatload`, `fatwrite`, `setexpr` e `gpio input`. O kernel também tem `CMDLINE_FORCE`.
- **initramfs** (`initramfs/init`): é o primeiro código nosso nos dois consoles; sabe o
  console por `/etc/board`, monta a `BOOT` (ro) e cria ou confere a `ROMS`.
- As capacidades dos U-Boots de fábrica vêm das strings dos binários (lidas em 2026-11-13).
  Nada disso foi provado no aparelho ainda: o grupo 1 das tarefas faz as provas.

## Goals / Non-Goals

**Goals:**
- Uma única implementação da escolha do DTB, igual nos dois consoles, testável no PC.
- Nenhum binário de fábrica alterado: a customização dos bootloaders fica no `boot.ini` e no
  env do GA36.
- O caminho padrão (aparelho original, sem escolha) custa zero: sem kexec e sem espera.

- Os DTBs do dArkOS/dArkOSRE para clones do R36S funcionam copiados para a pasta do SoC,
  convertidos no boot (D12 a D14).

**Non-Goals:**
- DTBs de outros projetos ou do kernel 4.4 de outros SoCs; subir o kernel 4.4 deles.
- Escolher o DTB dentro do bootloader. O `boot.ini` poderia ler o `force` e evitar o kexec
  no R36S, mas isso é uma otimização para depois das provas e fica fora desta change.
- Sondas que escrevem no hardware ou varrem barramentos inteiros.

## Decisions

### D1. A escolha mora no initramfs, não no bootloader

O initramfs escolhe o DTB e, se precisar, reinicia o kernel com ele por kexec.

```
 bootloader de fabrica (intocado) --> kernel + DTB padrao do SoC
        |
        v
 initramfs: monta BOOT (ro) e ROMS
        |
        +-- /proc/device-tree/chosen/lume,dtb-selected existe? --> segue (veio do kexec)
        |
        v
 lume-bootsel: force > lista (tecla) > fallback > manual gravada > regras > padrao
        |
        +-- escolhido == DTB em uso --> segue o boot
        +-- outro --> prepara o DTB, arma o watchdog se for novo, desmonta,
                      kexec (mesmo kernel, DTB escolhido)
                         |
                         v
                      2o inicio: DTB novo? pergunta na tela (D10)
                         +-- A --> good, para o watchdog, segue
                         +-- 15 s sem resposta --> bad, kexec de volta (reverted)
```

**Alternativas:** (a) no `boot.ini` do R36S: só serve a um console e as regras exigiriam
ler propriedades de DTB em script de U-Boot; (b) no env do GA36: não roda sondas e depende de
`if`/`test`, que ninguém provou; (c) U-Boot próprio (P-43): é o certo a longo prazo, mas o
P-19 está bloqueado. O initramfs é o único ponto nosso comum aos dois e tem o kernel
inteiro para ler o hardware (IIO, GPIO, I2C), o que no U-Boot exigiria um driver por chip.

### D2. Troca por `kexec_load`, com o DTB preparado pelo utilitário

O `kexec_file_load` não serve: no arm64 ele monta o DTB a partir do atual, sem aceitar outro,
e no arm32 ele não existe. Fica o `kexec` do `kexec-tools` com `--dtb`. Antes do kexec, o
utilitário grava uma cópia do DTB escolhido com: (1) o nó `/memory` copiado de
`/proc/device-tree` (o bootloader corrige a memória no DTB que carrega, e a cópia da pasta
não tem esse ajuste: no GA36 a memória real chega por ATAG); (2) `/chosen/lume,dtb-selected`
com o nome e o motivo. O segundo início vê essa propriedade e não escolhe de novo, o que
impede laço mesmo que as sondas deem outro resultado com o DTB novo ou que a tecla
continue segura. A linha de comando não serve de marcador porque os dois kernels têm
`CMDLINE_FORCE`.

Um boot faz **no máximo uma troca e uma volta**: a troca leva ao DTB escolhido; a volta
(D10) só acontece quando o DTB novo não foi confirmado na tela, e leva ao último
confirmado (ou ao padrão) com o motivo `reverted`. O terceiro início vê o `reverted` no
`/chosen` e segue sem perguntar nem trocar.

O kernel recarregado é o mesmo do boot: `r36s/Image` no R36S e um `ga36/zImage` novo na
`BOOT` (o mesmo kernel, sem DTB anexado) no GA36. Os dois fragmentos de kernel ganham
`CONFIG_KEXEC`.

### D3. A regra fica dentro do DTB, num nó do Lume

```
/ {
    lume-select {
        lume,id = "ga36-panel2";
        lume,priority = <10>;
        /* lume,default;                         so no DTB padrao */
        lume,adc = <0x01c22800 0 16 19>;         /* controlador, canal, min, max */
        lume,gpio = <0x01c20800 37 1>;           /* controlador, linha, nivel */
        lume,i2c-present = <0x01c2ac00 0x34>;    /* controlador, endereco */
    };
};
```

As propriedades levam o prefixo `lume,` (implementação, 2026-11-13): `name` é reservado no
DTB (o `dtc` recusa um `name` diferente do nome do nó, e o kernel cria
`/proc/device-tree/<nó>/name`) e `id` tem tipo próprio no `dt-core.yaml`. O prefixo `lume` e
o schema do nó entram pelo patch de kernel `0026-dt-bindings-add-the-Lume-device-tree-
selection-node.patch`, de modo que o `dt-validate` do build confere o nó. O build também
recusa uma pasta `dtbs/<soc>/` sem exatamente um `lume,default` ou com `lume,id` repetido.

O controlador é identificado pelo **endereço MMIO**, não por phandle: as regras são
avaliadas pelo kernel que subiu com o DTB padrão, e o phandle de um candidato não aponta
para nada nele. O endereço casa com o nome do dispositivo no sysfs (`1c22800.lradc`,
`ff288000.saradc`). Todas as regras de um candidato precisam bater; um candidato sem regra
só entra pela lista ou pelo `force`. O DTB em uso é reconhecido por
`/proc/device-tree/lume-select/lume,id`; um DTB sem o nó conta como o padrão.

**Alternativa:** um arquivo de regras à parte (`dtbs/rules.toml`), descartado porque teria
de ser mantido em sincronia com a pasta. Com a regra dentro do DTB, copiar o arquivo basta.

### D4. Sondas só de leitura

- **ADC**: `in_voltageN_raw` do dispositivo IIO do controlador.
- **GPIO**: só uma linha que o kernel já tem como entrada, lida pelo chardev; uma linha de
  saída ou desconhecida faz a regra falhar, sem mudar a direção do pino.
- **I2C**: leitura de 1 byte (como o `i2cdetect -r`) só no endereço da regra, nunca uma
  varredura, e só se o endereço não estiver preso a um driver.

### D5. Utilitário `lume-bootsel` em C, no initramfs

Ele faz a escolha, o menu e a preparação do DTB. É estático (musl), ligado à `libfdt`, e
entra como pacote local em `aports/`, copiado para o initramfs pelo build junto do `kexec`
do `kexec-tools`. Ele aceita `--root <dir>` (um sysfs, um `/proc/device-tree`, uma `BOOT` e
uma `ROMS` falsos) e `--dry-run` (imprime a decisão sem kexec), o que permite testar a
precedência, as regras e o fallback com pytest no PC. Sem `/proc/device-tree` (a VM x86)
ele registra `no device tree` e não faz nada.

**Alternativa:** shell no `init`. Descartada porque ler evdev (`EVIOCGKEY`), desenhar o
menu e editar o DTB não cabem no busybox.

**Implementação (2026-11-13):** o Alpine não tem `libfdt.a` e o `kexec` dele é dinâmico (o
initramfs não tem libc), então o aport `aports/lume-bootsel` compila a `libfdt` do tarball
do `dtc` junto do utilitário e o `kexec-tools` estático do fonte; os dois vão para
`/usr/lib/r36os/initramfs/bin/`, que o build do initramfs já copia. O utilitário sai com 10
quando carregou o kernel (`kexec -l`), e o `init` desmonta tudo e roda `kexec -e`; se o
`kexec -e` voltar, o boot segue com o DTB em uso. As linhas do log do primeiro início vão
para `/chosen/lume,dtb-log` do DTB preparado, e o segundo início as repete
(`before kexec: …`), porque o `dmesg` do primeiro kernel se perde no kexec. Na raiz falsa
dos testes (`--root`), um nó de dispositivo que é arquivo comum descreve o dispositivo
(eventos de entrada, linhas de GPIO, endereços de I2C). A `ROMS` passa a ser montada em
`/roms` logo depois da `BOOT` e é movida para `/newroot/storage` depois.

### D6. Estado na ROMS, por aparelho

`ROMS/system/etc/dtb-<soc>-<serial>.conf`, um arquivo **por aparelho**, com `manual=`,
`good=`, `pending=` e `bad=`. O `<serial>` é o número de série do SoC em
`/sys/devices/soc0/serial_number` (SID no A33, OTP no RK3326; prova 1.7). Assim o cartão
levado a outro aparelho do mesmo SoC (outro GA36, com outro painel) não leva a escolha do
primeiro: o aparelho novo começa pelas regras e pelo padrão. Sem número de série, o
arquivo é `dtb-<soc>.conf` (por SoC, como antes) e o log avisa que a escolha vale para todo
aparelho daquele SoC.

- Antes de subir com um DTB que não é o padrão e ainda não foi confirmado neste aparelho
  (inclusive o forçado), grava `pending=<nome>`.
- O DTB `pending` é confirmado na tela (D10): A grava `good=<nome>` e apaga o `pending`.
  Quando a pergunta não pode aparecer (sem dispositivo com a tecla de confirmar), o `logd`
  confirma quando o frontend sobe, como antes.
- Se o boot começa com `pending` gravado, aquele DTB travou antes da confirmação (o
  watchdog do D11 reiniciou o aparelho, ou o usuário desligou): ele vai para `bad=`, e o
  boot usa o `good` (ou o padrão). Se o descartado era a escolha `manual`, ela é apagada. O
  automático pula os nomes em `bad`.
- Um `force` que nomeia um DTB em `bad` neste aparelho é ignorado, com o motivo no log, até
  o arquivo ser apagado ou o DTB ser escolhido na lista.
- A escolha manual na lista limpa o `bad` daquele nome.
- Sem `ROMS` (cartão novo antes de criar, partição com erro), a escolha funciona sem
  persistência e sem confirmação.

O `force` fica só na `BOOT` e só é lido: a `BOOT` continua montada `ro`. Ele vale para o
cartão (qualquer aparelho do SoC); a confirmação e o `bad` são de cada aparelho.

**Implementação (2026-11-13):** do número de série ficam só letras e dígitos (o valor vira
nome de arquivo), e um valor vazio ou só de zeros (SoC sem fusível gravado) conta como
ausente. O `r36os-logd` acha o mesmo arquivo pela mesma regra (`dtb_conf_name` em `lib.sh`)
e passa a confirmar só um `pending` igual ao DTB em uso; antes ele gravava `good=` do DTB
em uso a cada boot, e agora o `good=` só nasce de uma confirmação.

**GA36 (boot 19, 2026-11-13, prova 1.7):** o kernel do A33 não cria `/sys/devices/soc0`
(nenhum driver registra o SoC no `soc` bus), então o estado ficou em `dtb-a33.conf`, com o
aviso no log. O SID existe pelo nvmem (`CONFIG_NVMEM_SUNXI_SID=y`); usá-lo como número de
série é uma decisão em aberto.

**Número de série do bootloader (2026-11-16, decisão do usuário):** o RK3326 também não tem
`soc0`, mas o U-Boot de fábrica do R36S grava `/serial-number` na raiz do DTB (do OTP;
`c3d9b8674f4b94f6`, igual nos boots 108 e 110). A fonte passa a ser, nesta ordem:
`/sys/devices/soc0/serial_number`, depois `/proc/device-tree/serial-number`, com a mesma
limpeza (só letras e dígitos, zeros contam como ausente). Como o kexec troca o DTB inteiro,
o `prepare()` copia o `/serial-number` do DTB em uso para o preparado, ao lado do `/memory`;
sem isso o segundo início acharia outro arquivo de estado. O `r36os-logd` (`dtb_serial` em
`lib.sh`) segue a mesma ordem. O log diz a origem (`SoC` ou `bootloader`). No GA36, depende
do que o U-Boot 2017 da Allwinner grava (prova 1.7); o SID pelo nvmem continua em aberto.
O estado antigo `dtb-rk3326.conf` não é migrado: o aparelho recomeça pelas regras e pelo
aprendido (que é por SoC e não muda).

### D7. Tecla e menu

A tecla de seleção e as de navegação são por console, num arquivo do board
(`board/<b>/bootsel-keys`) copiado para o initramfs. A proposta inicial é Vol- para abrir a
lista, as teclas de volume para navegar e uma tecla de ação para confirmar; a escolha final
sai das provas 1.2 e 1.3 (o U-Boot do GA36 já desvia o boot por faixas do LRADC, e uma
tecla de volume pode cair nelas). O estado da tecla é lido uma vez, por `EVIOCGKEY`, assim
que o dispositivo de entrada aparece (espera de no máximo 1 s), então o usuário só precisa
segurá-la ao ligar. O menu é texto no `tty1` (fbcon), com o automático marcado `(auto)`, o
último bom `(ok)` e a escolha forçada `(forced)`. Os drivers das teclas já são embutidos
(`KEYBOARD_GPIO` no R36S, `KEYBOARD_SUN4I_LRADC` no `sunxi_defconfig` do GA36), o que a
tarefa 3.1 confere.

### D8. Layout da BOOT

```
BOOT/
  boot.ini  logo.bmp  rg351mp-kernel.dtb  rg351p-kernel.dtb  VERSION
  dtbs/a33/    sun8i-a33-ga36-mb-v1.2-panel1.dtb (padrao)  ...-panel2.dtb
  dtbs/rk3326/ rk3326-r36s-v5.dtb (padrao)
  dtbs/force   (opcional, so o usuario cria)
  ga36/ SYSTEM  zImage
  r36s/ SYSTEM  Image
```

A `BOOT` tem só o que os consoles leem (pedido do usuário, 2026-11-13). `ga36/dtbs/`,
`r36s/<dtb>` e `ga36/android-boot/` saem; as imagens de boot dos dois painéis do GA36 (o
`dd` no setor 172032, plano B enquanto o kexec não é provado) são arquivadas com o build em
`out/images/console/<build>/ga36-android-boot-panel{1,2}.img`, com o SHA256. O `boot.ini` passa a carregar
`dtbs/rk3326/rk3326-r36s-v5.dtb`. O `force` traz só o nome do nó (`ga36-panel2`), não o
caminho do arquivo. A pasta do SoC vem de `/etc/soc`, gravado no initramfs pelo build.

### D9. Logo do GA36

O build copia o `BOOT/logo.bmp` (o de fábrica do R36S, de `r36s_vendor.BOOT_FILES`) sobre o
`bootlogo.bmp` da FAT interna (mtools no deslocamento do setor 73728; os dois têm o mesmo
tamanho) e reescreve o env: `bootcmd=fatload mmc 0:1 <addr> logo.bmp; sunxi_bmp_display
<addr>; run setargs_mmc boot_normal`, com o CRC32 recalculado. Os comandos são separados
por `;`, então uma falha no `fatload` não impede o boot. O endereço e o número do
dispositivo saem da prova 1.4. A conferência por SHA256 da área de fábrica continua sendo
feita antes dessas edições, como já é feito para o boot0.

**Se a prova 1.4 falhar** (o `fatload` não enxerga a `BOOT` ou o `sunxi_bmp_display` não
desenha), fica só a cópia na FAT interna: o logo continua o mesmo nos dois, e o cenário
"Logo trocado pelo PC" do spec passa a valer só para o R36S (o spec é ajustado nesta
change).

### D10. Confirmação na tela do DTB novo

Chegar ao frontend não prova que o DTB serve: com o painel errado, o kernel e o RetroArch
sobem e a tela fica preta. Quem sabe se a tela acendeu é o usuário. Por isso, no primeiro
boot com um DTB `pending` (diferente do padrão e ainda não confirmado neste aparelho, venha
das regras, da lista ou do `force`), o `lume-bootsel` do **segundo início** (depois do
kexec, já com o painel iniciado pelo DTB novo) mostra no `tty1`:

```
Lume Retro OS - new device tree: ga36-panel2

If you can read this, press A to keep it.
Going back to ga36-panel1 in 15 s...
```

- A (o papel `ok` do `bootsel-keys`) dentro de 15 s: grava `good=<nome>`, apaga o
  `pending`, para o watchdog (D11) e segue o boot.
- Nenhuma resposta: o DTB vai para `bad`, e o utilitário prepara o anterior (o `good`, ou o
  padrão) e faz o kexec de volta, com o motivo `reverted` no `/chosen`. A tela preta se
  resolve sozinha, sem PC e sem desligar.
- Sem dispositivo de entrada com a tecla de confirmar (ou sem `bootsel-keys`), a pergunta
  não aparece e o `pending` fica para o `logd` confirmar no frontend.
- O padrão e os DTBs já confirmados nunca perguntam: no uso normal ninguém vê esta tela.
- Mensagem só em inglês, como o resto do initramfs.

**Implementação (2026-11-13):** o segundo início só pergunta quando o `pending` gravado é
o DTB que veio do kexec; a mensagem é redesenhada a cada segundo com a contagem. Na raiz
falsa dos testes, o fim da descrição do dispositivo de entrada conta como "sem resposta"
na hora, para o teste não esperar 15 s.

**Alternativas:** (a) perguntar no frontend: depende do RetroArch, que um DTB ruim pode
impedir de subir; (b) tecla sorteada a cada pergunta, para não confirmar às cegas:
descartada pela simplicidade, o risco fica nos Riscos; (c) checar no initramfs se os drivers
essenciais ligaram: não pega a tela preta (o driver do painel liga mesmo com a sequência
errada).

### D11. Watchdog armado antes do kexec

Um DTB novo pode travar o kernel antes da pergunta. Antes do kexec para um DTB `pending`, o
`lume-bootsel` abre `/dev/watchdog`, ajusta o tempo (60 s) e o fecha sem o caractere mágico
`V`, de modo que o watchdog continua contando. No segundo início ele o abre de novo, o
alimenta durante a pergunta e o para (`V`) ao confirmar ou antes do kexec de volta (que
arma outro). Se nada abrir o watchdog, o aparelho reinicia, o bootloader inicia o padrão e
o boot seguinte encontra o `pending` e faz o `fallback`.

O kernel não pode alimentar sozinho um watchdog que encontra rodando: os fragmentos ganham
`CONFIG_WATCHDOG_OPEN_TIMEOUT` (o núcleo do watchdog para de alimentá-lo se ninguém o abrir
nesse tempo) e o driver do watchdog de cada SoC embutido. Se o watchdog não atravessar o
kexec num dos consoles (prova 1.6), aquele console fica só com o `fallback` depois de
desligar e ligar.

**Implementação (2026-11-13):** o DTB preparado leva `/chosen/lume,watchdog` quando o
watchdog foi armado, e todo início que vem de um kexec com essa marca para o watchdog
(`V`) quando não há pergunta: o terceiro início depois da volta, um DTB já confirmado, ou a
pergunta que não pôde aparecer (sem tecla de confirmar; aí o `pending` fica para o
`r36os-logd`, e um travamento antes do frontend só se resolve desligando). O watchdog só é
armado depois que o `kexec -l` deu certo, e o `--dry-run` não o toca. Se o `kexec -e`
voltar, o `init` chama `lume-bootsel --kexec-failed`, que para o watchdog e apaga o
`pending` (o DTB escolhido nunca rodou e não deve ir para `bad`).

**GA36 (boot 19):** o `sunxi-wdt` registra `timeout=16 sec`, o máximo dele. O utilitário
pede 60 s e, se o driver recusar, usa o maior tempo aceito e registra o valor real. No A33
o segundo início chega à pergunta cerca de 3 s depois do kexec, então 16 s bastam se o
watchdog atravessar o kexec (prova 1.6).

### D12. DTBs do dArkOS e do dArkOSRE convertidos no boot

> **Revisto pelo D17 (2026-11-16):** a conversão saiu do boot e foi para o PC (Python, na
> importação), com o resultado compilado e validado no build. O que segue vale como
> levantamento dos DTBs e das regras de conversão; o "onde" e o "quando" estão no D17.

**Contexto (2026-11-13):** o dArkOS compila o kernel de `christianhaitian/linux`, branch
`rg351` (4.4 da Rockchip, `rg351p_tweaked_defconfig`), e o dArkOSRE distribui 43 DTBs de
placas (R36S oficiais, clones e "soysauce") em `files/BOOT/dtb/<variante>/<placa>/`, todos
com o nome `rk3326-r36s-linux.dtb`, escolhidos à mão pelo PC (`select_devices.sh`). Cópias
para análise ficam em `.cache/upstream/` (fora do git): `dArkOSRE-R36` (commit `3f372c8`) e
`darkos-linux-rg351` (commit `14c877f`, DTS do RK3326 e os drivers `odroidgo3-joypad.c` e
`panel-simple.c`). Os 43 têm `rockchip,rk3326`, o PMIC `rk817` (codec, carregador,
bateria), o painel `simple-panel-dsi` com `panel-init-sequence` (14 sequências distintas,
640x480 ou 720x720), o controle `odroidgo3-joypad`, `pwm-backlight`, `simple-audio-card` e
`gpio-leds`. Mudam entre placas: sequência, timings, atrasos e pinos do painel; pinos dos
botões, mux e canal do ADC dos analógicos; PWM e níveis da luz de fundo; pino do
amplificador e da detecção do fone; tabela de tensão e capacidade da bateria; LEDs.

O nosso kernel não sobe com esses DTBs (bindings e drivers do 4.4). O `lume-bootsel` os
**converte no boot**:

```
 BOOT/dtbs/rk3326/  <placa>.dtb  ou  <placa>/rk3326-r36s-linux.dtb  (rg351*-uboot.dtb: ignorado)
        |
        v
 reconhece o DTB 4.4: compatible do SoC + nós conhecidos (simple-panel-dsi, odroidgo3-joypad, rk817)
        |
        +-- nó obrigatório ausente ou propriedade sem mapeamento --> recusado, motivo no log
        v
 base = o DTB padrão do SoC (rk3326-r36s-v5, nosso, mainline), trocando por placa:
   painel        -> nó rocknix,generic-dsi (D13): panel_description com sequências, modos,
                    atrasos; reset/enable
   luz de fundo  -> pwms, brightness-levels, default
   controle      -> gpio-keys (sw*) + adc-joystick sobre io-channel-mux (amux-*, io-channels,
                    amux-channel-mapping)
   som           -> pino do amplificador (spk-ctl-gpios) e detecção do fone (hp-det-gpio)
   bateria       -> simple-battery (ocv_table, design_capacity, design_qmax)
   LEDs          -> gpio-leds
        |
        v
 candidato com lume,id = nome da subpasta (ou o model), sem regra salvo assinatura (D14)
```

Os pinos do 4.4 vêm como `<phandle linha flags>`; o phandle aponta para um banco
(`gpio0`..`gpio3`) do DTB deles, identificado pelo endereço (`reg`), e vira o phandle do
mesmo banco no DTB base. Um pino de um banco que a base não tem recusa o DTB. A conversão é
determinística e só de leitura no DTB de origem; o resultado vai para o mesmo caminho de
preparo do D2 (memória, `/chosen`, kexec), e um DTB convertido é sempre "novo": passa pela
confirmação na tela (D10) e pela volta automática.

**Revisão (2026-11-13, depois de avaliar <https://handhelds.wiki/R36S_Clones> com o
usuário):**

- **Entradas:** além do dArkOSRE, os DTBs do arkos4clone (MIT, cerca de 280 arquivos para
  dArkOS) e o **DTB de fábrica do próprio aparelho** (o do cartão original, ou o do
  repositório EE-Clones-DTB, com os de fábrica de cerca de 25 aparelhos: K36, K36S, R36
  Max/Pro/Ultra, RX6H/RX6S, T16 Max, XF35H/XF40H, U8, MyMini, clones "EE" e outros). Os
  de fábrica usam o mesmo kernel da Rockchip (4.4; alguns V20 trazem DTBs do 5.10, com os
  mesmos nós) e entram pela mesma conversão. Cópias em `.cache/upstream/arkos4clone` e
  `.cache/upstream/EE-Clones-DTB`.
- **Lógica da conversão:** portada do `rocknix_dtbo.py` do ROCKNIX (repositório
  `stolen/overlay_server`, MIT, com crédito no código e no README; cópia em
  `.cache/upstream/overlay_server`), que já trata os casos reais desses clones: joypad de
  um ADC com mux ou de vários ADCs (estilo MyMini), `adc-keys` desligado, teclas de volume
  por GPIO, detecção do fone invertida, amplificador por `spk-con-gpio` ou
  `spk-ctl-gpios`. A nossa porta em C acrescenta bateria e LEDs, que ele não cobre, e gera
  o DTB completo em vez de um overlay (o kexec carrega um DTB pronto).
- **Base:** o DTB padrão do SoC serve de base para as placas parecidas com o R36S; para os
  clones "EE", cuja placa difere em mais que painel e pinos, a base é avaliada a partir do
  `rk3326-gameconsole-eeclone.dts` do ROCKNIX (GPL-2.0; cópia em `.cache/upstream/rocknix`)
  e entra como um segundo DTB base no build, escolhido pelo conversor conforme os nós do DTB
  de origem.
- **Volume seguro:** o arkos4clone queimou alto-falantes do R36S-V20 com tensão alta demais
  (aviso na página do handhelds.wiki). O conversor não copia o ganho do amplificador do DTB
  de origem: usa o valor seguro da base, e um DTB que peça outro registra isso no log.

**Avaliação da segunda base (tarefa 7.2, 2026-11-16).** A coleção EE-Clones-DTB tem 55
arquivos e nenhum convertido: 44 recusados por `play_joystick`, 5 por `micro,gamepad`, 1
sem painel DSI (G30) e 5 repetidos. As mesmas famílias aparecem convertidas pelas versões do
arkos4clone (K36, K36S, HG36, MyMini, R36 Max/Pro/Ultra, R36T, RX6H, T16 Max, U8,
XF35H/XF40H, XGB36) e as placas G80C/G80CA/G80D pelo dArkOSRE; ficam sem versão convertida
ANS11, ANS13, D28S, G30, L35, Project X Pro, R39 Max e RX6S. **O que não basta é a base, não
o controle:** um levantamento dos DTBs de origem (medição com `r36os.fdt` sobre o
`SOURCES.tsv`) comparou os reguladores do RK817 e os domínios de I/O de cada um com o DTB de
fábrica do R36S V5, que é o que todo convertido herda do nativo (o conversor não lê nem um
nem outro). Só o `factory-r35s` é igual; dos 169 convertidos, 153 diferem nos domínios de
I/O e 15 só nos reguladores. Duas famílias:

- **Layout "EE"** (os DTBs de fábrica EE "Stock", o `darkosre-r36s`, as G80, os
  `clone-type1/2` do arkos4clone e a maior parte das outras placas, cerca de 100 dos
  convertidos): `vccio3` e `vccio6` em 1,8 V, `vccio4`/`vccio5` no DCDC4 a 3,0 V, `vccio1` no
  LDO7 (1,8–3,3 V), LDO8 a 3,3 V (segundo slot ou câmera), LDO9 a 1,5 V. É o layout do
  `rk3326-gameconsole-eeclone.dts` do ROCKNIX. Na nossa base, `vccio3`–`vccio6` ficam no
  DCDC4 a 3,3 V e `vccio1` junto do `vccio_sd` (LDO5, que desce a 1,8 V com cartão UHS). Numa
  placa EE isso põe o seletor de tensão do SoC (GRF) em 3,3 V em bancos alimentados a 1,8 V,
  e, com cartão UHS, em 1,8 V num banco alimentado a 3,3 V pelo LDO7; e o DCDC4 fica 10%
  acima do projeto da placa. O kernel só recusa acima de 3,6 V; não foi medido no aparelho
  se isso só desliga pinos ou também estressa os pads.
- **Layout "RG351/origin"** (o `origin` e o `a10mini` do arkos4clone, os R36S V12/V20/R35S
  do dArkOSRE e parecidos, cerca de 45): `pmuio` a 3,3 V (nossa base: 3,0 V), LDO8 a 2,8 V no
  painel (nossa base: 1,8 V, painel sub-alimentado), LDO5 fixo em 1,8 V. Atenção: o
  `darkosre-r36s-r35s-v11` é a mesma placa do nosso `factory-r35s` e declara valores
  diferentes do DTB de fábrica dela; os DTBs de SO (dArkOS, arkos4clone) nem sempre retratam
  o hardware, e os de fábrica (EE "Stock", `out/r36s-factory`) valem mais.

**Conclusão:** a diferença das duas famílias é de alimentação (tensões dos reguladores e
qual regulador alimenta cada banco), não de base; o P-77 entrou nesta change como o D18,
que copia a alimentação da origem sobre a base de hoje. O controle `play_joystick` é um
passo à parte (P-75).

**Fora do alcance do DTB** (registrado em `docs/PENDENCIAS.md`): aparelhos com eMMC, que o
RK3326 tenta iniciar antes do cartão (o ROCKNIX precisou de um U-Boot próprio para o K36
com eMMC), e outra memória: P-43. As placas A33/A23 da família do GA36 (GA36-MB V1.0 e
V1.1, a V1.2-20260416, que pode ser A23, Gaminja Batocera, RD36) não têm DTB de fábrica
(o firmware delas é sunxi com FEX) e precisam de porte por placa: P-16. Os aparelhos com
outro SoC (RK3128, MediaTek MT6572, HCSEMI E3100 dos GB350, R36SX e R36HD, PS101/PS202, o
Famiclone) ficam documentados como incompatíveis.

**Alternativas:** (a) converter no PC (`r36os dtb import`): mais simples, mas o usuário
pediu "copiar e funcionar" sem o projeto no PC; (b) subir o kernel 4.4 deles por kexec: o
nosso userland, os módulos e o RetroArch não rodam nele; (c) portar cada placa à mão:
não escala para dezenas de placas; (d) usar o `rocknix_dtbo.py` como está: é Python, e o
initramfs não tem interpretador; a lógica é portada.

### D13. Painel DSI genérico do ROCKNIX (`rocknix,generic-dsi`)

O painel dos DTBs convertidos usa o driver `panel-generic-dsi` do ROCKNIX (GPL-2.0, autor
Danil Zagoskin; cópia em `.cache/upstream/rocknix/projects/ROCKNIX/packages/linux-drivers/
generic-dsi/`), já usado com kernel mainline nesses clones, trazido como patch de kernel
numerado com o crédito no cabeçalho, mais um binding YAML nosso para o `dt-validate` (o
ROCKNIX não tem). O driver lê do nó a propriedade `panel_description`: linhas de texto com
`delays`, `size`, `format`, `lanes`, `flags`, os modos (`clock`, `horizontal`, `vertical`,
`default`) e a sequência (`dcs`, `data`, `seq`, `wait`, `read`), além de `reset-gpios`,
`enable-gpios` e das alimentações `vdd` e `iovcc`. O conversor traduz o
`panel-init-sequence`/`panel-exit-sequence` (formato binário da Rockchip: tipo DCS, atraso,
tamanho, dados), os `display-timings` e os atrasos para esse texto, como o
`rocknix_dtbo.py` faz. O compatible fica o do ROCKNIX (`rocknix,generic-dsi`) para manter
a compatibilidade com os DTBs e overlays que eles geram. O R36S V5 continua com o driver
do ST7703 (provado no aparelho).

**Alternativa:** um driver nosso (`lume,dsi-panel`), que leria o formato binário da
Rockchip direto do nó: descartado porque o do ROCKNIX já está provado nesses clones.

**Feito (2026-11-16): patch 0033** (`panel-generic-dsi.c`, `CONFIG_DRM_PANEL_GENERIC_DSI=y`
no R36S, binding `rocknix,generic-dsi.yaml` e o prefixo `rocknix`). Porte limpo para o 6.18
(`devm_drm_panel_alloc`, modos e comandos em vetores, linha inválida da descrição falha o
probe, erro na sequência para o `prepare`, sem arquivo de firmware) com o formato e a
semântica do ROCKNIX, inclusive o `wait` em hexadecimal. Lê o ID do painel (DAh–DCh, 1
byte cada) depois do reset e o mostra em `panel_id`, como os patches 0031 e 0032: o D15
vale também para os convertidos.

### D14. Detecção pela assinatura medida

> **Revisto pelo D15 e pelo D17 (2026-11-16):** a tabela de assinaturas à parte não foi
> feita. Um DTB convertido escolhido na lista e confirmado na tela é aprendido para o ID do
> painel (D15) e passa a ser escolhido sozinho, carregado de `vendor/` pelo nome; uma
> regra `lume,panel-id` medida pode ir para o DTS da placa pelo conversor.

O nome da placa nos DTBs do (d)ArkOS é só um rótulo (`model`), sem nada que o hardware
confirme. A escolha automática de um DTB convertido usa uma **tabela de assinaturas** do
projeto (`board/r36s/vendor-signatures`): por placa, o SHA256 do DTB de origem (de
qualquer das fontes do D12) e as leituras
que a distinguem (o ID do painel lido pelo DSI, que o kernel padrão já registra com o patch
0012; níveis de pinos de entrada livres; faixas do ADC). Bate a assinatura, o DTB convertido
ganha as regras correspondentes e entra na escolha automática como qualquer candidato com
regras (D3, D4). A tabela começa com o R36S V5 (medido) e cresce com medições de outras
placas; sem assinatura, o DTB só entra pela lista ou pelo `force`. A lista rola e aceita as
coleções inteiras (dArkOSRE e arkos4clone) mais os DTBs de fábrica e os nativos.

### D15. Assinatura do hardware pelo ID do painel e aprendizado na confirmação

Decisão do usuário (2026-11-15): um cartão para os dois consoles, reconhecendo qualquer
variante; mais DTBs podem ser acrescentados, e uma variação nova tem de ser reconhecida
quando o DTB dela é adicionado.

- **Assinatura:** o que o kernel padrão de cada SoC lê sem risco. Começa pelo **ID do
  painel** (DCS 04h), que cada driver de painel nosso lê uma vez e mostra em
  `/sys/bus/mipi-dsi/devices/*/panel_id` (hex minúsculo; patches 0031 e 0032). Pode crescer
  com as sondas do D4 (ADC, GPIO, I2C).
- **Regra nova `lume,panel-id`** (bytes) no nó `lume-select`: bate quando algum
  `panel_id` do sysfs é igual. Os DTBs do projeto a declaram com o valor medido.
- **Aprende sozinho** (usuário, 2026-11-15: "ele precisa aprender sozinho, caso não dê
  certo, ter a possibilidade de entrar em um menu e escolher o DTB"). O critério automático
  de que um DTB serve é **o painel responder** ao kernel que subiu com ele (o driver leu o
  ID: `panel_id` não vazio); com o DTB errado o painel não responde e a tela fica preta.
  - Assinatura sem regra nem aprendizado que bata: se o painel respondeu com o DTB em uso,
    ele é aceito e aprendido (motivo `auto`, sem kexec).
  - Painel sem resposta com o DTB em uso: **busca** pelos candidatos ainda não descartados
    naquele aparelho, por prioridade; cada um sobe por kexec como `pending` (watchdog do D11)
    e o segundo início confere sozinho: painel respondeu → `good` e aprendido (motivo
    `search`); não respondeu → `bad` e kexec para o próximo; sem mais candidatos → volta ao
    padrão (`reverted`).
  - O aprendido fica em `ROMS/system/etc/dtb-<soc>-learned.conf` (`assinatura=lume,id`, no
    cartão, junto do estado do D6) e vale para qualquer aparelho com a mesma assinatura,
    com o motivo `learned`, abaixo do `force` e da lista e acima das regras. Um DTB que vai
    para `bad` sai do aprendizado.
- **Menu como saída:** a lista (tecla segurada ao ligar, D7) continua valendo sempre, para
  quando a escolha automática não servir (o painel respondeu, mas a imagem está errada, ou
  dois painéis com o mesmo ID). Uma escolha da lista confirmada na tela (A, D10) também é
  aprendida para aquela assinatura.
- **Limite:** o critério só existe para painéis cujo driver lê o ID (os nossos, patches 0031
  e 0032; o `panel-generic-dsi` do D13 tem de ler também). Sem `panel_id` no kernel do
  candidato, a busca não pode julgá-lo e ele não é testado sozinho; fica para a lista.
- **Dedução** (depois): um DTB de outro sistema cujo nó de painel usa um `compatible` que um
  driver nosso conhece ganha a assinatura desse painel sem precisar da primeira escolha.

**Alternativas descartadas:** só aprender na confirmação manual (exigiria o usuário em toda
variante nova) e regras só escritas à mão (uma variante nova exigiria mexer no projeto). O
custo da busca (um kexec por candidato errado, alguns segundos cada) só aparece no primeiro
boot de uma variante desconhecida.

### D16. No GA36 a troca grava a imagem de boot e reinicia (sem kexec)

Decisão do usuário (2026-11-15), depois das provas da tarefa 1.5 no GA36: com o DTB passado
à parte, o segundo kernel morre nos primeiros ~30 ms; imitando o U-Boot (`zImage` com o DTB
anexado e ATAGs) ele sobe, mas não retoma a tela e o cartão e trava. O R36S segue com kexec.

- O U-Boot de fábrica do GA36 carrega do setor 172032 uma imagem Android v0 com o `zImage`
  e o DTB anexado. Para trocar de DTB, o `lume-bootsel` monta essa imagem com
  `BOOT/ga36/zImage` e o DTB escolhido (do jeito do `src/r36os/bootimg.py`: cabeçalho de uma
  página com o `id` em SHA-1), grava no setor, lê de volta para conferir e sai com o código
  11; o `init` desmonta tudo e reinicia (`reboot -f`). Qualquer DTB copiado para
  `BOOT/dtbs/a33/` serve, sem o PC.
- O método vem de `/etc/bootsel-switch` do initramfs (`android-boot <setor>`, de
  `board/ga36/bootsel-switch`), e o disco, do `--disk` que o `init` passa; sem o arquivo, a
  troca é por kexec.
- O "segundo início" é reconhecido pelo estado, não pelo `/chosen`: o DTB em execução é o
  `pending`. O motivo da troca vai junto (`pending_reason=` no arquivo do D6), e a pergunta na
  tela, a conferência da busca, o aprendizado e a volta (`reverted`, que grava a imagem do
  anterior e reinicia) são os mesmos do kexec.
- Sem watchdog na troca (o reinício passa pelo U-Boot). Um DTB que travar o kernel exige
  desligar e ligar; no boot seguinte o `pending` não confirmado volta ao anterior. Os DTBs
  do GA36 diferem no painel, então o kernel sempre sobe e a USB continua disponível.

### D17. DTBs de fábrica e do (d)ArkOS convertidos no PC, carregados sob demanda

Decisão do usuário (2026-11-16, "pode seguir com a absorção dos DTBs"), revisando o D12:

- **Onde converte:** `r36os dtb-import NOME=PASTA...` (`src/r36os/vendor_dtb.py`) lê os
  DTBs das coleções (`.cache/upstream/dArkOSRE-R36`, `arkos4clone`, `EE-Clones-DTB`) e
  escreve um DTS por placa em `board/r36s/dts-vendor/<lume,id>.dts`, mais o
  `SOURCES.tsv` (cada arquivo lido: `converted`, `refused` com o motivo, ou `same` quando
  repete outro). Os DTS ficam no git: são fonte nossa, revisável, e o build não depende das
  coleções nem da rede (projeto autônomo).
- **O DTS convertido** faz `#include "rk3326-r36s-v5.dts"` e sobrescreve só o que muda
  entre as placas: painel (`rocknix,generic-dsi`, D13), pinos de reset/enable/stbyb e
  alimentação do painel, luz de fundo (PWM, período, níveis), botões (`gpio-keys`), teclas
  de volume (GPIO ou `adc-keys`), analógicos (mux de 4 canais ou ADC direto, ou nenhum),
  amplificador e detecção do fone, bateria (capacidade e tabela de tensão), LEDs, a
  interrupção do PMIC e, desde o D18, a alimentação (reguladores do RK817 e domínios de I/O). O `rockchip,lane-rate` e os tempos da PHY do R36S V5 saem (cada
  painel tem o seu clock). `lume,id` = nome do arquivo, prioridade 0, sem `lume,default`,
  sem regras.
- **Build:** `build_dtbs` compila `dts-vendor/` com a árvore do kernel e roda um único
  `dt-validate` sobre os nativos e os convertidos; um erro para o build. Os DTBs vão para
  `BOOT/dtbs/rk3326/vendor/`; o teste da imagem confere que cada um tem o nome do seu
  `lume,id` e não é padrão.
- **No boot (velocidade, D1):** o `lume-bootsel` não lê `vendor/` num boot normal. Um DTB
  de lá só é carregado quando algo o nomeia: `force`, a lista (que lista os nomes da pasta
  sem abrir os arquivos), a escolha salva, o aprendido (D15) ou o estado (`good`,
  `pending`). A busca do D15 continua só com os nativos e os já carregados: tentar ~170
  DTBs por kexec não cabe num boot.
- **Lista longa:** rola (18 linhas na tela, "... N more above/below"), com as teclas
  opcionais `pageup`/`pagedown` do `bootsel-keys` (no R36S: esquerda/L1 e direita/R1).
- **Analógicos:** com os pinos do mux iguais aos do R36S V5, ficam os eixos medidos do
  nativo; nos outros, a semântica do `rocknix-singleadc-joypad` do ROCKNIX (canal `m` do
  `amux-channel-mapping` = estado `3, 1, 2, 0` do `gpio-mux`, inversões do DTB de origem),
  **não medida** (anotado no DTS de cada placa). O ArkOS e o dArkOS ignoram o
  `amux-channel-mapping` e usam níveis brutos; nenhuma das duas semânticas reproduz a
  medida do V5, então a de outras placas só se confirma nelas.
- **Ganho do alto-falante:** o `spk-volume` do codec de origem nunca é copiado (o codec
  mainline não tem a propriedade; o volume seguro é o do nativo e do patch 0024); o valor
  ignorado vai para a nota do DTS e o `SOURCES.tsv`.
- **Resultado da primeira importação (2026-11-16):** 285 arquivos, **168 placas
  convertidas** (44 do dArkOSRE, 124 do arkos4clone), 50 repetidas, 67 recusadas: joypad
  `play_joystick` (44, os DTBs de fábrica "EE" do EE-Clones-DTB, kernel de fábrica
  diferente), mux com mais de um canal de ADC (8), `odroidgo3-hid-joypad` (6, RG351),
  `micro,gamepad` (5), PMIC RK809 (2), sem joypad (1), sem painel DSI (1). As placas EE
  recusadas aparecem convertidas pelas versões do arkos4clone.
- **DTB de fábrica do R36S V5 convertido** (`out/r36s-factory`, fora do git): os 19
  botões e códigos, o mux, o amplificador, a detecção do fone, a interrupção do PMIC, a
  luz de fundo, a bateria e os LEDs batem com o `rk3326-r36s-v5` nativo (teste unitário);
  o painel muda de driver (ST7703 → genérico).
- **Licenças:** a lógica vem do `rocknix_dtbo.py` (MIT) e do driver do ROCKNIX (GPL-2.0),
  com crédito no código. Dos DTBs só saem parâmetros de hardware (pinos, timings,
  sequências de inicialização) para DTS nossos (`GPL-2.0+ OR MIT`), cada um com a origem e
  o SHA-256; o arkos4clone é MIT; o dArkOSRE e o EE-Clones-DTB não têm arquivo de licença
  (os DTBs vêm de árvores de dispositivo de kernels GPL-2.0 dos fabricantes). Crédito às
  três coleções no README.
- **Perde-se:** um DTB do (d)ArkOS copiado pelo usuário direto para o cartão não é
  convertido no aparelho (sem `lume-select`, é ignorado com o motivo no log); precisa de
  `r36os dtb-import` e de um build. É o preço de não converter no boot.

**Alternativas:** conversão no boot em C (D12 original): lenta (ler e converter dezenas de
DTBs a cada boot), sem `dt-validate`, e muito código no initramfs; DTBs gerados só no
build, sem DTS no git: o build dependeria das coleções e da rede.

### D18. Alimentação da origem nos convertidos (P-77)

Decisão do usuário (2026-11-16, trazendo o P-77 para esta change), depois da avaliação da
tarefa 7.2 (D12): até aqui o DTS convertido herdava do R36S V5 as tensões do RK817 e o mapa
dos domínios de I/O, e só o `factory-r35s` tem na origem a mesma alimentação. O conversor
passa a levá-la da origem:

- **Reguladores:** para cada regulador do RK817 que a origem declara (`DCDC_REG*`,
  `LDO_REG*`, `BOOST`, `SWITCH_REG*`), o DTS convertido leva a faixa de tensão
  (`regulator-min/max-microvolt`) e o `regulator-always-on`/`regulator-boot-on` da origem,
  sobre o nó do mesmo nome da base (referência pelo caminho, `&{/.../regulators/LDO_REG8}`).
  São os valores com que aquele sistema (de fábrica, dArkOS ou arkos4clone) já roda naquele
  hardware.
- **Sempre ligado, só somado (implementação, 2026-11-16):** o `regulator-always-on` e o
  `regulator-boot-on` da origem são acrescentados aos da base, nunca retirados. Um regulador
  que a base deixa ligado pode alimentar, na placa de origem, algo que o DTS convertido não
  liga a ele (no `darkosre-r36s-r35s-v11-2022-08-18` o LDO7 é o `vcc_backlight`, consumido
  pelo `backlight-supply` do painel do kernel 4.4), e o kernel desliga 30 s depois do boot o
  regulador sem consumidor e sem `always-on`. A tensão, o `regulator-name` e o
  `regulator-state-mem` vêm da origem. Com isso o `factory-r35s` fica com a alimentação do
  nativo (o `boot-on` do LDO6, que só o nativo tem, continua).
- **Regulador que a origem não declara:** fica sem tensão definida no DTS (o kernel mantém a
  que o bootloader deixou) e ligado, para não cortar algo de ligação desconhecida. Nós do
  RK809 que alguns DTBs de origem listam (`DCDC_REG5`, `SWITCH_REG1/2`) não existem no
  driver mainline do RK817: ficam de fora, anotados no `SOURCES.tsv`.
- **Domínios de I/O:** o mapa da origem (`vccio1`–`vccio6`, `vccio-oscgpi`, `pmuio1`,
  `pmuio2`) é refeito no `&io_domains`/`&pmu_io_domains` da base, cada domínio apontando o
  regulador do RK817 do mesmo nome de nó. Domínio que a origem não declara sai da base
  (`/delete-property/`), e o driver deixa o seletor como o bootloader o pôs.
- **Recusa com motivo** (`SOURCES.tsv`): PMIC sem nó `regulators`; domínio de I/O que aponta
  para um regulador fora do PMIC; tensão de um domínio acima de 3,6 V (o limite do driver).
- **Referência independente:** a família "EE" (D12) é conferida contra o
  `rk3326-gameconsole-eeclone.dts` do ROCKNIX (GPL-2.0+ OR MIT, `.cache/upstream/rocknix`),
  que descreve a mesma alimentação para o kernel mainline. **Resultado (2026-11-16, tarefa
  10.3):** nos 55 DTBs do EE-Clones-DTB e no `arkos4clone-k36`, cada domínio aponta o mesmo
  regulador que no ROCKNIX (10 DTBs não declaram o `vccio6`, que no convertido fica sem
  alimentação declarada) e os reguladores dos domínios (DCDC4 3,0 V, LDO2 1,8 V, LDO4 3,0 V,
  LDO5 e LDO7 1,8–3,3 V) têm as mesmas tensões. Diferem, fora dos domínios: o BOOST (4,7 ou
  5,0 V de mínimo; ROCKNIX 4,9 V), o mínimo do DCDC2 (0,95 V; ROCKNIX 0,85 V), o LDO6
  (`vmmc` do cartão, 3,3 V fixo; ROCKNIX 1,8–3,3 V), o LDO8 (3,3 V; ROCKNIX 3,0 V) e o LDO9
  do G30 (3,3 V; ROCKNIX 1,5 V). O convertido segue a origem.
- **O que fica da base:** o resto da placa EE que não é alimentação crítica (USB host por
  GPIO, eMMC, segundo slot) continua o do R36S V5; aparelhos com eMMC já estão fora do
  alcance (P-43).

**Alternativas:** uma segunda base a partir do DTS do ROCKNIX, escolhida pelos domínios de
I/O da origem (o texto original do P-77): exigiria manter outro DTS inteiro e não resolveria
a família "RG351/origin" (painel a 2,8 V no LDO8), que tem a base do R36S; manter a
alimentação do R36S V5 com um aviso: deixa ~150 convertidos com seletor de tensão trocado em
relação à alimentação física.

## Risks / Trade-offs

- [kexec no armv7 com SMP: o A33 mainline pode não conseguir desligar os núcleos
  secundários] → **confirmado no GA36 (boot 20):** o método `allwinner,sun8i-a23` não tinha
  `.cpu_kill`, e o kernel recusa o kexec calado; o patch `0027` acrescenta `.cpu_die` e
  `.cpu_kill` (tarefa 3.6). Se ainda assim falhar no aparelho, vale o plano abaixo. Prova 1.5 antes do código; se falhar, o GA36 fica com a troca pelo
  `force` lido pelo U-Boot (`env import -t` de um arquivo da `BOOT`, se a prova 1.4 der
  certo) ou pela imagem de boot gravada com `dd`, que continua valendo.
- [Drivers que não reiniciam limpos depois do kexec (DSI, painel, PMIC, MMC)] → a prova 1.5
  sobe até o frontend depois de um kexec e confere tela, som e cartão.
- [Um DTB errado pode programar tensões erradas] → só candidatos do mesmo SoC, só DTBs do
  build na imagem; um DTB copiado pelo usuário é responsabilidade dele, e o log diz qual foi
  usado. Nos convertidos, a alimentação é a da origem (D18), nunca a de outra placa.
- [Um DTB de SO declara outra alimentação que o de fábrica da mesma placa (o
  `darkosre-r36s-r35s-v11` e o `factory-r35s`, D12)] → vale o que aquele SO já roda na
  placa; a confirmação na tela e a volta automática continuam como saída, e a prova 10.4
  usa justamente esse caso no R36S.
- [Desligar antes da confirmação marca um DTB bom como ruim] → o motivo vai para o log, e a
  lista limpa o `bad`; é preferível a ficar preso num DTB que trava.
- [Confirmar às cegas: apertar A com a tela preta] → a mensagem só aparece uma vez por DTB
  novo e pede A explicitamente; se acontecer, o `force` de outro DTB ou a lista resolvem.
- [O watchdog não atravessa o kexec, ou o kernel novo o alimenta sozinho] → prova 1.6;
  sem ele, o travamento antes da pergunta ainda se resolve desligando e ligando.
- [Sem número de série do SoC no kernel] → prova 1.7; o estado volta a ser por SoC e o log
  avisa.
- [A tecla de volume desvia o U-Boot do GA36 para `recovery` ou `fastboot`] → prova 1.3;
  troca de tecla ou de combinação no `bootsel-keys`.
- [Tempo de boot] → as sondas leem alguns arquivos (milissegundos); o kexec custa 1 a 2 s
  só quando troca.
- [Escrever no exFAT da `ROMS` cedo no boot] → as mesmas funções de montagem do init; um
  arquivo pequeno, gravado com `sync`.
- [Clone com outra memória ou outra cadeia de boot não passa do bootloader de fábrica do
  R36S] → fora do alcance do DTB; o log não chega a existir. Fica no P-43. Indício a favor:
  o ArkOS de série sobe o U-Boot nos clones "EE" (o LED vermelho piscando vem depois dele),
  inclusive nos V20 com LPDDR3; aparelhos com eMMC iniciam pelo eMMC e ficam de fora.
- [Ganho do amplificador alto demais queima o alto-falante (caso do arkos4clone no
  R36S-V20)] → o conversor usa o volume seguro da base e não copia o do DTB de origem.
- [DTB convertido de um clone com chip sem driver no nosso kernel] → o conversor recusa o
  que não mapeia; um chip novo exige o driver (patch numerado).
- [Conversão provada só no R36S V5] → os 43 DTBs passam nos testes de conversão e no
  `dt-validate`, mas o funcionamento em cada placa só se prova nela; a confirmação na tela e
  a volta automática protegem do painel errado. Clones ficam "compatíveis por conversão,
  sem garantia".
- [Painéis de 720x720 e timings acima do que o RetroArch espera] → o conversor leva o
  `native-mode`; a configuração de vídeo por resolução fica no P-33.
- [Tempo de conversão no boot] → não existe mais (D17): a conversão é no PC e o boot só lê
  `vendor/` quando um DTB de lá é nomeado.
- [Eixos dos analógicos trocados ou invertidos numa placa convertida] → semântica do
  ROCKNIX, não medida (D17); o remapeamento do RetroArch resolve, e a placa medida pode
  ganhar a correção no conversor.

## Migration Plan

`r36os flash console <dispositivo> --update` grava a área de boot (env e `bootlogo.bmp` do
GA36) e a `BOOT` nova; a `ROMS` não muda. Para voltar atrás, regravar o build anterior com
`--update`. Um cartão sem o layout novo continua iniciando como antes (o initramfs novo só
existe no build novo).

## Open Questions

- Tamanho do env do GA36 e se ele tem cópia redundante: lidos da tabela `softw411` na
  tarefa 2.2, sem mudar o desenho.
- Endereço de carga do logo no GA36 e o número do dispositivo MMC: saem da prova 1.4.
