# Design

## Context

Motivação em `proposal.md`. Estado atual relevante:

- O initramfs monta `BOOT/<console>/SYSTEM` como loop somente leitura (raiz do overlay) e,
  desde a `kernel-modules-image`, `BOOT/<console>/modules` também como loop. Os dois ficam
  abertos até o desligamento; a `BOOT` vai para `/boot` do sistema, somente leitura.
- O `push` (`src/r36os/push.py`) remonta a `BOOT` gravável e troca cada arquivo com
  `cp <src> <arq>.new && sync && mv <arq>.new <arq> && sync`, `VERSION` por último. O `mv`
  sobre o arquivo em uso o desliga do diretório (`nlink=0`) com o loop ainda aberto.
- No vfat do Linux, um inode com `nlink=0` aberto só libera seus clusters quando é fechado
  (`fat_evict_inode`); a FAT não tem lista de órfãos para terminar isso no boot seguinte.
  Enquanto ele existe, `sb_prepare_remount_readonly` recusa o `remount,ro` com `EBUSY`
  (`s_remove_count`). O loop somente leitura não é escritor e não bloqueia sozinho.
- O desligamento não consegue desmontar a `BOOT` (a raiz depende dela): o inode nunca é
  fechado e seus clusters viram uma cadeia perdida.
- O `r36os flash --update` regrava a partição `BOOT` inteira (`update_regions` em
  `src/r36os/flash.py`), o que também limpa cadeias perdidas e `*.old`.

## Goals / Non-Goals

**Goals:**
- Nenhum `push` perde espaço da `BOOT`, em nenhum dos consoles.
- A `BOOT` volta a somente leitura logo depois da troca e desliga limpa.
- O usuário sabe quando o cartão já tem espaço perdido e como recuperá-lo.

**Non-Goals:**
- Reparar a FAT no console (sem `fsck.vfat` no initramfs).
- Mudar a troca dos arquivos que não ficam abertos (kernel, DTBs, `boot.ini`, `VERSION`,
  o `SYSTEM` do outro console).

## Decisions

### D1. Renomear o arquivo em uso para `.old` em vez de apagá-lo

Para cada arquivo em uso trocado (só `<board>/SYSTEM` e `<board>/modules`, onde `<board>` é
o console lido no início do push):

```
cp  <stage>/<arq>  /boot/<arq>.new ; sync
mv  /boot/<arq>      /boot/<arq>.old      # o inode aberto continua com nome (nlink=1)
mv  /boot/<arq>.new  /boot/<arq>    ; sync
```

Como nada aberto perde o nome, o `s_remove_count` fica em zero: o `remount,ro` passa e a
`BOOT` desmonta limpa no desligamento. Os outros arquivos mantêm o `mv <arq>.new <arq>`
atual, que troca o nome numa operação só e não deixa janela sem o arquivo.

*Alternativas:* (a) `fsck.vfat -a` no initramfs, que remedia em vez de prevenir; descartada
pelo usuário (2026-11-14) por exigir `dosfstools` estático nos dois initramfs e por gravar
na `BOOT` a cada boot com problema; o `-a` ainda salva as cadeias como `FSCK*.REC`, o que
exigiria montar a `BOOT` gravável para apagá-los. (b) Usar o `.old` em todos os arquivos:
mais uniforme, mas abriria uma janela sem kernel ou DTB, que o initramfs não consegue
cobrir, porque quem os lê é o bootloader de fábrica. (c) Voltar para uma ramdisk no
desligamento e soltar a raiz (como o `shutdown` do systemd): resolve na origem, mas é bem
mais complexo para o OpenRC e o initramfs atuais.

### D2. O push seguinte apaga os `*.old` e `*.new` antes de copiar

Depois do reboot, a raiz roda do `SYSTEM` novo, e os `*.old` não estão mais abertos. Com a
`BOOT` já gravável, logo antes da troca, o push apaga todo `*.old` e todo `*.new` da `BOOT`
(um `.new` sobra de um push interrompido e também não está aberto). O apagamento libera os
clusters na hora, porque ninguém mantém esses arquivos abertos.

