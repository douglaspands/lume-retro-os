# Lume Retro OS

Distro mínima baseada em **Alpine Linux** com **RetroArch** para consoles portáteis. O build
gera duas imagens:

- **`console`**: um único cartão que inicia no GA36 e no R36S, sem regravar. Os dois
  consoles usam a mesma `ROMS` (jogos, saves e configuração), e cada um sobe o próprio
  sistema (camada de hardware);
- **`vm`**: a VM de teste.

| Camada | Imagem | Aparelho | SoC | Estado |
|---|---|---|---|---|
| `ga36` | `console` | GA36-MB V1.2 (clone do R36S) | Allwinner A33, armv7 | validado no aparelho ([guia](docs/BRINGUP-GA36.md)) |
| `r36s` | `console` | R36S "V5" | Rockchip RK3326, aarch64 | em desenvolvimento (change `r36s-single-card`, [guia](docs/BRINGUP-R36S.md)) |
| `vm` | `vm` | VM de teste (QEMU/KVM) | x86_64 | testada automaticamente a cada build |

O sistema sobe direto no menu do RetroArch (Ozone), sem login, com a raiz somente leitura
(`SYSTEM` em squashfs) e uma partição de jogos `ROMS` em exFAT, criada pelo `r36os flash` (ou
no primeiro boot, se faltar) e legível em qualquer PC. `r36os` é o nome interno do orquestrador, dos pacotes e dos serviços.

## Requisitos

