# Proposal

## Why

Hoje cada prova no aparelho exige tirar o cartão, ler os logs no PC e regravar a `BOOT` por
um leitor USB que corrompe gravações pequenas (14cd:125d, "USBC" gravado no cartão). Na
change `boot-dtb-select` (boots 21 a 23 do GA36, 2026-11-13) foram três ciclos de cartão só
para descobrir que o kexec não passa do salto. O usuário pediu acesso pelo cabo USB, em modo
de usuário e em modo root, para parar de tirar o cartão (P-48 em `docs/PENDENCIAS.md`).

## What Changes

- **Porta OTG com dois papéis, por projeto:** o GA36 e o R36S têm duas portas USB, uma de
  carga (DC) e uma marcada OTG. A OTG passa a ter um papel definido: **device** quando um PC
  está ligado nela e **host** quando um adaptador OTG está ligado. Esta change mede como cada
  console distingue os dois casos (pino ID, VBUS) e implementa só o papel device. O papel
  host (pendrive, controles, teclado) continua no P-38 e usa a mesma detecção.
- **Gadget USB "Lume" no papel device**, igual nos dois consoles, com duas funções:
  - **arquivos sempre**: a `ROMS` (jogos, BIOS, saves, `logs/`, `system/`) aparece no PC
    por MTP, sem parar o RetroArch e sem senha;
  - **root pelo cabo**: uma rede USB (NCM) com um servidor SSH que aceita o root sem senha
    e sem chave, só nessa rede (revisto em 2026-11-13: a primeira versão exigia uma chave
    pública em `BOOT/ssh/`).
- **Kernel:** gadget por configfs com as funções MTP (FunctionFS), NCM e o controlador da
  OTG em modo dual-role nos dois consoles (no GA36 o configfs hoje está desligado).
- **Userland:** servidor MTP e servidor SSH na lista comum de pacotes, iniciados só quando o
  papel device está ativo; nenhum deles escuta fora da interface USB.
- **Host:** `r36os push` envia um build para o console pelo cabo, confere o SHA256 dos
  arquivos **no próprio console**, só então troca os arquivos da `BOOT` (e, no GA36, a
  imagem de boot do setor 172032, onde fica o kernel) e reinicia.

Fora do escopo: o papel host da porta (P-38); exportar a `ROMS` inteira como disco USB
(mass storage), que exige parar o RetroArch; Wi-Fi e Bluetooth (P-15); acesso ao cartão
pelo bootloader (comando `ums` do U-Boot), que fica como investigação registrada.

## Capabilities

### New Capabilities

- `usb-otg`: a porta OTG dos consoles: detecção do papel (host ou device), o gadget do
  papel device, o acesso aos arquivos por MTP e o acesso root por SSH, sem senha e só pelo
  cabo.

### Modified Capabilities

- `system-image`: o console aceita atualização pelo cabo (`r36os push`), além do
  `flash --update`.

## Impact

- **Kernel:** `board/ga36/kernel.config` e `board/r36s/kernel.config` (configfs, FunctionFS,
  NCM, dual-role); testes de config de kernel dos dois consoles.
- **Device trees:** `board/ga36/dts/sun8i-a33-ga36-mb-v1.2.dtsi` (`usb_otg`, `usbphy`) e
  `board/r36s/dts/rk3326-r36s-v5.dts` (`usb20_otg`, `u2phy`), conforme a medição.
- **Rootfs:** `rootfs/packages.txt` (servidor MTP e SSH), serviço OpenRC novo do gadget em
  `rootfs/overlay/etc/init.d/`, scripts em `rootfs/overlay/usr/libexec/r36os/`, eventos
  novos no `events.log` (`docs/LOGS.md`).
- **Host:** `src/r36os/cli.py` e módulo novo do `push`; `README.md` e `docs/BRINGUP-*.md`.
- **Segurança:** o root não tem senha e entrava só pela serial de debug. Pelo cabo, ele
  passa a entrar também por SSH, sem senha (decisão do usuário, 2026-11-13), e o SSH não
  escuta em outra interface: só quem tem o console e um cabo chega a ele.
- **Pendências:** `docs/PENDENCIAS.md`: o P-48 aponta para esta change; o P-38 passa a
  depender da detecção de papel definida aqui.
