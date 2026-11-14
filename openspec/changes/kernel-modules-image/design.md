# Design

## Context

Hoje, nos consoles:

- `kernel.build_kernel()` instala os módulos com `INSTALL_MOD_STRIP=1` e os empacota em
  `out/<console>/kernel/modules.tar` (`lib/modules/<release>/...`, `--sort=name`,
  `--numeric-owner`). O `release` fica em `out/<console>/kernel/release`.
- O `_ROOTFS_SCRIPT` de `src/r36os/rootfs.py` extrai esse `modules.tar` no rootfs, e o
  `make_system()` gera o `SYSTEM` (squashfs zstd 19, `-mkfs-time 0 -all-time 0`).
- O `initramfs/init` monta `BOOT/<console>/SYSTEM` por loop em `/lower`, faz o overlay em
  `/newroot`, move a `ROMS` e a `BOOT` para dentro da raiz nova e faz o `switch_root`. No GA36,
  antes disso, o `lume-bootsel` pode recarregar o kernel por kexec (o init roda de novo).
- Os drivers de boot (cartão, FAT, squashfs, loop, overlay) estão embutidos no kernel. Os
  módulos servem ao sistema: `zram` (`r36os-zram`), USB host, Wi-Fi e Bluetooth por dongle.
- Tamanhos medidos (build `20261114-002340`): `modules.tar` do GA36 com 4,2 MB e do R36S com
  77 MB (sem compressão).
- `console_boot_files()` (`src/r36os/image.py`) é a lista única da `BOOT`: a FAT, a
  `boot-files.sha256`, o `flash` e o `push` saem dela. O `check_console_boot()` soma todos os
  arquivos para os 64 MiB livres.

## Goals / Non-Goals

**Goals:**

- Uma mudança só de kernel não muda nenhum `SYSTEM`.
- O console sobe mesmo com a imagem de módulos ausente ou de outro kernel, com o erro no log.

**Non-Goals:**

- Mudar a VM (kernel empacotado do Alpine, módulos no `SYSTEM`).
- Reduzir o conjunto de módulos do R36S.
- Atualização atômica de kernel com módulos (o `push` já troca arquivo por arquivo, com o
  `VERSION` por último).

## Decisions

### D1. Um squashfs por console em `BOOT/<console>/modules`

O arquivo fica ao lado do kernel e do `SYSTEM` do console (`ga36/modules`, `r36s/modules`),
sem extensão, como o `SYSTEM`. Ele tem na raiz a pasta `<release>/` (o conteúdo de
`lib/modules/`), para montar direto em `/lib/modules`.

Alternativas: um tar ou cpio extraído para a camada em RAM no boot (gasta RAM: 77 MB no R36S, e
a camada gravável tem 32 MiB); módulos dentro do initramfs embutido (o kernel cresceria e o GA36
leva o kernel duas vezes no cartão, na `BOOT` e no setor 172032); um squashfs só de kernel e
módulos para os dois consoles juntos (um `push` do GA36 levaria os módulos do R36S).

### D2. Gerado no build do kernel, pelo builder x86_64, reprodutível

`build_console_kernel()` gera `out/<console>/kernel/modules` a partir do `modules.tar`, no
mesmo container x86_64 que roda o `mksquashfs` do `SYSTEM` (ele não depende da arquitetura):
`mksquashfs - <dest> -tar` com o tar reescrito para tirar o prefixo `lib/modules/`, zstd,
`-mkfs-time 0 -all-time 0` e dono root. Mesmo `modules.tar`, mesmo arquivo, como no `SYSTEM`.
O `modules.tar` continua sendo a saída do kernel (cache do kernel e testes leem dele).

Alternativa: gerar o squashfs no container do kernel. O builder do kernel não tem
`squashfs-tools` e precisaria de um pacote novo.

### D3. O `SYSTEM` deixa de extrair o `modules.tar` e ganha `/lib/modules` vazio

