# Spec Delta

## MODIFIED Requirements

### Requirement: Uma imagem por alvo a partir da mesma base
O build MUST gerar duas imagens: `console` (um cartão único para o GA36, armv7, e o R36S V5, aarch64) e `vm` (x86_64). Os três sistemas (`ga36`, `r36s` e `vm`) MUST usar a mesma versão do Alpine, a mesma lista de pacotes de userland, a mesma configuração e os mesmos cores. Só a camada de hardware MUST variar: kernel, DTBs, bootloader e firmware.

#### Scenario: Mesma lista de pacotes nos dois alvos
- **WHEN** a imagem `console` e a imagem `vm` são geradas a partir da mesma revisão
- **THEN** o manifesto de pacotes de userland do `SYSTEM` do GA36, do `SYSTEM` do R36S e do `SYSTEM` da VM lista os mesmos nomes e versões, exceto os pacotes declarados como camada de hardware

#### Scenario: Alvo desconhecido
- **WHEN** o build é chamado com um alvo fora de `console` e `vm`
- **THEN** o build falha antes de gerar qualquer arquivo e lista os alvos válidos

### Requirement: Tabela de partições MBR com BOOT FAT32
A imagem gravada MUST ter tabela MBR com uma única partição: `BOOT`, FAT32, rótulo `BOOT`, 1 GiB. A área antes da `BOOT` MUST ficar livre de partições, reservada aos bootloaders: 16 MiB na VM (a `BOOT` começa no setor 32768) e 128 MiB na imagem `console`, a área de boot dos dois consoles (a `BOOT` começa no setor 262144). A assinatura de disco da imagem `console` MUST ser a mesma dos cartões do GA36 gravados antes desta versão (`4c554d32`).

#### Scenario: Layout da imagem recém-gerada
- **WHEN** a tabela de partições de uma imagem gerada é lida
- **THEN** ela é MBR, tem só a partição 1, FAT32 com rótulo `BOOT` e 1 GiB, começando no setor 32768 na `vm` e no setor 262144 na `console`, e a assinatura de disco da `console` é `4c554d32`

### Requirement: Conteúdo da partição BOOT
A partição `BOOT` MUST conter o `VERSION` do build e um `SYSTEM` por sistema da imagem. Na VM, MUST conter também o kernel, o initramfs e a configuração de boot no formato extlinux (`extlinux/extlinux.conf`). Na imagem `console`, MUST conter uma pasta por console: `ga36/` com o `SYSTEM`, os DTBs em `dtbs/` e as imagens de boot dos dois painéis em `android-boot/`; `r36s/` com o `SYSTEM`, o kernel e o DTB; e, na raiz, o `boot.ini` lido pelo U-Boot do R36S. Os logs não ficam na `BOOT` (ver `boot-runtime`).

#### Scenario: Arquivos presentes na BOOT
- **WHEN** a partição `BOOT` de uma imagem gerada é listada
- **THEN** existe `VERSION`, sem pasta `logs/`; na `vm` também `SYSTEM`, o kernel, o `initramfs` e `extlinux/extlinux.conf`; na `console` também `boot.ini`, `ga36/SYSTEM`, `ga36/dtbs/`, `ga36/android-boot/` com as imagens dos painéis 1 e 2, `r36s/SYSTEM`, o kernel e o DTB do R36S

### Requirement: Sistema como arquivo squashfs
O sistema de arquivos raiz de cada sistema MUST ser entregue como um único arquivo squashfs chamado `SYSTEM` dentro da `BOOT`. Na `vm`, ele MUST ter no máximo 768 MiB. Na `console`, cada `SYSTEM` MUST ter no máximo 448 MiB, e a soma de todos os arquivos da `BOOT` MUST deixar ao menos 64 MiB livres.

#### Scenario: SYSTEM dentro do limite
- **WHEN** uma imagem é gerada
- **THEN** cada `SYSTEM` é um squashfs válido dentro do seu limite, a `BOOT` da `console` tem ao menos 64 MiB livres, e o build falha se algum limite for ultrapassado

