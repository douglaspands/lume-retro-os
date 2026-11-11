# Spec Delta

## Purpose

Define as imagens de cartão geradas para cada alvo desta versão (GA36 e VM), o layout de partições e como o sistema é empacotado nelas. O alvo `r36s` fica reservado para a change do R36S (pendência P-27).

## ADDED Requirements

### Requirement: Uma imagem por alvo a partir da mesma base
O build MUST gerar uma imagem para cada alvo desta versão: `ga36` (armv7) e `vm` (x86_64). As duas MUST usar a mesma versão do Alpine, a mesma lista de pacotes de userland, a mesma configuração e os mesmos cores. Só a camada de hardware MUST variar: kernel, DTBs, bootloader e firmware.

#### Scenario: Mesma lista de pacotes nos dois alvos
- **WHEN** as duas imagens são geradas no mesmo build
- **THEN** o manifesto de pacotes de userland de cada uma lista os mesmos nomes e versões, exceto os pacotes declarados como camada de hardware

#### Scenario: Alvo desconhecido
- **WHEN** o build é chamado com um alvo fora de `r36s`, `ga36` e `vm`
- **THEN** o build falha antes de gerar qualquer arquivo e lista os alvos válidos

### Requirement: Tabela de partições MBR com BOOT FAT32
A imagem gravada MUST ter tabela MBR com uma única partição: `BOOT`, FAT32, rótulo `BOOT`, 1 GiB. A área antes da `BOOT` MUST ficar livre de partições, reservada ao bootloader do alvo: 16 MiB na VM (a `BOOT` começa no setor 32768) e 128 MiB no GA36, a área de boot do fabricante (a `BOOT` começa no setor 262144).

#### Scenario: Layout da imagem recém-gerada
- **WHEN** a tabela de partições de uma imagem gerada é lida
- **THEN** ela é MBR, tem só a partição 1, FAT32 com rótulo `BOOT` e 1 GiB, começando no setor 32768 na `vm` e no setor 262144 no `ga36`

### Requirement: Conteúdo da partição BOOT
A partição `BOOT` MUST conter o arquivo de sistema `SYSTEM` e o `VERSION` do build. Na VM, MUST conter também o kernel, o initramfs e a configuração de boot no formato extlinux (`extlinux/extlinux.conf`). No GA36, o kernel com o DTB anexado e o initramfs embutido vai na imagem de boot Android (setor 172032), e a `BOOT` MUST conter os DTBs em `dtbs/` e as imagens de boot dos dois painéis em `android-boot/`. Os logs não ficam na `BOOT` (ver `boot-runtime`).

#### Scenario: Arquivos presentes na BOOT
- **WHEN** a partição `BOOT` de uma imagem gerada é listada
- **THEN** existem `SYSTEM` e `VERSION`, sem pasta `logs/`; na `vm` também o kernel, o `initramfs` e `extlinux/extlinux.conf`; no `ga36` também `dtbs/` e `android-boot/` com as imagens dos painéis 1 e 2

### Requirement: Sistema como arquivo squashfs
O sistema de arquivos raiz MUST ser entregue como um único arquivo squashfs chamado `SYSTEM` dentro da `BOOT`, com no máximo 768 MiB, para sobrar espaço na `BOOT` para uma atualização.

#### Scenario: SYSTEM dentro do limite
- **WHEN** uma imagem é gerada
- **THEN** `SYSTEM` é um squashfs válido de até 768 MiB e o build falha se esse limite for ultrapassado

### Requirement: Bootloader na área reservada
No GA36, o build MUST gravar nos primeiros 128 MiB a área de boot do fabricante (boot0 e U-Boot da Allwinner, lidos da imagem de fábrica indicada por `R36OS_GA36_FACTORY` e conferidos por SHA256, fora do git) e, no setor 172032, a imagem de boot Android do painel 1. Na VM, MUST gravar um bootloader que leia o `extlinux.conf`. O U-Boot mainline do GA36 fica para depois (tarefa 12.2).

#### Scenario: Bootloader do GA36
- **WHEN** a imagem `ga36` é gerada
- **THEN** a área de 8 KiB até a `BOOT` é igual à da imagem de fábrica, exceto a imagem de boot no setor 172032, e a tabela MBR do setor 0 é a nossa

#### Scenario: Bootloader da VM
- **WHEN** a imagem `vm` sobe no QEMU com firmware BIOS
- **THEN** o bootloader lê `extlinux/extlinux.conf` da `BOOT` e carrega o kernel e o initramfs indicados nele

### Requirement: Build reproduzível e isolado do host
O build MUST rodar dentro de containers rootless e não instalar nada no host sem confirmação explícita. Dois builds da mesma revisão MUST gerar manifestos de pacotes iguais.

#### Scenario: Manifesto estável
- **WHEN** o mesmo alvo é gerado duas vezes a partir da mesma revisão do repositório
- **THEN** o manifesto de pacotes e versões das duas imagens é idêntico

### Requirement: Tamanho mínimo do cartão
A imagem MUST caber em um cartão de 4 GB, deixando ao menos 2 GB para a partição de jogos, criada pelo `r36os flash` com todo o resto do cartão (ou no primeiro boot, se faltar).

#### Scenario: Cartão de 4 GB
- **WHEN** a imagem é gravada em um cartão de 4 GB com `r36os flash --full`
- **THEN** a partição de jogos tem pelo menos 2 GB livres