O `_ROOTFS_SCRIPT` cria `$R/lib/modules` vazio como ponto de montagem e não extrai mais o
`modules.tar`. O pacote do kernel do Alpine não entra nos consoles, então nada mais escreve em
`/lib/modules` no `SYSTEM` deles. Um teste do rootfs confere que o `SYSTEM` de um console não
tem nada em `lib/modules/`.

### D4. O initramfs monta, confere e move

Depois do overlay em `/newroot` e antes do `switch_root`:

1. monta `BOOT/<console>/modules` por loop, somente leitura, num ponto de espera (`/modules`);
2. lista as pastas na raiz da imagem: precisa haver exatamente uma, igual a `uname -r`;
3. se bater, `mount --move /modules /newroot/lib/modules` e registra `modules: <arquivo>
   (<release>)` no log; se não bater, desmonta e registra `ERROR` com as duas versões; se o
   arquivo faltar ou não montar, registra `ERROR` com o caminho.

O nome do arquivo sai de uma função nova em `initramfs/lib/storage.sh`, ao lado de
`system_file()`, para o teste de shell cobrir a escolha por console. Na VM (`BOARD` vazio ou
`vm`), a função não devolve nada e o passo é pulado.

A montagem fica depois do `select_dtb`: no GA36 o kexec desmonta a `BOOT` antes de recarregar
o kernel, e um loop aberto o impediria.

Alternativa: falhar para a tela de recuperação se os módulos faltarem. Um console sem módulos
ainda abre o RetroArch e roda jogos (perde o `zram`, o USB host e os dongles). A tela de
recuperação num portátil sem teclado não ajuda o usuário, e um `push` interrompido entre o
kernel e os módulos não pode deixar o console sem boot.

### D5. `flash` e `push` sem código novo

`console_boot_files()` ganha `ga36/modules` e `r36s/modules`. A FAT, a `boot-files.sha256`,
o `flash` e o `push` passam a levar o arquivo por essa lista. O `push` troca arquivos com
`.new` + `mv` em ordem de nome e o `VERSION` por último. O kernel e os módulos não são trocados
juntos, e o D4 cobre o intervalo entre os dois. O `modules` em uso fica aberto pelo loop depois
da troca, como o `SYSTEM`, e o `push` já segue quando o `remount,ro` volta `EBUSY`.

## Risks / Trade-offs

- [O loop dos módulos segura a `BOOT`] → é o mesmo caso do `SYSTEM`, já tratado no `push`
  (aviso de que a `BOOT` fica rw até o reboot). O kexec do GA36 acontece antes da montagem
  (D4).
- [Console sem módulos sem ninguém perceber] → a linha `ERROR` do log de boot vai para o
  `events.log`, e o `hwinfo` já mostra "none loaded" em `/proc/modules`.
- [Um módulo carregado antes do `switch_root`] → nenhum hoje: os consoles não carregam
  módulos no initramfs (só a VM). Se um dia carregarem, terão de vir da imagem montada em
  `/modules`.
- [A imagem do R36S passa de ~20 MB] → a `BOOT` não cresce no total (os módulos saem do
  `SYSTEM`), e o `check_console_boot()` já soma todos os arquivos. O tamanho medido vai para o
  build e para os Riscos.
- [Cartões gravados antes desta change] → um `push` ou `flash --update` de um build novo leva o
  `SYSTEM` sem módulos e o arquivo de módulos juntos. Um `SYSTEM` antigo com um initramfs novo
  não acontece: o initramfs está embutido no kernel, que vem do mesmo build.

## Migration Plan

O primeiro `push` depois desta change manda os dois `SYSTEM` (agora sem módulos), os kernels e
os arquivos de módulos. A partir dele, uma mudança só de kernel manda só os arquivos do kernel.
Para voltar atrás, basta um `push` de um build anterior: o kernel antigo não procura o arquivo
de módulos e o `SYSTEM` antigo traz os módulos dentro.
