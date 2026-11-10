# Proposta: Swap comprimido em ZRAM nos três alvos (GA36, R36S e VM)

## Why

O GA36-MB V1.2 conta com 512 MiB de RAM física (e o R36S com 1 GiB), compartilhados entre kernel, buffers gráficos (DRM/CMA), a camada gravável da raiz em `tmpfs` (até 32 MiB), logs em `/run` e o RetroArch com o core ativo. Sem swap em RAM (`zram`), a pressão de memória força o descarte do cache de páginas (exigindo releitura do cartão SD lento e descompressão `zstd` do `SYSTEM` squashfs) ou aciona o OOM killer em cores mais pesados, pelo que precisamos ativar o ZRAM já para o teste em hardware real do GA36.

## What Changes

- **Suporte a ZRAM com LZ4 no kernel dos consoles (`ga36` e `r36s`):** habilitar `CONFIG_ZSMALLOC=y`, `CONFIG_ZRAM=y`, `CONFIG_ZRAM_BACKEND_LZ4=y` e `CONFIG_ZRAM_DEF_COMP_LZ4=y` no fragmento de kernel do GA36 (`board/ga36/kernel.config`) e na configuração do R36S (`board/r36s/kernel.config`), mantendo paridade com a VM (`linux-virt`, onde `zram` já existe como módulo).
- **Serviço de inicialização `r36os-zram` no runlevel `boot`:** criar `/etc/init.d/r36os-zram` na base comum (`rootfs/overlay/`), executado nos três alvos (`ga36`, `r36s` e `vm`). O serviço carrega o módulo `zram` quando aplicável, seleciona o compressor `lz4`, dimensiona `/dev/zram0` em **50% de `MemTotal`** (~256 MiB no GA36 de 512 MiB; ~512 MiB no R36S e na VM de 1 GiB), formata com `mkswap` e ativa com prioridade máxima (`swapon -p 32767`). Falhas não interrompem o boot.
- **Ajuste de parâmetros de memória virtual (`sysctl`) para ZRAM:** adicionar `/etc/sysctl.d/r36os-zram.conf` com `vm.swappiness = 100` (equilibra a compressão de páginas anônimas e `tmpfs` na ZRAM frente ao descarte de cache de arquivos do `SYSTEM` squashfs/SD) e `vm.page-cluster = 0` (descomprime 1 página por page fault, sem read-ahead desnecessário na CPU Cortex-A7/A35).
- **Validação automatizada e geração da imagem do GA36:** incluir verificações do kernel config do GA36, teste do serviço `r36os-zram` e checagem no `r36os-selftest` da VM, reutilizando toda a infraestrutura já implementada na branch atual (`initramfs`, `hwinfo`, `logd` e pipeline de build) para gerar a imagem `ga36.img` com ZRAM ativo.
- **Ejeção segura pós-gravação no CLI (`r36os flash --eject`):** adicionar a flag `--eject` ao subcomando `flash`, permitindo desmontar partições e desligar/ejetar com segurança o leitor ou cartão SD via `udisksctl power-off` (com fallback para `eject`) após a gravação e verificação SHA256 no modo `--update` ou `full`.

## Capabilities

### New Capabilities
- `boot-runtime`: ativação de swap comprimido em ZRAM (`50%` da RAM, `lz4`, prioridade `32767`) e ajuste de `vm.swappiness=100` e `vm.page-cluster=0` no boot dos três alvos (`ga36`, `r36s` e `vm`).
- `system-image`: suporte ao argumento `--eject` no comando `r36os flash` para desmonte e ejeção segura do dispositivo de bloco após a gravação.

### Modified Capabilities
Nenhuma (`openspec/specs/` ainda não possui specs arquivadas; este delta adiciona os requisitos a `boot-runtime` e `system-image`).

## Impact

- **Kernel:** `board/ga36/kernel.config` (e `board/r36s/kernel.config` quando criado) passa a embutir `zram` + `zsmalloc` + `lz4`.
- **Rootfs comum:** `rootfs/configure.sh`, `rootfs/overlay/etc/init.d/r36os-zram` e `rootfs/overlay/etc/sysctl.d/r36os-zram.conf`.
- **Ferramentas de host:** `src/r36os/flash.py` e `src/r36os/cli.py` com suporte ao flag `--eject`.
- **Observabilidade (já pronta na branch):** `hwinfo` (`ROMS/logs/hw/boot-<n>.txt`) e `logd` (`swap_used_mb` em `ROMS/logs/metrics/boot-<n>.csv`) passam a reportar automaticamente o tamanho e o uso real do `zram0`.
- **Testes e artefatos:** `tests/unit/test_ga36_kernel_config.py`, `tests/unit/test_r36s_kernel_config.py`, `tests/unit/test_zram_service.py`, `tests/unit/test_flash.py`, `rootfs/overlay/usr/libexec/r36os/selftest`, `src/r36os/selftest.py` e nova imagem `out/ga36/ga36.img` arquivada em `out/images/ga36/`.
