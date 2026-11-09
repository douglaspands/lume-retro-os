# Spec Delta

## Purpose

Define as imagens de cartão geradas para cada alvo (R36S, GA36 e VM), o layout de partições e como o sistema é empacotado nelas.

## ADDED Requirements

### Requirement: Uma imagem por alvo a partir da mesma base
O build MUST gerar uma imagem para cada alvo: `r36s` (aarch64), `ga36` (armv7) e `vm` (x86_64). As três MUST usar a mesma versão do Alpine, a mesma lista de pacotes de userland, a mesma configuração e os mesmos cores. Só a camada de hardware MUST variar: kernel, DTBs, bootloader e firmware.

#### Scenario: Mesma lista de pacotes nos três alvos
- **WHEN** as três imagens são geradas no mesmo build
- **THEN** o manifesto de pacotes de userland de cada uma lista os mesmos nomes e versões, exceto os pacotes declarados como camada de hardware

#### Scenario: Alvo desconhecido
- **WHEN** o build é chamado com um alvo fora de `r36s`, `ga36` e `vm`
- **THEN** o build falha antes de gerar qualquer arquivo e lista os alvos válidos

### Requirement: Tabela de partições MBR com BOOT FAT32
A imagem gravada MUST ter tabela MBR com uma única partição: `BOOT`, FAT32, rótulo `BOOT`, 1 GiB, começando em 16 MiB. Os primeiros 16 MiB MUST ficar livres de partições, reservados ao bootloader de cada alvo.

#### Scenario: Layout da imagem recém-gerada
- **WHEN** a tabela de partições de qualquer imagem gerada é lida
- **THEN** ela é MBR, tem só a partição 1, FAT32 com rótulo `BOOT`, começa no setor 32768 (16 MiB) e tem 1 GiB

### Requirement: Conteúdo da partição BOOT
A partição `BOOT` MUST conter o kernel do alvo, o initramfs, a configuração de boot no formato extlinux (`extlinux/extlinux.conf`), os DTBs do alvo (só nos consoles) e o arquivo de sistema `SYSTEM`. Os logs não ficam na `BOOT` (ver `boot-runtime`).

#### Scenario: Arquivos presentes na BOOT
- **WHEN** a partição `BOOT` de uma imagem gerada é listada
- **THEN** existem o kernel, o `initramfs`, `extlinux/extlinux.conf` e `SYSTEM`, sem pasta `logs/`, e nos alvos `r36s` e `ga36` também `dtbs/` com os DTBs do console

### Requirement: Sistema como arquivo squashfs
O sistema de arquivos raiz MUST ser entregue como um único arquivo squashfs chamado `SYSTEM` dentro da `BOOT`, com no máximo 768 MiB, para sobrar espaço na `BOOT` para uma atualização.

#### Scenario: SYSTEM dentro do limite
- **WHEN** uma imagem é gerada
- **THEN** `SYSTEM` é um squashfs válido de até 768 MiB e o build falha se esse limite for ultrapassado

### Requirement: Bootloader na área reservada
Nos consoles, o build MUST gravar o bootloader na área antes de 16 MiB, no offset que a ROM de boot do SoC exige: R36S com `idbloader` no setor 64 e `u-boot.itb` no setor 16384; GA36 com U-Boot sunxi (SPL incluso) em 8 KiB. Na VM, MUST gravar um bootloader que leia o mesmo `extlinux.conf`.

#### Scenario: Bootloader do R36S
- **WHEN** a imagem `r36s` é gerada
- **THEN** os bytes a partir do setor 64 são o `idbloader` e os bytes a partir do setor 16384 são o `u-boot.itb`, ambos do mesmo build

#### Scenario: Bootloader do GA36
- **WHEN** a imagem `ga36` é gerada
- **THEN** os bytes a partir de 8 KiB são o U-Boot sunxi com SPL, e a tabela MBR do setor 0 continua intacta

#### Scenario: Bootloader da VM
- **WHEN** a imagem `vm` sobe no QEMU com firmware BIOS
- **THEN** o bootloader lê `extlinux/extlinux.conf` da `BOOT` e carrega o kernel e o initramfs indicados nele

### Requirement: Build reproduzível e isolado do host
O build MUST rodar dentro de containers rootless e não instalar nada no host sem confirmação explícita. Dois builds da mesma revisão MUST gerar manifestos de pacotes iguais.

#### Scenario: Manifesto estável
- **WHEN** o mesmo alvo é gerado duas vezes a partir da mesma revisão do repositório
- **THEN** o manifesto de pacotes e versões das duas imagens é idêntico

### Requirement: Tamanho mínimo do cartão
A imagem MUST caber em um cartão de 4 GB, deixando ao menos 2 GB para a partição de jogos criada no primeiro boot.

#### Scenario: Cartão de 4 GB
- **WHEN** a imagem é gravada em um cartão de 4 GB e o primeiro boot termina
- **THEN** a partição de jogos tem pelo menos 2 GB livres