Na leitura do console, a lista de SHA256 passa a ignorar `*.old`, como já ignora `*.new`, e
a sonda devolve também o tamanho somado desses arquivos. O `check_room` soma esse tamanho ao
espaço livre antes de comparar. A fórmula da necessidade não muda: o maior arquivo, mais o
tamanho dos arquivos em uso, que agora ficam como `.old`.

*Alternativa:* apagar os `.old` no boot seguinte, no initramfs. Exigiria montar a `BOOT`
gravável a cada boot com `.old` e mexeria no initramfs só para isso. Deixá-los até o push
seguinte não custa espaço novo, porque o `check_room` já reservava o tamanho dos arquivos
em uso.

### D3. Detecção de clusters perdidos pela diferença entre `df` e `du`

A sonda do console ganha o espaço usado da `BOOT` (`df -Pk /boot`, coluna "Used") e o que
os arquivos e diretórios ocupam (`du -sk /boot`). No vfat, o `df` conta os clusters de dados
não livres e o `du` arredonda cada arquivo para o tamanho do cluster. Num sistema de arquivos
limpo, os dois praticamente coincidem. Acima de 32 MB de diferença, o push mostra:

```
warning: BOOT has <N> MiB in lost clusters (a SYSTEM replaced by an older push or a power
cut); recover them from the PC: `sudo fsck.vfat -a <part>` and delete BOOT/FSCK*.REC, or
`r36os flash --update`
```

O aviso não interrompe o push. Os 32 MB ficam acima de qualquer imprecisão de contagem e
abaixo do menor vazamento que interessa: o de um `SYSTEM`, de ~290 MB, ou o acúmulo dos
vazamentos de `modules`, de 1 a 16 MB cada.

*Alternativa:* `fsck.vfat -n` no console. Não está disponível (o busybox não traz) e seria
lento demais para cada push.

### D4. Reserva `.old` no initramfs

O `initramfs/lib/storage.sh` ganha uma função que, dado o caminho relativo de um arquivo da
`BOOT`, devolve o próprio arquivo quando ele existe. Quando só existe o `<arq>.old`, ela
devolve o `.old` e registra `ERROR: BOOT has no <arq>; using <arq>.old from the previous
build`. O `init` a usa para o `SYSTEM`, e o `mount_modules` para os módulos. A conferência
de release do `mount_modules` continua valendo: se o kernel já for o novo e só houver o
`modules.old` do kernel antigo, o boot segue sem módulos, com o `ERROR` atual.

A janela coberta é só a que fica entre os dois `mv` do D1, com um corte de energia nesse
intervalo.

### D5. `remount,ro` recusado deixa de ser normal

Hoje a recusa é esperada e só gera uma nota. Com o D1, ela indica que algo ainda segura um
arquivo apagado. O push continua (os arquivos já estão gravados e sincronizados) e troca a
nota por um aviso de que esse boot pode deixar clusters perdidos, para o próximo push
conferir.

## Risks / Trade-offs

- [Corte de energia entre os dois `mv` do D1] → o D4 sobe o build anterior pelo `.old`; o
  próximo push refaz a troca, porque a `VERSION` antiga continua lá.
- [O `.old` ocupa até ~290 MB por console até o push seguinte] → o espaço já era reservado
  pelo `check_room`. Se faltar espaço, o `flash --update` limpa tudo.
- [Cartões que já têm cadeias perdidas (o R36S não foi conferido)] → o D3 avisa no primeiro
  push. A limpeza é manual pelo PC, uma vez.
- [`du` e `df` divergem por outro motivo, como um arquivo aberto e apagado por outro
  processo] → o aviso não bloqueia nada e só sugere a verificação pelo PC.
- [Um build futuro com outros arquivos abertos na `BOOT`] → a lista de arquivos em uso fica
  num só lugar no `push.py` (hoje já existe a tupla `running` do `check_room`), usada pela
  troca e pelo espaço.

## Migration Plan

Não há passo de migração. O primeiro push com a mudança já troca sem vazar. Se o cartão
tiver vazamentos antigos, o aviso do D3 aparece, e a limpeza é feita uma vez pelo PC. Para
desfazer a mudança, basta voltar o `push.py`: os `*.old` que sobrarem não atrapalham o boot
e são apagados pelo `flash --update`.
