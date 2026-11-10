# Design: Swap comprimido em ZRAM (GA36, R36S e VM)

## Context

Veja `proposal.md` para a motivação. Na branch atual (`alpine-retroarch-distro`), toda a infraestrutura de observabilidade e boot já suporta ZRAM:
- `initramfs/init` já ignora `zram*` ao procurar o disco de boot;
- `rootfs/overlay/usr/libexec/r36os/hwinfo` já lê `SwapTotal`, `SwapFree` e `/sys/block/zram*/disksize` no retrato de hardware (`ROMS/logs/hw/boot-<n>.txt`);
- `rootfs/overlay/usr/libexec/r36os/logd` já amostra `swap_used_mb` a cada 5 s em `ROMS/logs/metrics/boot-<n>.csv`;
- `out/vm/kernel/config-6.18.62-0-virt` (`linux-virt` do Alpine) já inclui `CONFIG_ZSMALLOC=y`, `CONFIG_ZRAM=m` e `CONFIG_ZRAM_BACKEND_LZ4=y`;
- `out/ga36/kernel/config` (`sunxi_defconfig` + `board/ga36/kernel.config`) tem `CONFIG_SWAP=y`, mas ainda está com `# CONFIG_ZRAM is not set`.

## Goals / Non-Goals

**Goals:**
- Reaproveitar 100% do que já foi implementado na branch atual, adicionando apenas a configuração de kernel dos consoles, o serviço `r36os-zram`, o arquivo `sysctl` e as verificações automatizadas.
- Manter paridade estrita entre `ga36`, `r36s` e `vm`: o mesmo serviço e os mesmos parâmetros rodam nos três alvos e são validados no `test-vm`.
- Gerar a imagem atualizada do GA36 (`out/ga36/ga36.img` e pacote arquivado em `out/images/ga36/`) pronta para gravação e teste em hardware real.

**Non-Goals:**
- Swap em arquivo ou partição no cartão SD (desgasta o cartão e causa travamentos por I/O lento).
- `zswap` (requer dispositivo de swap de bloco subjacente; usamos `zram` puro em RAM).

## Decisions

### D1. ZRAM e LZ4 embutidos no kernel dos consoles (`=y`) e módulo na VM (`=m`)

- Nos consoles (`board/ga36/kernel.config` e `board/r36s/kernel.config`), habilitamos:
  - `CONFIG_ZSMALLOC=y`
  - `CONFIG_ZRAM=y`
  - `CONFIG_ZRAM_BACKEND_LZ4=y`
  - `CONFIG_ZRAM_DEF_COMP_LZ4=y`
- **Por que `=y` nos consoles:** evita depender de `modprobe` durante o runlevel `boot` e já cria `/dev/zram0` com `lz4` como algoritmo padrão desde a inicialização do kernel.
- **Por que `lz4` em vez de `zstd` ou `lzo-rle`:** no Cortex-A7 de 512 MiB (GA36) e no Cortex-A35 de 1 GiB (R36S), page faults durante a execução de um core não podem competir por ciclos de CPU com o áudio/vídeo. O `lz4` oferece a descompressão mais rápida com razão de compressão ~2,5:1.
- Na VM (`linux-virt`), `CONFIG_ZRAM=m` e `CONFIG_ZRAM_BACKEND_LZ4=y` já vêm prontos no pacote oficial do Alpine; o serviço faz `modprobe zram` se `/dev/zram0` ainda não existir.

### D2. Serviço OpenRC `/etc/init.d/r36os-zram` no runlevel `boot`

