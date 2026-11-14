# Proposal

## Why

Com o build reprodutível da change `usb-device-access`, o `r36os push` só manda os arquivos da
`BOOT` que mudaram. O resto do peso vem dos módulos do kernel. Eles moram dentro do `SYSTEM` (os
módulos de `modules.tar` vão para `/lib/modules` no build do rootfs), então qualquer mudança de
kernel que mude um módulo reenvia o `SYSTEM` inteiro: 277 MB no GA36 e 295 MB no R36S. Na fase de
bring-up, quase toda iteração é de kernel. O usuário pediu "mais agilidade" no `push` e escolheu
este caminho (P-53 em `docs/PENDENCIAS.md`, 2026-11-14) em vez do delta por blocos.

## What Changes

- **Imagem de módulos por console:** o build de cada console gera, junto com o kernel, um
  squashfs só com os módulos daquele kernel, `BOOT/<console>/modules`. Ele é reprodutível como o
  `SYSTEM`: os mesmos módulos dão o mesmo arquivo.
- **O `SYSTEM` dos consoles deixa de levar os módulos:** ele só muda quando muda um pacote ou o
  overlay. `/lib/modules` fica vazio no `SYSTEM`, como ponto de montagem.
- **Boot:** o initramfs monta `BOOT/<console>/modules` em `/lib/modules` da raiz nova, antes do
  `switch_root`, e confere que a versão dos módulos é a do kernel em execução (`uname -r`). Se o
  arquivo faltar ou a versão não bater, o console sobe sem módulos e registra o erro no log de
  boot com o nome do arquivo e as duas versões. Os drivers de boot estão embutidos no kernel,
  então o sistema sobe e o erro aparece no `events.log`.
- **`flash` e `push`:** levam o arquivo novo pela lista única da `BOOT` (`console_boot_files()`).
  Uma mudança só de kernel passa a mandar o kernel, a imagem de boot do painel 1 no GA36 e a
  imagem de módulos: poucos MB no GA36 e dezenas de MB no R36S.
- **VM:** sem mudança. Ela usa o kernel empacotado do Alpine, com os módulos dentro do `SYSTEM`.

Fora do escopo: diminuir a lista de módulos do R36S (o `defconfig` do arm64 gera ~77 MB de
módulos), o delta por blocos de arquivos grandes, e o `push --only-board`.

## Capabilities

### New Capabilities

Nenhuma.

### Modified Capabilities

- `system-image`: requisito novo: na imagem `console`, os módulos do kernel de cada console
  ficam num arquivo próprio da `BOOT`, fora do `SYSTEM`, e o `SYSTEM` não muda quando só o
  kernel muda.
- `boot-runtime`: requisito novo: o boot monta os módulos do próprio console em `/lib/modules`,
  confere a versão contra o kernel em execução e, se faltar ou não bater, sobe sem módulos com
  um erro no log.

## Impact

- **Build:** `src/r36os/build.py` (`build_console_kernel` gera a imagem de módulos),
  `src/r36os/rootfs.py` (o `_ROOTFS_SCRIPT` deixa de extrair `modules.tar` e cria
  `/lib/modules` vazio), `src/r36os/image.py` (`console_boot_files()` ganha
  `<console>/modules`; o limite da `BOOT` já soma todos os arquivos).
- **Initramfs:** `initramfs/init` e `initramfs/lib/storage.sh` (montagem e conferência da
  versão).
- **Push e flash:** sem código novo, pela lista única da `BOOT`; testes do `push` e da imagem.
- **Testes:** unidade (lista da `BOOT`, rootfs sem módulos, script do initramfs) e integração
  da imagem `console`.
- **Docs:** `docs/LOGS.md` (erro novo no log de boot), `README.md` e `docs/BRINGUP-*.md` (ciclo
  do `push`).
- **Depende de:** change `usb-device-access` (`r36os push` e build reprodutível), ainda não
  arquivada; esta change parte do branch dela.
- **Pendências:** `docs/PENDENCIAS.md`: o P-53 aponta para esta change.
