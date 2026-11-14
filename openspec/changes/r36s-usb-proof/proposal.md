# Proposal

## Why

A change `usb-device-access` entregou o acesso pelo cabo USB (MTP, rede USB com SSH,
`r36os push`), o papel host (pendrive, controles, teclado) e o Wi-Fi e o Bluetooth por dongle
nos dois consoles. As provas no aparelho foram feitas só no GA36, porque o R36S não estava
disponível em 2026-11-14. Para não segurar o archive dela, as provas do R36S, a do dongle e a
troca de papel com o carregador na DC vêm para esta change.

## What Changes

- Provas no R36S, com o mesmo roteiro usado no GA36:
  - papel pelo DTS nas quatro situações (nada, carregador na DC, PC na OTG, adaptador OTG);
  - MTP com o RetroArch no menu, SSH só pela rede USB, memória e tempo de boot;
  - `r36os push` de um build novo e o ciclo completo sem tirar o cartão;
  - papel host com o adaptador OTG: pendrive, controle USB como jogador 2, teclado e mouse.
- Módulos do kernel fora do `SYSTEM` no R36S (tarefa 3.3 da change `kernel-modules-image`,
  provada só no GA36): o `push` de uma mudança só de kernel sem nenhum `SYSTEM`, e os
  módulos montados e carregáveis no boot.
- No GA36, a situação que faltou: carregador na DC, que não pode virar papel device nem host.
- Dongle Wi-Fi/Bluetooth (RTL8821CU) reconhecido nos dois consoles: driver, firmware e
  interfaces `wlan0`/`hci0`. A prova de rede e de pareamento pelo menu fica para quando houver
  um dongle e uma rede de teste (pendência própria).
- Só correções que as provas pedirem. Nenhum comportamento novo: os requisitos são os dos
  specs `usb-otg`, `wireless` e `system-image` da change `usb-device-access`, e os de
  `system-image` e `boot-runtime` da change `kernel-modules-image`.

## Capabilities

### New Capabilities

Nenhuma.

### Modified Capabilities

Nenhuma (`skip_specs`): esta change só prova no R36S os requisitos já escritos.

## Impact

- **Docs:** `docs/BRINGUP-R36S.md` (seções "Pelo cabo USB" e "Adaptador OTG"),
  `docs/BRINGUP-GA36.md` (carregador na DC), `docs/PENDENCIAS.md`.
- **Código:** só se uma prova falhar; a correção entra como tarefa nova desta change.
- **Depende de:** change `usb-device-access` (arquivada antes ou junto), change
  `kernel-modules-image` (grupo 5) e de o R36S estar disponível.