- Criado em `rootfs/overlay/etc/init.d/r36os-zram` e habilitado no runlevel `boot` em `rootfs/configure.sh`.
- Sequência no `start()`:
  1. Se `[ ! -b /dev/zram0 ]`, executa `modprobe zram num_devices=1 2>/dev/null || true`.
  2. Se `/dev/zram0` ou `/sys/block/zram0/disksize` não existir, registra aviso via `logger -t r36os-zram` e retorna `0` (nunca derruba o boot).
  3. Se `/sys/block/zram0/comp_algorithm` aceitar `lz4`, grava `echo lz4 > /sys/block/zram0/comp_algorithm`.
  4. Lê `MemTotal` (em KiB) de `/proc/meminfo`, calcula `BYTES=$((KIB * 1024 / 2))` (50% da RAM) e grava em `/sys/block/zram0/disksize`.
  5. Executa `mkswap /dev/zram0 >/dev/null 2>&1` e `swapon -p 32767 /dev/zram0`.
- Baseado diretamente no script validado em `docs/referencia/ga36-emuelec/sistema/zram-swap`, adaptado para OpenRC e para selecionar `lz4`.

### D3. Parâmetros `sysctl` em `/etc/sysctl.d/r36os-zram.conf`

- O serviço `sysctl` do OpenRC já está habilitado no runlevel `boot` (`rootfs/configure.sh`).
- Criamos `rootfs/overlay/etc/sysctl.d/r36os-zram.conf` com:
  ```ini
  # Lume Retro OS: ZRAM tuning for squashfs-on-SD + tmpfs overlay
  vm.swappiness = 100
  vm.page-cluster = 0
  ```
- **Racional de `vm.swappiness = 100`:** no Linux 6.18, `100` atribui peso igual à compressão de páginas anônimas/`tmpfs` em RAM (`zram0`) e ao descarte de cache de arquivos (que no Lume Retro OS exige reler o cartão SD `mmc0` e descomprimir blocos `zstd` do `SYSTEM`). Assim, páginas frias de serviços de boot, da camada `/rw` (`tmpfs` 32 MiB) e de `/run` vão para o ZRAM, preservando o código executável do RetroArch e do core na RAM.
- **Racional de `vm.page-cluster = 0`:** desativa o read-ahead de swap (padrão `3` = 8 páginas = 32 KiB, projetado para discos mecânicos), descomprimindo apenas a página de 4 KiB efetivamente requisitada no page fault.

### D4. Ejeção segura opcional pós-gravação (`r36os flash --eject`)

- Adicionada flag `--eject` em `src/r36os/cli.py` e função `_eject()` em `src/r36os/flash.py`.
- Após a conclusão da escrita e validação SHA256 em `flash()`, se `eject=True`:
  1. Desmonta quaisquer partições do disco eventualmente remontadas pelo desktop environment (`_unmount()`).
  2. Executa `udisksctl power-off -b <device>` para cortar a energia do leitor USB / desacoplar a mídia de forma limpa.
  3. Caso `udisksctl` falhe ou não esteja disponível, executa `eject <device>` como fallback.
- Garante que cartões SD gravados com ou sem `--update` possam ser removidos imediatamente sem risco de dados em cache pendentes ou corrupção de sistema de arquivos.

## Risks / Trade-offs

- **[Consumo de RAM física pelo próprio ZRAM]** → Com `disksize` em 50% de `MemTotal` (256 MiB no GA36) e taxa de compressão média de ~2,5:1, o ZRAM cheio consome ~100 MiB de RAM física para armazenar 256 MiB de páginas frias, gerando ganho líquido de ~156 MiB de memória utilizável sem comprometer o espaço do core ativo.
- **[Recompilação do kernel do GA36]** → Como o diretório de build do kernel em `~/.cache/r36os/kbuild/` e o `ccache` são incrementais (D2/D3 da change principal), ativar `CONFIG_ZSMALLOC` e `CONFIG_ZRAM` recompila apenas os objetos afetados e regenera `zImage`, `SYSTEM` e `ga36.img` em poucos minutos.

## Migration Plan

1. Implementar as opções de kernel, o serviço `r36os-zram`, o `sysctl` e os testes na branch atual.
2. Rodar a suíte de testes unitários e de integração.
3. Executar `uv run r36os build ga36` para gerar a nova imagem `out/ga36/ga36.img` (e o arquivo em `out/images/ga36/<timestamp>/`) pronta para gravar no cartão SD e testar no GA36.
