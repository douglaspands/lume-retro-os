# Tasks

Roteiro das provas: o mesmo da change `usb-device-access` no GA36. A captura no aparelho é
um script no scratchpad, enviado por MTP (`gio copy ... mtp://.../ROMS/`) e iniciado com
`start-stop-daemon -S -b -x /storage/<script>.sh`. O usuário troca o cabo pelo adaptador, e o
log é lido depois, com o cabo de volta. Os scripts de captura saem da `ROMS` ao fim.

## 1. Papel pelo DTS (tarefa 2.2 da `usb-device-access`)

- [ ] 1.1 R36S: num mesmo boot, 20 s em cada situação (nada ligado, carregador na DC, cabo do PC na OTG, adaptador OTG). Verificação: a linha `usb OK otg:` do `events.log` mostra `not_attached` sem nada e com o carregador, o gadget `configured` com o PC e `USB-HOST=1` com o adaptador, com o papel em `/sys/class/usb_role/*/role` trocado pelo `r36os-usb`; tabela anotada no `docs/BRINGUP-R36S.md`.
- [ ] 1.2 GA36: carregador na DC, a situação que faltou nas provas de 2026-11-13/14. Verificação: nenhuma troca de papel no `events.log` (sem `connected`, sem `USB-HOST=1`), e a carga aparece em `axp20x-usb`; anotado no `docs/BRINGUP-GA36.md`.

## 2. Arquivos, SSH e `push` pelo cabo (tarefas 3.5, 4.4, 5.3 e 6.1)

- [ ] 2.1 R36S, MTP: o GNOME monta o "Lume R36S" ao plugar; cópia por MTP para `ROMS/roms/<sistema>/` com o RetroArch no menu e remoção; desligar o cabo. Verificação: mesmo SHA256 no cartão, RetroArch com o mesmo PID, eventos `usb OK device: connected|disconnected`; seção "Pelo cabo USB" no `docs/BRINGUP-R36S.md`.
- [ ] 2.2 R36S, SSH: `ssh root@10.55.0.1` sem senha e sem chave; `netstat -tuln` com o SSH só em `10.55.0.1:22`; RSS do `umtprd` e do `dropbear`; tempo até o frontend contra os boots do R36S antes do USB. Verificação: login aceito no `events.log`; números anotados no `docs/BRINGUP-R36S.md`.
- [ ] 2.3 R36S, `push`: `r36os push` de um build novo, até o reboot. Verificação: o boot seguinte registra a versão nova no `events.log`, sem erro de FAT no log de boot; o `push` seguinte sem mudança manda só o `VERSION`.
- [ ] 2.4 R36S, ciclo completo: `push`, reboot e leitura do `logs/boot/boot-<n>.log` por MTP e por `ssh`, com o mesmo comando no PC usado no GA36. Verificação: os três passos em sequência sem tirar o cartão.

## 3. Papel host (tarefa 7.4)

- [ ] 3.1 R36S com o adaptador OTG, primeiro sem hub: pendrive (montado em `/storage/usb/`, listado em *Carregar conteúdo*, removido), controle USB como jogador 2 e mexendo no menu, teclado e mouse. Verificação: eventos `storage: mounted|removed` e `host_devs` na linha `otg:`; controle do console no jogador 1; se a porta não alimentar, repetir com hub alimentado e registrar como no GA36 (P-54); seção "Adaptador OTG" no `docs/BRINGUP-R36S.md`.

## 4. Dongle Wi-Fi/Bluetooth (tarefa 8.4, parte do reconhecimento)

- [ ] 4.1 Nos dois consoles (GA36 com hub alimentado), ligar o dongle RTL8821CU. Verificação: no log do kernel, o `rtw88_8821cu` e o `btusb` associados e o firmware carregado sem erro; `wlan0` e `hci0` presentes; o menu Wi-Fi do RetroArch lista redes; anotado nos `docs/BRINGUP-*.md`.
- [ ] 4.2 `docs/PENDENCIAS.md`: pendência nova para a prova completa do Wi-Fi e do Bluetooth (rede conectada pelo menu e de volta no boot seguinte, cabo USB e Wi-Fi juntos, controle Bluetooth pareado, UDP 55355 sem resposta de outro aparelho), que exige uma rede e um controle Bluetooth de teste. Verificação: item novo com estado e evidência.

## Workflow follow-up

- Archive desta change depois das provas; se uma falhar, a correção entra como tarefa nova aqui.
