# Tasks

Roteiro das provas: o mesmo da change `usb-device-access` no GA36. A captura no aparelho é
um script no scratchpad, enviado por MTP (`gio copy ... mtp://.../ROMS/`) e iniciado com
`start-stop-daemon -S -b -x /storage/<script>.sh`. O usuário troca o cabo pelo adaptador, e o
log é lido depois, com o cabo de volta. Os scripts de captura saem da `ROMS` ao fim.

## 1. Papel pelo DTS (tarefa 2.2 da `usb-device-access`)

- [ ] 1.1 R36S: num mesmo boot, 20 s em cada situação (nada ligado, carregador na DC, cabo do PC na OTG, adaptador OTG). Verificação: a linha `usb OK otg:` do `events.log` mostra `not_attached` sem nada e com o carregador, o gadget `configured` com o PC e `USB-HOST=1` com o adaptador, com o papel em `/sys/class/usb_role/*/role` trocado pelo `lume-usb`; tabela anotada no `docs/BRINGUP-R36S.md`.
- [x] 1.3 **Feita em 2026-11-15 (boot 61, build `20261115-145900`: `Image` e `dtbs/rk3326/rk3326-r36s-v5.dtb` copiados ao cartão; só o `Image` no boot 60 não bastou, o DTB carrega a propriedade):** `otg port: no VBUS sensing, kept powered` no log, sem `HANG!` nem `Couldn't set device mode`; `udc` em `configured`, papel `device`; o PC registrou o "Lume R36S" (`1d6b:0104`, `cdc_ncm`) e o `ssh root@10.55.0.1` entrou. Observação: no boot o PC também vê o bootloader da Rockchip (`2207:330d`) duas vezes antes do kernel. Falta a 1.1 (adaptador OTG ainda dando `USB-HOST=1`). **Segunda parte (build `20261115-154529`, boot 62):** com o PC na OTG, ligar o carregador na DC derrubava o gadget de vez: o `utmi_bvalid` sobe com o VBUS da DC, e a máquina de estados rodava a detecção de carregador nas linhas da OTG e desligava o PHY. O patch 0030 passou a ignorar o `bvalid` com `rockchip,vbus-always-on`; provado: carregador na DC e PC na OTG juntos, `rk817-charger` `online=1`, bateria `Charging`, gadget `configured` e SSH respondendo. A porta OTG não carrega o aparelho (`online=0` só com o PC): a carga é só pela DC. R36S: o gadget nunca se conecta ao PC (2026-11-15, boots 58 e 59, imagem do lume-launcher). **Evidência:** `dwc2_core_reset: HANG! Soft Reset timeout GRSTCTL_CSFTRST` e `dwc2_wait_for_mode: Couldn't set device mode` ao ligar o gadget (24 s); depois, `role=…:device`, `udc …:not_attached` e `USB=0` no extcon mesmo com `vbus=rk817-charger:1`; o PC não registra nenhum evento USB. **Causa:** o `phy-rockchip-inno-usb2` desliga o PHY da porta OTG na primeira passada da máquina de estados quando não vê o VBUS (`utmi_bvalid`), e só o religa num host (ID baixo) ou com VBUS; no R36S o VBUS nunca chega ao PHY, então o dwc2 em device fica sem clock do PHY. O host funcionava porque o ID baixo religa o PHY. **Correção:** patches 0029 (binding) e 0030 (driver): `rockchip,vbus-always-on` no `otg-port` (mesmo nome do kernel BSP da Rockchip) mantém o PHY ligado; o DTS do R36S ganha a propriedade e o teste `test_otg_phy_port_stays_powered_without_vbus_sensing`. **Verificação:** com o `Image` e o DTB novos no cartão, o log tem `otg port: no VBUS sensing, kept powered` e não tem `HANG!`, o PC registra o "Lume R36S" (NCM) e `ssh root@10.55.0.1` entra; depois, a 1.1 inteira (o adaptador OTG continua dando `USB-HOST=1`).
- [ ] 1.2 GA36: carregador na DC, a situação que faltou nas provas de 2026-11-13/14. Verificação: nenhuma troca de papel no `events.log` (sem `connected`, sem `USB-HOST=1`), e a carga aparece em `axp20x-usb`; anotado no `docs/BRINGUP-GA36.md`.

## 2. Arquivos, SSH e `push` pelo cabo (tarefas 3.5, 4.4, 5.3 e 6.1)

