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

## O cartão

| Região | Conteúdo |
|---|---|
| início do cartão | bootloaders. Na `console`: os 128 MiB com as cadeias de fábrica dos dois consoles (boot0 do GA36 encolhido para 24 KiB, `idbloader`, `uboot.img` e `trust.img` do R36S, U-Boot do GA36) e o nosso kernel do GA36 no setor 172032. Na `vm`: SYSLINUX nos primeiros 16 MiB |
| `BOOT` (FAT32, 2 GiB na `console`, 1 GiB na `vm`) | `VERSION`. Na `console`: `boot.ini` (lido pelo U-Boot do R36S), `ga36/` (`SYSTEM`, DTBs e as imagens de boot dos dois painéis em `android-boot/`) e `r36s/` (`SYSTEM`, kernel e DTB). Na `vm`: `SYSTEM`, kernel, initramfs e `extlinux/` |
| `ROMS` (exFAT, resto do cartão) | `roms/<sistema>/`, `bios/`, `saves/`, `states/`, `system/` (configurações), `logs/`, `LEIA-ME.txt`: a mesma nos dois consoles |

- Os jogos vão em `ROMS/roms/<sistema>/` pelo PC; as listas são geradas no boot.
- **Restaurar a configuração de fábrica:** apagar a pasta `ROMS/system/`.
- **Logs** (sempre em inglês): `ROMS/logs/`. Formato em [docs/LOGS.md](docs/LOGS.md).
- **GA36, painel:** há duas variantes de tela; a imagem usa a 1 (a do firmware de fábrica).
  A imagem de boot da 2 fica em `BOOT/ga36/android-boot/android-boot-panel2.img` (gravá-la
  no setor 172032 troca o painel).
- **Trocar de console:** basta passar o cartão de um aparelho para o outro. Os saves
  (`.srm`) passam entre eles; os *save states* podem não passar, porque o GA36 é armv7 e o
  R36S é aarch64.
- **Leitor de cartão:** o leitor USB `14cd:125d` ("Mass Storage Device") corrompe o cartão em
  gravações pequenas: grava o próprio comando USB (assinatura `USBC`) no lugar dos dados,
  como no primeiro setor da `ROMS` ou no FSINFO da `BOOT`. O `r36os flash` avisa quando
  identifica esse leitor, e o boot registra a causa quando acha a `ROMS` com essa
  assinatura. Use outro leitor; um cartão afetado se recupera com `fsck.exfat` ou
  gravando de novo com `--full`.

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
  (Apêndice A do design da change `alpine-retroarch-distro`), base do device tree do R36S.
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
