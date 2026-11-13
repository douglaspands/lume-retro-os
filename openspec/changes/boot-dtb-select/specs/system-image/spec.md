# Spec Delta

## ADDED Requirements

### Requirement: Logo de boot único
Os dois consoles MUST mostrar no boot o mesmo logo, o `BOOT/logo.bmp`, que é o logo de fábrica do R36S, conferido por SHA256. No GA36, o build MUST gravar o mesmo arquivo como `bootlogo.bmp` na FAT interna da área de fábrica, e o U-Boot de fábrica MUST carregar o logo da `BOOT`, de modo que trocar o `BOOT/logo.bmp` pelo PC troque o logo dos dois consoles.

#### Scenario: Mesmo logo nos dois
- **WHEN** um cartão recém-gravado com a imagem `console` é ligado no GA36 e no R36S
- **THEN** os dois mostram o logo de fábrica do R36S, e o `bootlogo.bmp` da FAT interna do GA36 é idêntico ao `BOOT/logo.bmp`

#### Scenario: Logo trocado pelo PC
- **WHEN** o usuário troca o `BOOT/logo.bmp` por outro BMP de 640x480 e 24 bits e liga os dois consoles
- **THEN** o R36S mostra o logo novo e o GA36 também o mostra depois do primeiro quadro, que ainda vem da FAT interna

## MODIFIED Requirements

### Requirement: Conteúdo da partição BOOT
A partição `BOOT` MUST conter o `VERSION` do build e um `SYSTEM` por sistema da imagem. Na VM, MUST conter também o kernel, o initramfs e a configuração de boot no formato extlinux (`extlinux/extlinux.conf`). Na imagem `console`, MUST conter só o que os consoles leem: uma pasta por console, `ga36/` com o `SYSTEM` e o kernel como arquivo, e `r36s/` com o `SYSTEM` e o kernel; uma pasta de DTBs por SoC, `dtbs/a33/` e `dtbs/rk3326/` (ver `dtb-selection`), onde o arquivo opcional `dtbs/force` é lido se existir; e, na raiz, o `boot.ini` lido pelo U-Boot do R36S, os dois DTBs do RG351 de fábrica (`rg351mp-kernel.dtb` e `rg351p-kernel.dtb`) que esse U-Boot exige para iniciar, e o `logo.bmp` dos dois consoles. As imagens de boot dos dois painéis do GA36 (gravadas no setor 172032 com `dd`) MUST NOT ficar na `BOOT`: elas MUST ser arquivadas com o build, ao lado da imagem do cartão, com o SHA256 no `SHA256SUMS`. Os logs não ficam na `BOOT` (ver `boot-runtime`).

#### Scenario: Arquivos presentes na BOOT
- **WHEN** a partição `BOOT` de uma imagem gerada é listada
- **THEN** existe `VERSION`, sem pasta `logs/`; na `vm` também `SYSTEM`, o kernel, o `initramfs` e `extlinux/extlinux.conf`; na `console` também `boot.ini`, `rg351mp-kernel.dtb`, `rg351p-kernel.dtb`, `logo.bmp`, `ga36/SYSTEM`, o kernel do GA36, `r36s/SYSTEM`, o kernel do R36S, `dtbs/a33/` com os DTBs dos dois painéis do GA36 e `dtbs/rk3326/` com o DTB do R36S V5, sem `dtbs/force` e sem `ga36/android-boot/`

#### Scenario: Imagens de boot dos painéis arquivadas
- **WHEN** a imagem `console` é gerada
- **THEN** a pasta do build em `out/images/console/<build>/` tem `ga36-android-boot-panel1.img` e `ga36-android-boot-panel2.img`, com o SHA256 de cada uma no `SHA256SUMS`

### Requirement: Bootloader na área reservada
Na imagem `console`, o build MUST montar a área de 128 MiB antes da `BOOT` a partir das áreas de fábrica dos dois consoles, lidas de cópias dos cartões originais e conferidas por SHA256, fora do git: a do GA36 (`R36OS_GA36_FACTORY`) e a do R36S (`R36OS_R36S_FACTORY`). No setor 172032 MUST ir a imagem de boot Android do painel 1 do GA36. Na área do GA36, o build MUST trocar o `bootlogo.bmp` da FAT interna pelo logo da `BOOT` e editar o env do U-Boot de fábrica (com o CRC recalculado) para carregar o logo da `BOOT`, sem alterar nenhum binário. Na VM, MUST gravar um bootloader que leia o `extlinux.conf`. O U-Boot mainline dos consoles fica para depois (P-19, P-34 e P-43).

#### Scenario: Bootloader do GA36
- **WHEN** a imagem `console` é gerada
- **THEN** a área de 8 KiB até a `BOOT` é igual à área de fábrica do GA36, exceto o boot0 encolhido (setores 16 a 63), a cadeia do R36S nos setores que ela ocupa no cartão original do R36S, o `bootlogo.bmp` da FAT interna, o env do U-Boot e a imagem de boot no setor 172032; e a tabela MBR do setor 0 é a nossa

#### Scenario: Env do GA36 válido
- **WHEN** o env do U-Boot do GA36 é lido da imagem gerada
- **THEN** o CRC confere, as variáveis de fábrica continuam iguais exceto o `bootcmd`, e o `bootcmd` carrega o `logo.bmp` da `BOOT` antes do boot normal

#### Scenario: Bootloader da VM
- **WHEN** a imagem `vm` sobe no QEMU com firmware BIOS
- **THEN** o bootloader lê `extlinux/extlinux.conf` da `BOOT` e carrega o kernel e o initramfs indicados nele
