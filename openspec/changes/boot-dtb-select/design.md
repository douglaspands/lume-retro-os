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

**Non-Goals:**
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
  ga36/ SYSTEM  zImage  android-boot/
  r36s/ SYSTEM  Image
```

`ga36/dtbs/` e `r36s/<dtb>` saem. O `boot.ini` passa a carregar
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

## Risks / Trade-offs

- [kexec no armv7 com SMP: o A33 mainline pode não conseguir desligar os núcleos
  secundários] → prova 1.5 antes do código; se falhar, o GA36 fica com a troca pelo
  `force` lido pelo U-Boot (`env import -t` de um arquivo da `BOOT`, se a prova 1.4 der
  certo) ou pela imagem de boot gravada com `dd`, que continua valendo.
- [Drivers que não reiniciam limpos depois do kexec (DSI, painel, PMIC, MMC)] → a prova 1.5
  sobe até o frontend depois de um kexec e confere tela, som e cartão.
- [Um DTB errado pode programar tensões erradas] → só candidatos do mesmo SoC, só DTBs do
  build na imagem; um DTB copiado pelo usuário é responsabilidade dele, e o log diz qual foi
  usado.
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

## Migration Plan

`r36os flash console <dispositivo> --update` grava a área de boot (env e `bootlogo.bmp` do
GA36) e a `BOOT` nova; a `ROMS` não muda. Para voltar atrás, regravar o build anterior com
`--update`. Um cartão sem o layout novo continua iniciando como antes (o initramfs novo só
existe no build novo).

## Open Questions

- Tamanho do env do GA36 e se ele tem cópia redundante: lidos da tabela `softw411` na
  tarefa 2.2, sem mudar o desenho.
- Endereço de carga do logo no GA36 e o número do dispositivo MMC: saem da prova 1.4.
