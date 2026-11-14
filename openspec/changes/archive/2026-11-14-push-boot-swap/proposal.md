# Proposal

## Why

Cada `r36os push` que troca o `SYSTEM` do console em uso deixa ~290 MB perdidos na FAT da
`BOOT` (P-55, medido no GA36 em 2026-11-14: 4 cadeias de 283 MB recuperadas pelo
`fsck.vfat`), e cada troca do `<console>/modules` perde mais 1 a 16 MB. Em poucos `push` o
seguinte é recusado por falta de espaço. A causa é o `mv SYSTEM.new SYSTEM`: ele apaga o
`SYSTEM` antigo enquanto o loop da raiz ainda o mantém aberto; a FAT não tem lista de órfãos,
o arquivo nunca é fechado antes do desligamento e seus clusters ficam alocados sem dono. O
mesmo arquivo apagado e aberto é o que faz o kernel recusar o `remount,ro` da `BOOT` depois
do push ("Resource busy"), deixando a `BOOT` gravável e suja até o desligamento.

## What Changes

- **Troca sem apagar o arquivo em uso**: o `SYSTEM` e o `modules` do console que roda o push
  são renomeados para `<arquivo>.old` antes que o novo tome o lugar. Nada aberto é apagado,
  então nenhum cluster se perde e o `remount,ro` da `BOOT` volta a funcionar logo depois da
  troca. Os outros arquivos (kernel, DTBs, o `SYSTEM` do outro console) continuam com a troca
  atual, que não deixa janela sem o arquivo.
- **Espaço devolvido no push seguinte**: depois do reboot nenhum `*.old` está aberto; o push
  seguinte os apaga antes de copiar, e conta esse espaço na verificação da `BOOT`.
- **Detecção de clusters perdidos**: o push compara o espaço usado da `BOOT` (`df`) com o que
  os arquivos ocupam (`du`); acima de 32 MB de diferença, avisa que há clusters perdidos e diz
  como recuperar pelo PC (`fsck.vfat -a` e apagar os `FSCK*.REC`, ou `r36os flash --update`).
  O aviso não bloqueia o push; só a falta de espaço continua bloqueando.
- **Fallback no initramfs**: se um corte de energia cair entre os dois `mv` e a `BOOT` ficar
  sem `<console>/SYSTEM` (ou sem `<console>/modules`), o boot usa o `.old`, que é o build
  anterior íntegro, e registra a linha no log, em vez de cair no `rescue`.

Fora do escopo: `fsck.vfat` no console (alternativa descartada na exploração de 2026-11-14:
exige `dosfstools` no initramfs e uma escrita na `BOOT` a cada boot); recuperar sozinho os
clusters já perdidos nos cartões (a detecção aponta, a limpeza é pelo PC).

## Capabilities

### New Capabilities

Nenhuma.

### Modified Capabilities

- `system-image`: o requisito "Atualização pelo cabo USB" passa a exigir que a troca não
  perca espaço da `BOOT`, que a `BOOT` volte a somente leitura logo depois da troca, que o
  push avise de clusters perdidos e que o boot sobreviva a um corte de energia no meio da
  troca do `SYSTEM`.

## Impact

- **Código**: `src/r36os/push.py` (leitura do console com `df` usado, `du` e os `*.old`;
  `check_room`; a troca; o aviso); `initramfs/lib/storage.sh` (`system_file`/`modules_file`
  com o `.old` como reserva) e `initramfs/init`.
- **Testes**: `tests/unit/test_push.py` (sequência de comandos com `.old`, limpeza no push
  seguinte, espaço, aviso, `remount,ro` aceito); `tests/initramfs/test_storage.sh` (reserva
  `.old`); prova no GA36.
- **Cartões**: os que já têm clusters perdidos precisam de uma limpeza pelo PC, uma vez; o
  push passa a avisar quando for o caso.
- **Documentação**: `docs/BRINGUP-GA36.md` e `docs/BRINGUP-R36S.md` (push e recuperação),
  `docs/PENDENCIAS.md` (P-55 vira esta change).
- **Branch**: `feature/push-boot-swap`, criada a partir de `feature/boot-dtb-select` (pedido
  do usuário), não da `main`.