- [ ] 2.1 R36S, MTP: o GNOME monta o "Lume R36S" ao plugar; cópia por MTP para `ROMS/roms/<sistema>/` com o RetroArch no menu e remoção; desligar o cabo. Verificação: mesmo SHA256 no cartão, RetroArch com o mesmo PID, eventos `usb OK device: connected|disconnected`; seção "Pelo cabo USB" no `docs/BRINGUP-R36S.md`.
- [ ] 2.2 R36S, SSH: `ssh root@10.55.0.1` sem senha e sem chave; `netstat -tuln` com o SSH só em `10.55.0.1:22`; RSS do `umtprd` e do `dropbear`; tempo até o frontend contra os boots do R36S antes do USB. Verificação: login aceito no `events.log`; números anotados no `docs/BRINGUP-R36S.md`.
- [ ] 2.3 R36S, `push`: `lume push` de um build novo, até o reboot. Verificação: o boot seguinte registra a versão nova no `events.log`, sem erro de FAT no log de boot; o `push` seguinte sem mudança manda só o `VERSION`.
- [ ] 2.4 R36S, ciclo completo: `push`, reboot e leitura do `logs/boot/boot-<n>.log` por MTP e por `ssh`, com o mesmo comando no PC usado no GA36. Verificação: os três passos em sequência sem tirar o cartão.

## 3. Papel host (tarefa 7.4)

- [ ] 3.1 R36S com o adaptador OTG, primeiro sem hub: pendrive (montado em `/storage/usb/`, listado em *Carregar conteúdo*, removido), controle USB como jogador 2 e mexendo no menu, teclado e mouse. Verificação: eventos `storage: mounted|removed` e `host_devs` na linha `otg:`; controle do console no jogador 1; se a porta não alimentar, repetir com hub alimentado e registrar como no GA36 (P-54); seção "Adaptador OTG" no `docs/BRINGUP-R36S.md`.

## 4. Dongle Wi-Fi/Bluetooth (tarefa 8.4, parte do reconhecimento)

- [ ] 4.1 Nos dois consoles (GA36 com hub alimentado), ligar o dongle RTL8821CU. Verificação: no log do kernel, o `rtw88_8821cu` e o `btusb` associados e o firmware carregado sem erro; `wlan0` e `hci0` presentes; o menu Wi-Fi do RetroArch lista redes; anotado nos `docs/BRINGUP-*.md`.
- [ ] 4.2 `docs/PENDENCIAS.md`: pendência nova para a prova completa do Wi-Fi e do Bluetooth (rede conectada pelo menu e de volta no boot seguinte, cabo USB e Wi-Fi juntos, controle Bluetooth pareado, UDP 55355 sem resposta de outro aparelho), que exige uma rede e um controle Bluetooth de teste. Verificação: item novo com estado e evidência.

## 5. Módulos do kernel fora do `SYSTEM` (tarefa 3.3 da `kernel-modules-image`)

- [ ] 5.1 R36S: `lume push` de um build da `kernel-modules-image` (o primeiro manda o `r36s/SYSTEM` sem módulos), depois um build com uma mudança só no kernel do R36S (por exemplo `CONFIG_DUMMY=m` temporário no `board/r36s/kernel.config`, retirado depois). Verificação: o segundo `push` manda só `r36s/Image`, `r36s/modules` e o `VERSION`, sem nenhum `SYSTEM`; no console, `/lib/modules/$(uname -r)/modules.dep` existe, o `modprobe` de um módulo da imagem funciona (o `zram` é embutido, `CONFIG_ZRAM=y`) e o log de boot tem `lume: modules: r36s/modules (<versão>)`; tempo e volume do `push` anotados no `docs/BRINGUP-R36S.md`, como no GA36.

## 6. Troca da `BOOT` sem vazamento (tarefa 6.4 da `push-boot-swap`)

- [ ] 6.1 R36S, com o mesmo cartão do GA36 (`BOOT` limpa em 2026-11-14: `df` = `du`, `fsck.fat -n` sem clusters perdidos, e um `ga36/SYSTEM.old` sobrando da prova no GA36): `lume push` de um build que troque o `r36s/SYSTEM` em uso; se o build não trocar o `SYSTEM`, usar um marcador provisório no overlay (`/usr/share/lume/proof-push-boot-swap`), como no GA36, e tirá-lo depois. Verificação: o `push` não mostra aviso de clusters perdidos nem de `remount,ro` recusado; o `r36s/SYSTEM.old` fica na `BOOT` e o `ga36/SYSTEM.old` é apagado antes da cópia; depois do reboot, `df` = `du` da `BOOT` e `fsck.fat -n /dev/mmcblk0p1` pelo console sem clusters perdidos (binário do `dosfstools` do Alpine aarch64 no `/tmp`); anotado no `docs/BRINGUP-R36S.md`, no lugar do "pendente (tarefa 6.4)".

## Workflow follow-up

- Archive desta change depois das provas; se uma falhar, a correção entra como tarefa nova aqui.
