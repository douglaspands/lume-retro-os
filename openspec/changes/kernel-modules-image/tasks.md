# Tasks

## 1. Imagem de módulos e `SYSTEM` sem módulos (D1, D2, D3)

- [x] 1.1 `build_console_kernel()` gera `out/<console>/kernel/modules` a partir do `modules.tar`, no builder x86_64: `mksquashfs -tar` com o prefixo `lib/modules/` tirado, zstd, dono root, `-mkfs-time 0 -all-time 0`. Verificação: teste unitário confere o comando gerado (prefixo tirado, flags de reprodutibilidade); teste de integração gera a imagem duas vezes do mesmo `modules.tar` com o mesmo SHA256 e uma só pasta na raiz, igual ao `release`.
- [x] 1.2 `_ROOTFS_SCRIPT` deixa de extrair o `modules.tar` e cria `/lib/modules` vazio. Verificação: teste unitário do script (sem `modules.tar`, com `mkdir -p $R/lib/modules`); depois de um build, `unsquashfs -l out/<console>/SYSTEM` não lista nada abaixo de `lib/modules/`.
- [x] 1.3 `console_boot_files()` ganha `ga36/modules` e `r36s/modules`. Verificação: os testes da lista da `BOOT` (`test_console_boot.py`, `test_image_console.py`) conferem os dois arquivos na FAT e na `boot-files.sha256`, e o `check_console_boot()` conta os dois; tamanho medido de cada imagem anotado nos Riscos do `design.md`.

## 2. Boot com a imagem de módulos (D4)

- [x] 2.1 `initramfs/lib/storage.sh`: função `modules_file <board>` (`ga36/modules`, `r36s/modules`, nada na VM) e função que confere a pasta de versão da imagem montada contra uma versão dada. Verificação: teste de shell cobre os três consoles, a imagem com uma pasta igual, com versão diferente e com duas pastas.
- [x] 2.2 `initramfs/init`: depois do overlay e antes do `switch_root`, monta a imagem por loop em `/modules`, confere a versão com `uname -r` e faz `mount --move` para `/newroot/lib/modules`; sem arquivo, sem montagem ou com versão diferente, segue sem módulos com uma linha `ERROR` no log. Verificação: teste de shell do init com `mount`/`uname` falsos cobre a montagem certa, o arquivo ausente e a versão diferente, e confere que o passo vem depois do `select_dtb`; boot da VM sem mudança no `events.log`.
- [x] 2.3 `docs/LOGS.md` com a linha `modules:` e os dois erros novos do log de boot. Verificação: as mensagens do documento são as mesmas do `initramfs/init` (teste que procura as mensagens nos dois).

## 3. Prova nos consoles

- [x] 3.1 GA36: `r36os push` do primeiro build desta change (manda os dois `SYSTEM` uma última vez), depois um build com uma mudança só de kernel. Verificação: o segundo `push` manda só `ga36/zImage`, `ga36/modules`, `r36s/Image`, `r36s/modules` e os arquivos de boot que mudaram, sem nenhum `SYSTEM`; no console, `/lib/modules/$(uname -r)/modules.dep` existe, um `modprobe` de um módulo da imagem funciona (o `zram` é embutido nos dois kernels, `CONFIG_ZRAM=y`, e não aparece no `lsmod`), e o log de boot tem a linha `modules:`; tempo e volume do `push` anotados no `docs/BRINGUP-GA36.md`.
- [x] 3.2 GA36: boot com a imagem de módulos removida pelo `ssh` (renomear `ga36/modules` e reiniciar). Verificação: o RetroArch abre, `/lib/modules` vazio, linha `ERROR` no log de boot e no `events.log`; arquivo de volta e boot normal em seguida.
- [x] 3.3 Movida para a change `r36s-usb-proof` (tarefa 5.1, 2026-11-14): o R36S não está em mãos, e as provas dele ficam juntas naquela change. Texto original: R36S: o mesmo da 3.1 quando o R36S estiver disponível. Verificação: `modules.dep` presente, `modprobe` de um módulo da imagem funciona, linha `modules:` no log; anotado no `docs/BRINGUP-R36S.md`.
- [x] 3.4 `README.md` e `docs/PENDENCIAS.md`: o ciclo do `push` com a imagem de módulos no README; o P-53 movido para "Concluídas" com o nome desta change. Verificação: README descreve o que o `push` manda numa mudança só de kernel; P-53 em "Concluídas".

## Workflow follow-up

- Esta change parte do branch `feature/usb-device-access` (precisa do `r36os push` e do build reprodutível); o merge na `main` vem depois do archive da `usb-device-access`.
- Archive depois das provas da 3.1 e da 3.2 no GA36; a do R36S segue na `r36s-usb-proof` (5.1).
