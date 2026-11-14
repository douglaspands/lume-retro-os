# Tasks

## 1. Medição da porta OTG antes do DTS (D1)

- [x] 1.1 `logd`: amostra da porta OTG a cada intervalo de métricas (nível do pino ID, VBUS visto pelo PHY, papel do controlador em `/sys` e `/sys/class/udc/*/state` quando houver), gravada como linhas `usb:` no `trace` e como evento só na mudança; descrito em `docs/LOGS.md`. Verificação: teste de shell do `logd` com um `/sys` falso cobrindo as quatro situações; a linha aparece no log de boot da VM sem erro.
- [x] 1.2 Prova nos dois consoles com o build da 1.1: num mesmo boot, deixar 20 s em cada situação (nada ligado, carregador na DC, cabo do PC na OTG, adaptador OTG com pendrive na OTG), anotando a ordem. Verificação: tabela situação → ID, VBUS e papel de cada console anotada no Context do `design.md`, com a decisão do D1 (troca automática ou papel padrão device) registrada nele.
- [x] 1.3 GA36: procurar o comando `ums` no U-Boot 2017 de fábrica (strings do binário da área de fábrica `R36OS_GA36_FACTORY`, sem gravar nada). Verificação: resultado anotado nas Open Questions do `design.md`; se existir, pendência nova no `docs/PENDENCIAS.md`.

## 2. Kernel e device trees

- [x] 2.1 `board/ga36/kernel.config` e `board/r36s/kernel.config`: `USB_CONFIGFS`, `USB_CONFIGFS_F_FS`, `USB_CONFIGFS_NCM` embutidos (`=y`) e o controlador da OTG em dual-role nos dois. Verificação: testes de config de kernel dos dois consoles cobrem as opções e passam; o `.config` gerado pelo `r36os build` as tem.
- [ ] 2.2 DTS dos dois consoles conforme a decisão da 1.2 (`dr_mode`, ID e VBUS no `usbphy` do GA36; `usb20_otg`/`u2phy` no R36S, com `usb-role-switch` se a troca for explícita). Verificação: testes de DTS (`dt-validate` do build) passam; no aparelho, o log mostra o papel certo nas quatro situações da 1.2.

## 3. Gadget USB e arquivos por MTP (D2, D3)

- [x] 3.1 `rootfs/packages.txt`: `umtprd`, `dropbear`, `dropbear-convert` (sem `dropbear-openrc`: o serviço é o `r36os-usb`). Verificação: `tests/unit/test_manifest_parity.py` passa com os manifestos novos dos três sistemas; o tamanho de cada `SYSTEM` continua dentro do limite do `system-image`.
- [x] 3.2 `rootfs/overlay/usr/libexec/r36os/usb-gadget`: monta o gadget "Lume" no configfs (VID/PID `1d6b:0104`, nome "Lume GA36"/"Lume R36S", serial), com `ffs.mtp` e `ncm.usb0`, e liga o `UDC` só depois do `umtprd` pronto; `stop` desfaz tudo. Verificação: teste de shell com um configfs falso confere a árvore criada, a ordem (`umtprd` antes do `UDC`) e o `stop` limpo.
- [x] 3.3 Configuração do `umtprd`: um armazenamento "ROMS" em `/storage`, com uid/gid do `game`, sem acesso à `BOOT`. Verificação: teste unitário do arquivo de configuração gerado (caminho, uid, nenhum caminho fora de `/storage`).
- [x] 3.4 Serviço OpenRC `r36os-usb` (`rootfs/overlay/etc/init.d/`), depois do `localmount` e do `r36os-logd`, antes do `frontend`; na VM ele não faz nada (sem `UDC`). No R36S (role switch do D1), ele acompanha o `USB-HOST` do `extcon` do `u2phy` e escreve `host`/`device` em `/sys/class/usb_role/*/role`, mantendo o host automático que já funciona hoje (acréscimo aprovado em 2026-11-13). Verificação: teste do serviço (dependências, saída imediata sem `UDC`, troca de papel com um `/sys` falso); boot da VM sem erro nem atraso no `events.log`.
- [ ] 3.5 Prova no GA36 e no R36S: ligar o cabo com o RetroArch no menu, copiar um arquivo para `ROMS/roms/<sistema>/`, abrir `logs/` no PC e desligar o cabo. Verificação: arquivo com o mesmo SHA256 no cartão, RetroArch rodando, eventos `usb OK device: connected|disconnected` no `events.log`; `docs/BRINGUP-GA36.md` e `docs/BRINGUP-R36S.md` com a seção "Pelo cabo USB".

