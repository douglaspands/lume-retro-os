# Tasks

## 1. Configuração de Kernel (GA36 e R36S)

- [x] 1.1 Habilitar `CONFIG_ZSMALLOC=y`, `CONFIG_ZRAM=y`, `CONFIG_ZRAM_BACKEND_LZ4=y` e `CONFIG_ZRAM_DEF_COMP_LZ4=y` em `board/ga36/kernel.config` e atualizar `tests/unit/test_ga36_kernel_config.py`; verificar que `uv run pytest tests/unit/test_ga36_kernel_config.py` passa para o fragmento
- [x] 1.2 Registrar as mesmas opções (`CONFIG_ZSMALLOC=y`, `CONFIG_ZRAM=y`, `CONFIG_ZRAM_BACKEND_LZ4=y`, `CONFIG_ZRAM_DEF_COMP_LZ4=y`) em `board/r36s/kernel.config` (ou no teste/requisito correspondente do R36S) para garantir que o kernel do R36S suba com ZRAM + LZ4 embutidos; verificar com teste unitário

## 2. Serviço OpenRC e Parâmetros sysctl

- [x] 2.1 Criar `rootfs/overlay/usr/libexec/r36os/zram` e o serviço `rootfs/overlay/etc/init.d/r36os-zram` (carrega `modprobe zram` se necessário, seleciona `lz4`, configura `disksize` em 50% de `MemTotal`, roda `mkswap` e `swapon -p 32767 /dev/zram0` sem falhar o boot se ausente) e adicioná-lo ao runlevel `boot` em `rootfs/configure.sh`; verificar permissões em `tests/unit/test_overlay_modes.py` e a lógica de cálculo/fallback com teste automatizado
- [x] 2.2 Criar `rootfs/overlay/etc/sysctl.d/r36os-zram.conf` com `vm.swappiness = 100` e `vm.page-cluster = 0`; verificar com teste unitário a presença dos parâmetros e a ativação de `r36os-zram` e `sysctl` no runlevel `boot`

## 3. Validação e Geração da Imagem do GA36

- [x] 3.1 Adicionar checagem `zram-swap` ao `rootfs/overlay/usr/libexec/r36os/selftest` e `src/r36os/selftest.py` (confirmando `/dev/zram0` ativo em `/proc/swaps` com prioridade `32767`, `swappiness=100` e `page-cluster=0`); verificar que a suíte de testes (`uv run pytest -m "not slow"`) passa integralmente
- [x] 3.2 Gerar a imagem do GA36 (`uv run r36os build ga36`) na branch atual e verificar que `out/ga36/kernel/config` contém `CONFIG_ZRAM=y` e `CONFIG_ZRAM_DEF_COMP_LZ4=y`, que `tests/unit/test_ga36_kernel_config.py` (incluindo `test_built_config`) passa e que `out/ga36/ga36.img` e o pacote em `out/images/ga36/latest/` foram gerados e verificados por SHA256

## 4. Ejeção Segura pós-Flash no CLI

- [x] 4.1 Adicionar suporte a `--eject` em `src/r36os/flash.py` e `src/r36os/cli.py` (executando desmonte prévio e `udisksctl power-off` com fallback para `eject`) e cobrir com testes unitários em `tests/unit/test_flash.py`