### Requirement: Bootloader na área reservada
Na imagem `console`, o build MUST montar a área de 128 MiB antes da `BOOT` a partir das áreas de fábrica dos dois consoles, lidas de cópias dos cartões originais e conferidas por SHA256, fora do git: a do GA36 (`R36OS_GA36_FACTORY`) e a do R36S (`R36OS_R36S_FACTORY`). No setor 172032 MUST ir a imagem de boot Android do painel 1 do GA36. Na VM, MUST gravar um bootloader que leia o `extlinux.conf`. O U-Boot mainline dos consoles fica para depois (P-19 e pendência nova do R36S).

#### Scenario: Bootloader do GA36
- **WHEN** a imagem `console` é gerada
- **THEN** a área de 8 KiB até a `BOOT` é igual à área de fábrica do GA36, exceto o boot0 encolhido (setores 16 a 63), a cadeia do R36S nos setores que ela ocupa no cartão original do R36S e a imagem de boot no setor 172032; e a tabela MBR do setor 0 é a nossa

#### Scenario: Bootloader da VM
- **WHEN** a imagem `vm` sobe no QEMU com firmware BIOS
- **THEN** o bootloader lê `extlinux/extlinux.conf` da `BOOT` e carrega o kernel e o initramfs indicados nele

## ADDED Requirements

### Requirement: Cartão único para os dois consoles
O mesmo cartão gravado com a imagem `console` MUST iniciar no GA36 e no R36S V5, sem regravar nada entre um e outro, e os dois MUST usar a mesma partição `ROMS` (jogos, BIOS, saves e configuração).

#### Scenario: Trocar o cartão de console
- **WHEN** um cartão gravado com a imagem `console` é usado no GA36 e depois colocado no R36S
- **THEN** o R36S inicia o Lume e mostra os mesmos jogos e saves que o GA36 mostrava

#### Scenario: Ida e volta
- **WHEN** o cartão volta do R36S para o GA36
- **THEN** o GA36 inicia normalmente, e um save feito no R36S aparece no GA36

### Requirement: Boot0 do GA36 encolhido
Na área de boot da `console`, o boot0 do GA36 MUST ocupar só os setores 16 a 63, com o tamanho do cabeçalho eGON em 24 KiB e a soma recalculada pelo build. O build MUST falhar se o boot0 de fábrica tiver conteúdo diferente de `0xFF` depois dos primeiros 24 KiB.

#### Scenario: Cabeçalho válido
- **WHEN** a área de boot da `console` é inspecionada
- **THEN** o setor 16 tem a assinatura `eGON.BT0`, o tamanho declarado é 24576 bytes e a soma eGON confere com os 24 KiB gravados

#### Scenario: Boot0 maior que o espaço
- **WHEN** o build recebe uma área de fábrica cujo boot0 tem código além dos primeiros 24 KiB
- **THEN** o build falha com uma mensagem que explica o motivo, sem gerar a imagem

### Requirement: Cadeias de boot sem sobreposição
O build MUST garantir que nenhuma região usada pela cadeia de boot de um console sobrescreva dados não vazios da área de boot do outro, além do boot0 encolhido e do bloco de fábrica do GA36 nos setores 80 a 277, que não é usado. O `idbloader` do R36S MUST ficar no setor 64, o único que o BROM do RK3326 lê no cartão.

#### Scenario: Regiões conferidas no build
- **WHEN** a área de boot da `console` é montada
- **THEN** o build confere que as regiões do R36S (do setor 64 ao fim do `idbloader` e as do `uboot.img` e do `trust.img`) caem em setores vazios da área do GA36 ou nos setores 64 a 277, e falha listando os setores em conflito se não caírem

### Requirement: Atualização de cartões do GA36 para a imagem única
Um cartão gravado antes com a imagem `ga36` MUST aceitar `r36os flash console <dispositivo> --update`, que grava só a área de boot e a `BOOT`, sem tocar no setor 0 nem na `ROMS`. Depois disso, o cartão MUST iniciar nos dois consoles.

#### Scenario: Cartão antigo do GA36
- **WHEN** o usuário roda `r36os flash console <dispositivo> --update` num cartão gravado antes com a imagem `ga36`
- **THEN** a gravação é aceita, a `ROMS` fica intacta e o cartão inicia no GA36 e no R36S

#### Scenario: Cartão de outro layout
- **WHEN** o usuário roda `--update` da `console` num cartão cuja partição 1 tem outro início, tamanho ou assinatura
- **THEN** o comando recusa a gravação e explica que o cartão precisa de uma gravação completa