## 4. Rede USB e root pelo cabo (D4, D5)

- [x] 4.1 `usb-gadget`: quando a `usb0` sobe, endereço `10.55.0.1/30`, `udhcpd` entregando só `10.55.0.2` sem roteador nem DNS; quando cai, para os dois. Verificação: teste de shell confere a configuração do `udhcpd` (um endereço, sem `router`/`dns`) e o ciclo sobe/cai.
- [x] 4.2 `dropbear` sempre que a rede USB sobe, root sem senha (D4 revisto em 2026-11-13): `-R -B -j -k -p 10.55.0.1:22`, chave de host gerada na RAM a cada boot; login aceito e recusado viram eventos `usb`. Verificação: teste de shell cobre os argumentos do `dropbear`, os eventos com as linhas reais do dropbear 2026.91 (medidas no Alpine) e o ciclo sobe/cai.
- [x] 4.3 Sem chave no cartão (D4 revisto em 2026-11-13, pedido do usuário): sai o `r36os flash --ssh-key` e a `BOOT/ssh/` da primeira versão; o `push` entra como root sem senha, sem conferir a chave de host (nova a cada boot) e sem tocar no `known_hosts` do usuário. Verificação: testes unitários do `push` (opções do `ssh`, sem `-i`) e do serviço (argumentos do `dropbear`, `passwd -d root`, sem `dropbear-convert`); `README.md` com o uso.
- [ ] 4.4 Prova nos dois consoles: `ssh root@10.55.0.1` pelo cabo, sem senha e sem chave; conferir que o SSH não responde fora da rede USB; medir a memória usada pelo `umtprd`/`dropbear` e o tempo de boot até o frontend contra o build anterior. Verificação: login aceito, eventos no `events.log`; custo anotado nos Riscos do `design.md`.

## 5. Atualização pelo cabo: `r36os push` (D6)

- [x] 5.1 Lista de arquivos da `BOOT` de um build tirada do mesmo módulo que monta a FAT (`src/r36os/image.py`), usada pelo `flash` e pelo `push`. Verificação: teste unitário confere que a lista é igual ao conteúdo da FAT de um build de teste.
- [x] 5.2 `src/r36os/push.py` e `r36os push [build]` na CLI: leitura do console (`VERSION`, placa, bateria, espaço livre na `ROMS` e na `BOOT`), `rsync` para `/storage/.lume-push/<build>/`, `sha256sum -c` no console, troca por `.new` + `mv` com `VERSION` por último, imagem de boot do painel 1 no setor 172032 só no GA36 e só se mudou (com leitura de volta), `remount,ro`, limpeza e reboot. Verificação: testes unitários com um executor SSH falso cobrem a ordem dos passos e cada recusa (SHA256 diferente, sem espaço, bateria abaixo de 20%; o console fora do cabo é o erro do `ssh`).
- [ ] 5.3 Prova nos dois consoles: `r36os push` de um build novo e, no GA36, de um build com kernel novo. Verificação: o próximo boot registra a versão nova no `events.log`; no GA36, `Linux version` do log de boot é o do build enviado; a troca do `SYSTEM` em uso não gera erro de FAT no log (risco do `design.md`); `README.md` e `docs/BRINGUP-*.md` com o ciclo `push`.

## 6. Integração

- [ ] 6.1 Ciclo completo sem tirar o cartão, nos dois consoles: `push` de um build, reboot, ler `logs/boot/boot-<n>.log` por MTP e por `ssh`. Verificação: os três passos funcionam em sequência nos dois aparelhos com o mesmo comando no PC.
- [ ] 6.2 `docs/PENDENCIAS.md`: P-48 aponta para esta change e, ao concluir, vai para "Concluídas"; o P-38 registra que usa a detecção de papel do D1. Verificação: os dois itens atualizados.

## Workflow follow-up

- Voltar à `boot-dtb-select` (diagnóstico do kexec no GA36, boots 21 a 23) usando o `push`.
  Antes, religar a pergunta "press A" na tela (D10): `LUME_CONFIRM` volta a `1` em
  `aports/lume-bootsel/lume-bootsel.c` (desligada para as provas desta change, pedido de
  2026-11-13), com o `test_the_package_builds_without_the_question` removido.
- Arquivar com `/opsx:archive` depois das provas nos dois aparelhos.
