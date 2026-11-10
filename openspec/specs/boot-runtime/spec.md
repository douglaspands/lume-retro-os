# boot-runtime Specification

## Purpose

Define como o sistema sobe a partir do cartão: montagem do sistema imutável, criação e verificação da partição de jogos, persistência seletiva, mensagens de boot, swap comprimido em ZRAM e logs.

## Requirements

### Requirement: Swap comprimido em ZRAM no boot
Em todos os alvos (`ga36`, `r36s` e `vm`), o sistema MUST configurar e ativar no boot um dispositivo de swap em ZRAM (`/dev/zram0`) com compressor `lz4`, tamanho descomprimido igual a 50% da memória RAM total (`MemTotal`) e prioridade máxima (`32767`). Caso o dispositivo ZRAM não esteja disponível, o boot MUST registrar um aviso e prosseguir normalmente sem bloquear o sistema.

#### Scenario: ZRAM ativo no GA36 (512 MiB)
- **WHEN** o GA36 com 512 MiB de RAM conclui o runlevel de boot
- **THEN** `/dev/zram0` está ativo em `/proc/swaps` com prioridade `32767`, algoritmo `lz4` em `/sys/block/zram0/comp_algorithm` e `disksize` igual à metade de `MemTotal` (~256 MiB)

#### Scenario: ZRAM ativo no R36S e na VM (1 GiB)
- **WHEN** o R36S ou a VM com 1 GiB de RAM conclui o runlevel de boot
- **THEN** `/dev/zram0` está ativo em `/proc/swaps` com prioridade `32767`, algoritmo `lz4` e `disksize` igual à metade de `MemTotal` (~512 MiB)

#### Scenario: Falha no ZRAM não interrompe o boot
- **WHEN** `/dev/zram0` não existe e o módulo `zram` não pode ser carregado
- **THEN** o serviço registra o aviso no log do sistema, encerra com código `0` e o frontend inicia normalmente sem swap

### Requirement: Parâmetros de memória virtual ajustados para ZRAM
O sistema MUST configurar no boot `vm.swappiness=100` e `vm.page-cluster=0` via `sysctl`, para priorizar o envio de páginas anônimas e `tmpfs` frias ao ZRAM sem leituras especulativas de múltiplas páginas em cada page fault.

#### Scenario: Valores de sysctl aplicados no boot
- **WHEN** o sistema conclui o runlevel de boot
- **THEN** `/proc/sys/vm/swappiness` vale `100` e `/proc/sys/vm/page-cluster` vale `0`