- Linux com `podman` (rootless) e [`uv`](https://docs.astral.sh/uv/); Python 3.14 via `uv`;
- para a imagem `console`, `qemu-user` registrado no binfmt para armv7 e aarch64 (os pacotes
  das duas camadas são compilados sob emulação);
- espaço em disco: cerca de 17 GB para o cache em `.cache/` e mais os artefatos em `out/`
  (veja abaixo).

Tudo roda em containers: kernel e U-Boot em cross (Debian), pacotes e rootfs em Alpine.

**Ambiente Python (`.venv/`).** O orquestrador e os testes rodam no venv do repositório,
criado e mantido pelo `uv` a partir do `pyproject.toml` (fora do git pelo `.gitignore`):

```sh
uv sync                 # cria o .venv (Python 3.14) e instala o r36os e o pytest
uv run r36os --help     # ou .venv/bin/r36os
uv run pytest           # testes unitários (tests/unit)
```

Nada usa o Python global da máquina.

**Cache do build (`.cache/`).** Fica na raiz do projeto, ignorado pelo git, e guarda o que
o build baixa e compila entre uma execução e outra: fontes e árvores de build do kernel e do
U-Boot (`src/`, `kbuild/`, `ubuild/`), `ccache/`, `distfiles/`, as chaves de assinatura do
abuild (`abuild/`), as áreas de boot de fábrica (`vendor/`), a imagem descomprimida do
`flash` (`flash/`) e o disco da VM (`vm/`). Cerca de 17 GB com as camadas compiladas;
`uv run r36os clean` remove o que um build refaz sozinho.

- No Btrfs, o build cria o `.cache/` como No-COW (`chattr +C`), o que evita a fragmentação
  das árvores de build e do disco da VM. Em ext4, xfs e outros, ele avisa numa linha e segue.
- Para guardar o cache em outro lugar, exporte `R36OS_CACHE=/outro/lugar`.
- Uma git worktree (por exemplo, `out/worktrees/<nome>`) usa o `.cache/` do repositório
  principal, sem recompilar o kernel.
- Exclua o `.cache/` (e o `out/`) do file watcher da IDE: são milhões de arquivos.
- **`git clean -fdx` apaga o `.cache/` inteiro**, incluindo as chaves do abuild. Tudo volta
  com um build, mas as chaves novas exigem recompilar os pacotes de `out/repo`. Prefira
  `git clean -fd` (sem `-x`) ou `uv run r36os clean`.

**Bootloaders dos aparelhos.** Cada console sobe pelo bootloader do próprio fabricante, que
é binário fechado e não está no repositório:

- GA36: boot0 e U-Boot da Allwinner, nos primeiros 128 MiB do cartão original;
- R36S: `idbloader`, `uboot.img` e `trust.img` da Rockchip, nos primeiros 16 MiB do cartão
  original.

Na primeira vez, faça uma cópia do cartão que veio com cada aparelho e aponte as variáveis
para elas. O build extrai as áreas de boot para o cache (`.cache/vendor/`), confere
o SHA256 e, daí em diante, não precisa mais das variáveis. A cópia do R36S pode ser a
imagem inteira do cartão, crua ou comprimida (`.img.zst`):

```sh
sudo dd if=/dev/sdX of=ga36-boot-area.img bs=1M count=128   # cartão original do GA36
sudo dd if=/dev/sdY of=r36s-card.img bs=1M count=16          # cartão original do R36S
R36OS_GA36_FACTORY=ga36-boot-area.img R36OS_R36S_FACTORY=r36s-card.img uv run r36os build console
```

Só os cartões de fábrica medidos são aceitos (o SHA256 de outro cartão é recusado com uma
mensagem que explica o motivo).

### Cache de versões anteriores

Até esta versão, o cache ficava em `~/.cache/r36os` (ou `$XDG_CACHE_HOME/r36os`), que o
build não usa mais. Para aproveitá-lo sem recompilar tudo, mova-o uma vez, com nenhum build
rodando (`podman ps` vazio), a partir da raiz do projeto:

```sh
uv run r36os clean                  # confira a lista
uv run r36os clean --yes            # remove as árvores kbuild/ de conjuntos de patches antigos
stat -c %d ~/.cache/r36os/ .        # o mesmo número: o mv só troca nomes, sem copiar dados
mkdir .cache
chattr +C .cache                    # só no Btrfs
mv ~/.cache/r36os/src .cache/       # repita para cada pasta de primeiro nível do cache antigo
rmdir ~/.cache/r36os                # falha se sobrar algo
uv run r36os build vm               # reaproveita fontes e ccache, sem baixar o kernel de novo
lsattr -d .cache                    # mostra o atributo C (No-COW)
```

Se o `stat` mostrar números diferentes, o `mv` vira uma cópia completa: confira o espaço
livre antes. Se o `~/.cache/r36os` for um symlink, use o caminho real dele no `stat` e no
`mv`, e no fim remova o symlink (`rm ~/.cache/r36os`) e a pasta vazia de destino (`rmdir`).
Para voltar atrás, mova as pastas de volta ou exporte `R36OS_CACHE` com o caminho antigo.

## Uso rápido

```sh
uv run r36os build vm              # gera a imagem da VM
uv run r36os vm                    # roda a VM em janela (--headless: serial no terminal)
uv run r36os test-vm               # teste de aceitação completo da VM

uv run r36os build console         # gera o cartão único do GA36 e do R36S (as duas camadas, uma depois da outra)
uv run r36os build console --lang pt_BR   # idioma de fábrica do menu (padrão: en)
uv run r36os build --all           # vm, test-vm e depois console (só liberada se a vm passar)

uv run r36os pkg r36s retroarch    # recompila um pacote de aports/ para uma camada (ga36, r36s, vm)
```

Idiomas aceitos em `--lang`: `en` (padrão), `pt_BR`, `pt_PT`, `es`, `fr`, `de`, `it`.
O usuário pode trocar o idioma no menu do RetroArch, e a escolha é guardada no cartão.

## Versões das imagens

Cada build recebe um timestamp (`AAAAMMDD-HHMMSS`) e é guardado em
`out/images/<imagem>/<timestamp>/`:

```
out/images/console/20261109-214233/
  console-20261109-214233.img.zst  imagem do cartão (zstd)
  manifest-ga36.txt                pacotes e versões de cada sistema
  manifest-r36s.txt                (na vm, um manifest.txt só)
  build.json                       commit, idioma, Alpine, tamanhos, cada camada (kernel,
                                   patches, tamanho do SYSTEM) e os bootloaders de fábrica
  SHA256SUMS
out/images/console/latest -> 20261109-214233
```

O mesmo timestamp está em `BOOT/VERSION` (no PC) e em `/etc/os-release` (`BUILD_ID`) dos dois
sistemas.

## Gravar o cartão

Rode num terminal (a escrita usa `sudo`, que pede a senha):

```sh
uv run r36os flash console /dev/sdX --full     # cartão todo (o padrão): imagem + ROMS no resto
uv run r36os flash console /dev/sdX            # o mesmo que --full
uv run r36os flash console /dev/sdX --update   # atualização: preserva jogos, saves e configurações
uv run r36os flash console /dev/sdX --build 20261109-214233   # um build específico
uv run r36os eject /dev/sdX                    # ejetar com segurança (sync, desmonta e desliga)
```

- O comando só aceita discos removíveis, desmonta as partições, pede para digitar o nome
  do dispositivo como confirmação e, no fim, lê de volta e confere o SHA256.
- A gravação completa cria também a `ROMS` (exFAT) com todo o espaço que sobra do cartão,
  as pastas padrão (`roms/<sistema>` de cada sistema do catálogo, `bios`, `saves`, `states`,
  `screenshots`, `system`) e a configuração de fábrica do RetroArch, no idioma do build.
  Dá para copiar os jogos logo depois, antes do primeiro boot. No fim, o `fsck.exfat -n`
  confere a partição criada.
- `--update` grava só a área de boot e a partição `BOOT`; a tabela de partições e a `ROMS`
  não são tocadas. Ele recusa cartões com outro layout (por exemplo, um cartão da `vm` ou
  um com o layout antigo, em que a `BOOT` começava em 16 MiB) e pede a gravação completa.
- **Cartão do GA36 gravado antes da imagem `console`:** a `BOOT` dele tem 1 GiB e a da
  `console` tem 2 GiB, então o `--update` recusa e pede a gravação completa, que apaga a
  `ROMS`. Copie `roms/`, `bios/`, `saves/` e `states/` para o PC antes, grave com
  `flash console /dev/sdX` e devolva os arquivos. As atualizações seguintes podem usar
  `--update`.
- O cartão precisa ter pelo menos 4 GB (a `BOOT` ocupa 2 GiB depois dos 128 MiB iniciais).
- Para descobrir o dispositivo: `lsblk -o NAME,SIZE,TRAN,RM,MODEL,LABEL`.
- Rode o `r36os flash` como seu usuário, **sem** `sudo` na frente: ele chama o `sudo` só
  para gravar e ler o cartão. Com `sudo` na frente, os arquivos de cache ficam com o root.

## Pelo cabo USB

Ligue o console ao PC pela porta **OTG** (não a de carga), sem adaptador. O console aparece
como "Lume GA36" ou "Lume R36S" e oferece duas coisas:

- **Arquivos (MTP):** a `ROMS` (jogos, BIOS, saves, `logs/`, `system/`) aparece no
  gerenciador de arquivos do PC, com o RetroArch rodando. A `BOOT` não aparece.
- **Rede USB e root:** o PC recebe `10.55.0.2` por DHCP, sem rota nem DNS (a internet do PC
  não muda), e o console fica em `10.55.0.1`. O root entra **sem senha**:

  ```sh
  ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null root@10.55.0.1
  ```

  As duas opções evitam o aviso de chave trocada, porque o console gera uma chave de host
  nova a cada boot. Comandos do dia a dia (bateria, logs, reiniciar o USB, copiar arquivos
  sem MTP) e o que fazer quando o MTP não monta: "Guia rápido pelo cabo" em
  `docs/BRINGUP-GA36.md`. O SSH só escuta na rede do cabo: só quem tem o console e um cabo chega
  a ele, e essa pessoa já pode tirar o cartão.

### Atualizar pelo cabo USB (`r36os push`)

Com o console ligado no PC pela porta OTG:

```sh
uv run r36os push                          # o build mais recente (out/images/console/latest)
uv run r36os push --build 20261114-100000  # um build específico
```

1. Lê o console: build atual, placa, bateria, espaço livre e espaço perdido na `BOOT`.
2. Separa os arquivos da `BOOT` do build que diferem dos do console.
3. Envia esses arquivos para `/storage/.lume-push/` (na `ROMS`) e confere o SHA256 **no
   próprio console**. Se algum arquivo diferir, a `BOOT` não é tocada.
4. Apaga os `*.old` e `*.new` deixados pelo `push` anterior e troca os arquivos na `BOOT`
   um a um (`.new` e depois renomeia), com o `VERSION` por último. O `SYSTEM` e o `modules`
   do console que está rodando continuam abertos pelo sistema: o antigo é renomeado para
   `<arquivo>.old` em vez de apagado, e fica na `BOOT` até o `push` seguinte. No GA36, grava
   também a imagem de boot do painel 1 no setor 172032, só se ela mudou, e confere lendo
   de volta.
5. Remonta a `BOOT` só leitura, apaga a pasta temporária e reinicia o console.

- Os módulos do kernel de cada console ficam fora do `SYSTEM`, em `ga36/modules` e
  `r36s/modules` na `BOOT`, e o build é reprodutível. Uma mudança só de kernel manda o
  kernel e a imagem de módulos de cada console (`ga36/zImage`, `ga36/modules`, `r36s/Image`,
  `r36s/modules`), a imagem de boot do painel 1 no GA36 e o `VERSION`, sem nenhum `SYSTEM`.
  O `SYSTEM` só volta a ser enviado quando muda um pacote ou o overlay.
- O comando recusa com a bateria abaixo de 20% e sem espaço livre na `ROMS` ou na `BOOT`.
- Um `push` interrompido deixa o `VERSION` antigo, e o próximo `push` reenvia tudo. Se a
  energia cair bem no meio da troca do `SYSTEM` (ou do `modules`), o console sobe com o
  `<arquivo>.old`, o build anterior, e registra uma linha `ERROR` no log de boot. Se o
  console não iniciar, `r36os flash --update` pelo leitor continua sendo a recuperação.
- **Clusters perdidos:** quando o espaço usado da `BOOT` passa em mais de 32 MB o que os
  arquivos ocupam, o `push` avisa (`warning: BOOT has <N> MiB in lost clusters`) e segue.
  Isso sobra de cartões atualizados por versões antigas do `push`, que vazavam ~290 MB por
  troca do `SYSTEM`, ou de um corte de energia. Para recuperar, com o cartão no leitor do
  PC: `sudo fsck.vfat -a /dev/sdX1` (a `BOOT` é a partição 1) e apague os `FSCK*.REC` que
  ele cria na raiz da `BOOT`; ou regrave com `r36os flash --update`.
- Os arquivos do MTP e o `push` usam o mesmo cabo: dá para ler `logs/` pelo gerenciador de
  arquivos do PC antes e depois.

## O cartão

| Região | Conteúdo |
|---|---|
| início do cartão | bootloaders. Na `console`: os 128 MiB com as cadeias de fábrica dos dois consoles (boot0 do GA36 encolhido para 24 KiB, `idbloader`, `uboot.img` e `trust.img` do R36S, U-Boot do GA36) e o nosso kernel do GA36 no setor 172032. Na `vm`: SYSLINUX nos primeiros 16 MiB |
| `BOOT` (FAT32, 2 GiB na `console`, 1 GiB na `vm`) | `VERSION`. Na `console`, só o que os consoles leem: `boot.ini`, `logo.bmp` e os dois DTBs do RG351 (lidos pelo U-Boot do R36S), `dtbs/a33/` e `dtbs/rk3326/` (os DTBs de cada SoC), `ga36/` (`SYSTEM` e kernel) e `r36s/` (`SYSTEM` e kernel). Na `vm`: `SYSTEM`, kernel, initramfs e `extlinux/` |
| `ROMS` (exFAT, resto do cartão) | `roms/<sistema>/`, `bios/`, `saves/`, `states/`, `system/` (configurações), `logs/`, `LEIA-ME.txt`: a mesma nos dois consoles |

- Os jogos vão em `ROMS/roms/<sistema>/` pelo PC; as listas são geradas no boot.
- **Restaurar a configuração de fábrica:** apagar a pasta `ROMS/system/`.
- **Logs** (sempre em inglês): `ROMS/logs/`. Formato em [docs/LOGS.md](docs/LOGS.md).
- **GA36, painel:** há duas variantes de tela; a imagem usa a 1 (a do firmware de fábrica).
  Para a 2, escreva `ga36-panel2` em `BOOT/dtbs/force` (ver "Escolha do device tree"
  abaixo). A imagem de boot de cada painel também fica na pasta do build
  (`out/images/console/<build>/ga36-android-boot-panel{1,2}.img`), para gravar à mão no
  setor 172032 se preciso (ver `docs/BRINGUP-GA36.md`).
- **Trocar de console:** basta passar o cartão de um aparelho para o outro. Os saves
  (`.srm`) passam entre eles; os *save states* podem não passar, porque o GA36 é armv7 e o
  R36S é aarch64.
- **Leitor de cartão:** o leitor USB `14cd:125d` ("Mass Storage Device") corrompe o cartão em
  gravações pequenas: grava o próprio comando USB (assinatura `USBC`) no lugar dos dados,
  como no primeiro setor da `ROMS` ou no FSINFO da `BOOT`. O `r36os flash` avisa quando
  identifica esse leitor, e o boot registra a causa quando acha a `ROMS` com essa
  assinatura. Use outro leitor; um cartão afetado se recupera com `fsck.exfat` ou
  gravando de novo com `--full`.

### Escolha do device tree

O device tree (DTB) diz ao kernel como é o hardware do aparelho: painel, botões, som,
bateria. A `BOOT` traz os de cada SoC em `dtbs/a33/` (GA36: `ga36-panel1`, o padrão, e
`ga36-panel2`) e `dtbs/rk3326/` (R36S: `r36s-v5`, o padrão, mais os convertidos de
`vendor/`, ver abaixo). O bootloader de fábrica sempre inicia com o padrão; logo no começo
do boot o sistema confere se ele serve e, se outro foi escolhido, troca: no R36S o kernel
reinicia com o outro DTB (kexec, poucos segundos a mais), no GA36 a imagem de boot é
regravada com ele e o console reinicia uma vez.

**Sozinho (o normal):** nada a fazer. O sistema lê o ID que o painel responde e:

- usa o DTB cuja regra bate com esse ID (o R36S V5 é reconhecido assim);
- usa o que já aprendeu antes para esse ID;
- se o painel respondeu ao DTB em uso, fica com ele e o aprende;
- se o painel não respondeu (tela preta), testa os outros DTBs do SoC, um por boot, e
  aprende o primeiro com que o painel responde.

**Pelo PC, `BOOT/dtbs/force`:** um arquivo de texto com o nome de um DTB (o `lume,id`,
igual ao nome do arquivo de um convertido, sem `.dtb`), por exemplo `ga36-panel2`. Use
quando a tela fica preta e você sabe qual é a placa, ou para testar um convertido. Ele vale
enquanto o arquivo existir; apague-o para voltar à escolha automática. Um nome inválido é
ignorado e registrado no log.

**Pela lista:** ligue segurando **Vol-**. A tela mostra os DTBs do SoC, os convertidos e
"Automatic", com as marcas `(auto)` (o que seria escolhido sozinho), `(ok)` (já confirmado
neste aparelho) e `(forced)`. Cima/baixo (ou Vol+/Vol-) move, A escolhe; no R36S,
esquerda/L1 e direita/R1 pulam uma página. A escolha fica guardada e vale nos boots
seguintes; "Automatic" apaga a escolha guardada. Sem nenhuma tecla em 60 s, o boot segue
com a escolha automática. (As teclas ainda são provisórias: falta conferir quais o
bootloader de fábrica de cada console usa ao ligar.)

**Confirmação na tela:** no primeiro boot com um DTB que ainda não foi confirmado naquele
aparelho, a tela pergunta "If you can read this, press A to keep it." com uma contagem de
15 s. A mantém o DTB e o aprende para o painel; sem resposta (tela preta ou ninguém na
frente), o console volta sozinho ao DTB anterior e descarta esse naquele aparelho. Se o
kernel novo travar antes da pergunta, desligue e ligue o console: o boot seguinte descarta
esse DTB e volta ao último que funcionou (o reinício sozinho pelo watchdog ainda está em
prova).

**Guardado por aparelho:** a escolha e os descartados ficam em
`ROMS/system/etc/dtb-<soc>-<serial>.conf`, um arquivo por aparelho (pelo número de série do
SoC ou, no R36S, pelo que o U-Boot de fábrica grava no device tree), de modo que o cartão levado a outro console do mesmo modelo não leva a escolha do
primeiro. O aprendido por ID do painel fica em `ROMS/system/etc/dtb-<soc>-learned.conf`.
Para recomeçar do zero, apague esses arquivos pelo PC; para usar de novo um DTB descartado
com o `force`, tire o nome dele da linha `bad=` do arquivo do aparelho.

**No log:** `ROMS/logs/boot/boot-<n>.log`, linhas `lume-bootsel:`; a linha
`selected <id> (reason: ...)` diz qual DTB foi usado e por quê (`default`, `rule`,
`learned`, `auto`, `search`, `manual`, `forced`, `fallback`, `reverted`). No
`ROMS/logs/events.log`, `boot OK device tree selected …`. Detalhes em
[docs/LOGS.md](docs/LOGS.md).

### Clones do R36S: device trees convertidos

Além do R36S V5, a `BOOT` traz em `dtbs/rk3326/vendor/` cerca de 170 device trees de
clones e parentes do R36S (RK3326), convertidos dos DTBs do dArkOSRE e do arkos4clone para
o nosso kernel (`board/r36s/dts-vendor/`, gerados por `r36os dtb-import`; a origem de cada
um e os recusados, com o motivo, ficam no `SOURCES.tsv`). Num boot normal eles não são
lidos, e a busca sozinha (tela preta) não os testa: seriam um reinício por placa. Para usar
um:

- **pela lista:** ligar segurando Vol-, rolar até o nome (esquerda/L1 e direita/R1 pulam uma
  página) e confirmar com A;
- **pelo PC:** escrever o nome (o do arquivo, sem `.dtb`) em `BOOT/dtbs/force`.

No primeiro boot com um DTB novo a tela pergunta se ele serve: A em 15 s mantém; sem
resposta (tela preta), o console volta sozinho ao anterior e descarta esse DTB naquele
aparelho. Confirmado, ele é lembrado para o painel do aparelho e escolhido sozinho nos boots
seguintes. São **compatíveis por conversão, sem garantia**: só o R36S V5 foi provado; os
analógicos de outras placas seguem a semântica do ROCKNIX, sem medição, e podem precisar
de remapeamento no RetroArch. O volume do alto-falante é sempre o seguro do R36S V5.
**A alimentação vem da origem:** as tensões dos reguladores do PMIC (RK817) e qual
regulador alimenta cada banco de pinos do SoC são copiadas do DTB de origem, como aquele
sistema já roda naquela placa; um regulador que a origem não declara fica com a tensão que
o bootloader deixou, e nenhum regulador que o R36S V5 mantém ligado é desligado. Para a
família "EE", essa alimentação foi conferida com o device tree do ROCKNIX para essas
placas. No aparelho, só o DTB de fábrica do R36S V5 convertido foi provado até aqui.

**Fora do alcance:** aparelhos com eMMC (o RK3326 inicia pelo eMMC antes do cartão, P-43);
as placas A33/A23 da família do GA36 sem DTB de fábrica (P-16); aparelhos de outro SoC
(RK3128, MediaTek MT6572, HCSEMI E3100: GB350, R36SX, R36HD e parecidos); e as famílias que
o conversor ainda recusa (DTBs de fábrica "EE" com `play_joystick`, RG351 com joypad HID,
PMIC RK809 e outras, P-75).

### Converter os DTBs (o do seu aparelho ou as coleções)

A conversão é automática e roda no PC: `r36os dtb-import` lê os DTBs (do kernel 4.4 ou
5.10 da Rockchip, como os do ArkOS, dArkOS e dos cartões de fábrica), gera um device tree
nosso por placa em `board/r36s/dts-vendor/` e anota cada arquivo lido no
`board/r36s/dts-vendor/SOURCES.tsv`: `converted` (com o nome da placa), `refused` (com o
motivo) ou `same` (igual a outro já convertido). O DTB original não é alterado.

**1. Baixar as coleções** (uma vez; ficam em `.cache/upstream/`, fora do git). O comando
exige as três, para que a pasta gerada seja a mesma em qualquer máquina:

```sh
git clone https://github.com/southoz/dArkOSRE-R36.git .cache/upstream/dArkOSRE-R36
git -C .cache/upstream/dArkOSRE-R36 checkout 3f372c85aa53a26b265c3dc0c2661ec0fae5faf0
git clone https://github.com/lcdyk0517/arkos4clone.git .cache/upstream/arkos4clone
git -C .cache/upstream/arkos4clone checkout c570364df5baf417edb7eed6be01bf0bc48a7755
git clone https://github.com/Vi-K36/EE-Clones-DTB.git .cache/upstream/EE-Clones-DTB
git -C .cache/upstream/EE-Clones-DTB checkout 73fb2cf539fde87c32c35304c90e594cf3039cd7
```

**2. (Opcional) O DTB de fábrica do seu aparelho.** Copie da partição `BOOT` do cartão
original o `.dtb` do kernel (por exemplo `rk3326-r35s-linux.dtb`,
`rk3326-evb-lp3-v12-linux.dtb` ou `rf3536k3ka.dtb`; não os `rg351*-uboot.dtb`) para uma
pasta, e passe-a com um nome curto. A cópia do cartão do R36S em `out/r36s-factory/` entra
sozinha quando existe.

**3. Converter:**

```sh
uv run r36os dtb-import                      # as coleções (e out/r36s-factory, se houver)
uv run r36os dtb-import meu=~/meu-console    # as coleções mais a pasta do seu aparelho
```

Cada execução refaz a pasta inteira a partir das fontes que recebeu, então o DTB do seu
aparelho aparece como mudança local no git e some se o comando rodar de novo sem ele. O
comando mostra quantos foram `converted`, `refused` e `same`. Procure o seu arquivo no
`SOURCES.tsv`: a segunda coluna é o nome da placa convertida (por exemplo `meu-r35s`); se
foi recusado, a última coluna diz o motivo.

**4. Gerar e gravar o cartão** com os DTBs novos: `uv run r36os build console` (o build
compila cada DTS e o confere no `dt-validate`; um erro para o build) e depois
`uv run r36os flash console <dispositivo> --update` ou `uv run r36os push`.

**5. No console:** escreva o nome da placa em `BOOT/dtbs/force` (ou escolha-a na lista com
Vol- segurado ao ligar) e confirme com A quando a tela perguntar. Sem resposta em 15 s, o
console volta sozinho ao DTB anterior.

Ao mudar o conversor (`src/r36os/vendor_dtb.py`), rode `uv run r36os dtb-import` de novo e
inclua no commit a pasta `board/r36s/dts-vendor/` regenerada; o teste
`tests/unit/test_vendor_dtb.py` acusa quando ela ficou desatualizada.

### Números desta versão

Medidos em 2026-11-11 (GA36: imagem `20261111-131212` e os boots anteriores no aparelho;
VM: `test-vm` da mesma build, 69 de 69 checagens):

| | GA36 | VM |
|---|---|---|
| Do kernel ao frontend | 19 a 22 s | 2,9 s |
| `SYSTEM` (squashfs) | 270 MiB | 302 MiB |
| `ROMS` num cartão de 4 GB | cerca de 1,6 GiB (o cartão menos 128 MiB do fabricante e 2 GiB da `BOOT`) | cerca de 2,7 GiB |

## Documentação

- [docs/BRINGUP-GA36.md](docs/BRINGUP-GA36.md): gravar, subir e conferir o GA36
- [docs/BRINGUP-R36S.md](docs/BRINGUP-R36S.md): cadeia de boot de fábrica, cartão único e conferência do R36S
- [docs/PENDENCIAS.md](docs/PENDENCIAS.md): o que falta, para decidir as próximas changes
- [docs/VM.md](docs/VM.md): VM, atalhos de teclado e leitura do teste de aceitação
- [docs/LOGS.md](docs/LOGS.md): logs de diagnóstico
- [docs/CATALOG.md](docs/CATALOG.md): catálogo de sistemas e cores
- [docs/FRONTEND.md](docs/FRONTEND.md): contrato da sessão, troca de frontend e idioma
- [docs/LAUNCHER.md](docs/LAUNCHER.md): guia do lume-launcher (controles, Fn+Start, listas de
  jogos e como adicionar um emulador pelo cartão)
- [docs/referencia/](docs/referencia/): medições do GA36 no projeto anterior

## Estrutura

```
board/<camada>/   DTS, extlinux.conf, configs do kernel e do U-Boot, serial, pacotes de hardware
kernel/patches/   patches do kernel (bindings e os drivers do painel e do controle do GA36)
aports/           pacotes Alpine locais (RetroArch, cores, Mesa da VM); mudanças em *.patch
rootfs/           lista de pacotes, overlay e configuração do sistema
initramfs/        init próprio (partição de jogos, SYSTEM, overlay)
src/r36os/        orquestrador (build, imagem, versão, gravação, VM, testes)
tests/            testes unitários, de integração e suítes em shell
openspec/         planejamento (proposta, design, specs e tarefas)
out/              artefatos do build: imagens, repositório de pacotes local (fora do git)
.cache/           cache do build: fontes, árvores de build, ccache, chaves do abuild (fora do git)
```

Upstream (kernel, U-Boot, aports, RetroArch) fica intocado e fixado por versão e sha256;
toda mudança entra como patch numerado.

## Agradecimentos

O Lume Retro OS é autocontido: o build não baixa nem depende de nada destes projetos. Eles
serviram de inspiração e de referência, e o que foi aproveitado está copiado no próprio
repositório, com o crédito no lugar:

- **[goodluckOS](https://github.com/CodeZombie/goodluckOS)** (GPL-2.0): os drivers do painel
  JD9366 e do controle serial do GA36 (`kernel/patches/0005` e `0006`) e a base do device
  tree (`board/ga36/dts/`) são port do trabalho dele.
- **Firmware de fábrica do GA36** (baseado no EmuELEC): medições, ajustes de áudio, bateria
  e cores registrados em `docs/referencia/ga36-emuelec/`, que guiaram decisões como o core
  de SNES e o volume.
- **Shaders do projeto anterior do autor** ("R36S GA36-MB V1.2"): os shaders `gb-modern-dmg`,
  `gbc-modern-remaster` e `gba-modern-remaster`, copiados sem alteração para
  `/usr/share/libretro/shaders/lume-shaders/` (escolhidos no menu do RetroArch, desligados
  por padrão).
- **[Imagem custom para o clone do R36S (r/R36SBrasil)](https://www.reddit.com/r/R36SBrasil/comments/1xr9zfp/lan%C3%A7amento_imagem_custom_para_clone_do_r36s_placa/)**:
  tópico da comunidade usado como referência para configurar o GA36.
- **[dArkOSRE-R36](https://github.com/southoz/dArkOSRE-R36)**: os dados do hardware do R36S
  (Apêndice A do design da change `alpine-retroarch-distro`), base do device tree do R36S, e
  os DTBs das placas R36S, clones e "soysauce" convertidos em `board/r36s/dts-vendor/`.
- **[arkos4clone](https://github.com/lcdyk0517/arkos4clone)** (MIT, lcdyk) e
  **[EE-Clones-DTB](https://github.com/Vi-K36/EE-Clones-DTB)** (DTBs de fábrica reunidos pela
  comunidade): os
  DTBs dos clones convertidos em `board/r36s/dts-vendor/`; de cada um saem só os parâmetros
  de hardware (pinos, timings, sequência do painel), e cada DTS cita a origem e o SHA-256.
- **[ROCKNIX](https://github.com/ROCKNIX/distribution)**: o driver `panel-generic-dsi`
  (GPL-2.0, Danil Zagoskin; port em `kernel/patches/0033`), a lógica de conversão do
  `rocknix_dtbo.py` (`stolen/overlay_server`, MIT) portada para `src/r36os/vendor_dtb.py`, e
  o mapeamento dos analógicos do `rocknix-singleadc-joypad` (GPL-2.0).
- **Cartão de fábrica do R36S** (um ArkOS para o "R36S V5"): a cadeia de boot do aparelho
  (`idbloader` e `trust.img` da Rockchip e o U-Boot da linha Hardkernel, que lê o
  `boot.ini`) e o device tree de fábrica, de onde vieram a sequência do painel e os valores
  do PMIC. A cadeia é binário fechado e **não é distribuída**: o build a extrai da cópia do
  cartão do próprio aparelho (`R36OS_R36S_FACTORY`).
- **Device trees mainline do Odroid Go2/Go3 (Hardkernel) e do GameForce Chi** (Chris
  Morgan): a estrutura do `board/r36s/dts/rk3326-r36s-v5.dts` (mesmo RK3326, analógicos
  sobre `io-channel-mux` e painel ST7703) segue a deles.
- **[Alpine Linux](https://alpinelinux.org/)**, **[RetroArch e libretro](https://www.retroarch.com/)**
  e o **Linux mainline**: a base de tudo; os pacotes locais de `aports/` partem dos APKBUILDs do
  Alpine, e as mudanças no RetroArch e nos cores ficam em patches numerados.
- **FB Alpha 2012** (Final Burn Alpha v0.2.97.29, de Dave e da equipe do FB Alpha): os
  cores `fbalpha2012_cps1`, `fbalpha2012_cps2` e `fbalpha2012_neogeo` (os recortes por placa
  do libretro, `libretro/fbalpha2012_*`) são o core padrão do CPS-1, do CPS-2 e do Neo Geo.

## Licença

O Lume Retro OS é distribuído sob a **GNU General Public License, versão 2** (somente a
versão 2, `GPL-2.0-only`); o texto está em [LICENSE](LICENSE).

- Os drivers do painel JD9366 e do controle do GA36 (`kernel/patches/`) são port do
  goodluckOS (GPL-2.0), e os patches do kernel seguem a GPL-2.0, como o próprio Linux.
- Cada pacote em `aports/` mantém a licença do upstream (o `APKBUILD` declara a de cada
  um); os patches desses pacotes seguem a licença do projeto que modificam.
- Os cores **FB Alpha 2012** (`aports/libretro-fbalpha2012-*`) têm licença própria, **não
  comercial**: o FB Alpha proíbe a venda e o pedido de doações. Por isso o Lume Retro OS é
  distribuído de graça e **sem doações**, e o texto da licença vai junto com o binário, em
  `/usr/share/licenses/libretro-fbalpha2012-*/license.txt`. Quem redistribuir a imagem
  herda a restrição.
- Os bootloaders dos fabricantes (boot0 e U-Boot da Allwinner no GA36; `idbloader`,
  `uboot.img` e `trust.img` da Rockchip no R36S) são binários fechados e **não são
  distribuídos**: cada um os extrai do cartão original do próprio aparelho
  (`R36OS_GA36_FACTORY` e `R36OS_R36S_FACTORY`).
- Nenhuma ROM, BIOS ou jogo comercial faz parte do repositório; as ROMs de teste da VM
  são geradas pelo build.
