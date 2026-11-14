# Tasks

## 1. Branch

- [x] 1.1 Criar `feature/push-boot-swap` a partir de `feature/boot-dtb-select` (pedido do
  usuário, não da `main`); verificar com `git log --oneline -n 1` que o ponto de partida é o
  HEAD da `feature/boot-dtb-select`.

## 2. Push: troca por `.old` e limpeza (D1, D2, D5)

- [x] 2.1 `src/r36os/push.py`: a sonda do console ignora `*.old` na lista de SHA256 (como
  `*.new`) e devolve o tamanho somado dos `*.old` e `*.new` da `BOOT`; teste em
  `tests/unit/test_push.py` com um `*.old` na sonda falsa, que não entra no `plan_files` nem
  é enviado.
- [x] 2.2 `check_room` soma ao livre da `BOOT` o espaço dos `*.old`/`*.new` que serão
  apagados; a tupla dos arquivos em uso (`<board>/SYSTEM`, `<board>/modules`) fica num só
  lugar, usada pelo espaço e pela troca; teste: uma `BOOT` com livre insuficiente sem
  contar os `.old` e suficiente contando-os passa.
- [x] 2.3 Troca: depois do `remount,rw`, apagar `/boot` `*.old` e `*.new`; para os arquivos
  em uso, `cp` para `.new`, `mv <arq> <arq>.old`, `mv <arq>.new <arq>`, `sync`; os outros
  mantêm o `mv` direto; `VERSION` por último; teste da sequência exata de comandos na
  `Remote` falsa (arquivo em uso, arquivo comum e o `SYSTEM` do outro console, que não vira
  `.old`).
- [x] 2.4 `remount,ro` recusado vira aviso de possível vazamento (D5), o push segue e
  reinicia; atualizar os dois testes atuais da recusa (`test_boot_busy_for_read_only_...` e
  `test_a_failed_swap_is_still_the_error_...`) e o docstring do módulo; suíte
  `tests/unit/test_push.py` passando.

## 3. Push: detecção de clusters perdidos (D3)

- [x] 3.1 A sonda devolve o usado da `BOOT` (`df -Pk /boot`) e o `du -sk /boot`;
  diferença acima de 32 MB mostra o aviso com o tamanho em MiB, a partição da `BOOT`
  (`fsck.vfat -a` + apagar `FSCK*.REC`) e o `r36os flash --update`, sem interromper;
  testes: diferença de 31 MB não avisa, de 290 MB avisa e o push continua.

## 4. Initramfs: reserva `.old` (D4)

- [x] 4.1 `initramfs/lib/storage.sh`: função que devolve o arquivo da `BOOT` ou, sem ele, o
  `<arq>.old` com a linha `ERROR` no log; `initramfs/init` a usa para o `SYSTEM` e o
  `mount_modules` para os módulos (conferência de release mantida); casos em
  `tests/initramfs/test_storage.sh`: arquivo presente, só o `.old`, nenhum dos dois.
- [x] 4.2 Conferir que os testes do layout e do `initramfs` (`tests/unit/test_modules_image.py`
  e a suíte de unidade) continuam passando.

## 5. Documentação

- [x] 5.1 `docs/BRINGUP-GA36.md` e `docs/BRINGUP-R36S.md` (seção do push): a troca com
  `.old`, o aviso de clusters perdidos e as duas formas de recuperar pelo PC; `docs/LOGS.md`
  com a linha `ERROR ... using <arq>.old`; conferir com `rg -n "\.old" docs/`.
- [x] 5.2 `docs/PENDENCIAS.md`: o P-55 aponta para a change `push-boot-swap`.

## 6. Prova no GA36

- [ ] 6.1 Antes: `fsck.vfat -n` da `BOOT` pelo PC sem cadeias perdidas (o cartão foi limpo
  em 2026-11-14) e build `console` com a mudança.
- [ ] 6.2 Dois `push` seguidos que troquem o `SYSTEM` do GA36: depois de cada um, a `BOOT`
  em `ro` no `/proc/mounts` antes do reboot; no segundo, o `ga36/SYSTEM.old` do primeiro
  apagado antes da cópia e sem aviso de clusters perdidos.
- [ ] 6.3 Depois: `fsck.vfat -n` da `BOOT` pelo PC sem cadeias perdidas e `df` contra `du`
  dentro de 32 MB; registrar em `docs/BRINGUP-GA36.md`.
- [ ] 6.4 Primeiro `push` no R36S: registrar se o aviso de clusters perdidos apareceu (os
  pushes antigos podem ter vazado) e, se sim, limpar pelo PC e repetir o push sem aviso.

## Workflow follow-up

- Commits pequenos (Conventional Commits) na `feature/push-boot-swap`, juntos perto do fim,
  com o OK do usuário.
- Arquivar com `/opsx:archive`; o P-55 vai para "Concluídas" com a change.
