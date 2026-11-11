# Lume Retro OS

Distro mínima baseada em **Alpine Linux** com **RetroArch** para consoles portáteis:

| Alvo | Aparelho | SoC | Estado |
|---|---|---|---|
| `ga36` | GA36-MB V1.2 (clone do R36S) | Allwinner A33, armv7 | validado no aparelho ([guia](docs/BRINGUP-GA36.md)) |
| `r36s` | R36S "V5" | Rockchip RK3326, aarch64 | planejado (pendência P-27) |
| `vm` | VM de teste (QEMU/KVM) | x86_64 | testada automaticamente a cada build |

O sistema sobe direto no menu do RetroArch (Ozone), sem login, com a raiz somente leitura
(`SYSTEM` em squashfs) e uma partição de jogos `ROMS` em exFAT, criada pelo `r36os flash` (ou
no primeiro boot, se faltar) e legível em qualquer PC. `r36os` é o nome interno do orquestrador, dos pacotes e dos serviços.

## Requisitos

- Linux com `podman` (rootless) e [`uv`](https://docs.astral.sh/uv/); Python 3.14 via `uv`;
- para os alvos ARM, `qemu-user` registrado no binfmt (os pacotes são compilados sob emulação);
- espaço em disco: o cache fica fora do repositório, em `~/.cache/r36os` (kernel, U-Boot,
  distfiles, ccache), e os artefatos em `out/`.

Tudo roda em containers: kernel e U-Boot em cross (Debian), pacotes e rootfs em Alpine.

**GA36: imagem de fábrica.** O GA36 sobe pelo bootloader do fabricante (boot0 e U-Boot da
Allwinner), que é binário fechado e não está no repositório. Na primeira vez, aponte a
variável para a imagem de fábrica (ou um dump dos primeiros 128 MiB do cartão original);
o build extrai a área de boot para o cache e confere o SHA256:

```sh
R36OS_GA36_FACTORY="/caminho/R36S GA36-MB V1.2-20260416 - Emuelec - No ROMS.img" uv run r36os build ga36
```

## Uso rápido

```sh
uv run r36os build vm              # gera a imagem da VM
uv run r36os vm                    # roda a VM em janela (--headless: serial no terminal)
uv run r36os test-vm               # teste de aceitação completo da VM

uv run r36os build ga36            # gera a imagem do GA36
uv run r36os build ga36 --lang pt_BR   # idioma de fábrica do menu (padrão: en)
uv run r36os build --all           # vm + test-vm, depois os consoles (só liberados se a vm passar)
```

Idiomas aceitos em `--lang`: `en` (padrão), `pt_BR`, `pt_PT`, `es`, `fr`, `de`, `it`.
O usuário pode trocar o idioma no menu do RetroArch, e a escolha é guardada no cartão.

## Versões das imagens

Cada build recebe um timestamp (`AAAAMMDD-HHMMSS`) e é guardado em
`out/images/<alvo>/<timestamp>/`:

```
out/images/ga36/20261109-214233/
  ga36-20261109-214233.img.zst   imagem do cartão (zstd)
  manifest.txt                   pacotes e versões
  build.json                     commit, idioma, kernel e patches, U-Boot, Alpine, tamanhos
  SHA256SUMS
out/images/ga36/latest -> 20261109-214233
```

O mesmo timestamp está em `BOOT/VERSION` (no PC) e em `/etc/os-release` (`BUILD_ID`).

## Gravar o cartão

Rode num terminal (a escrita usa `sudo`, que pede a senha):

```sh
uv run r36os flash ga36 /dev/sdX --full     # cartão todo (o padrão): imagem + ROMS no resto
uv run r36os flash ga36 /dev/sdX            # o mesmo que --full
uv run r36os flash ga36 /dev/sdX --update   # atualização: preserva jogos, saves e configurações
uv run r36os flash ga36 /dev/sdX --build 20261109-214233   # um build específico
uv run r36os eject /dev/sdX                 # ejetar com segurança (sync, desmonta e desliga)
```

- O comando só aceita discos removíveis, desmonta as partições, pede para digitar o nome
  do dispositivo como confirmação e, no fim, lê de volta e confere o SHA256.
- A gravação completa cria também a `ROMS` (exFAT) com todo o espaço que sobra do cartão,
  as pastas padrão (`roms/<sistema>` de cada sistema do catálogo, `bios`, `saves`, `states`,
  `screenshots`, `system`) e a configuração de fábrica do RetroArch, no idioma do build.
  Dá para copiar os jogos logo depois, antes do primeiro boot. No fim, o `fsck.exfat -n`
  confere a partição criada.
- `--update` grava só a área de boot e a partição `BOOT`; a tabela de partições e a `ROMS`
  não são tocadas. Ele recusa cartões que não foram gravados com uma imagem do mesmo alvo
  (por exemplo, um cartão com o layout antigo, em que a `BOOT` começava em 16 MiB).
- Para descobrir o dispositivo: `lsblk -o NAME,SIZE,TRAN,RM,MODEL,LABEL`.

## O cartão

| Região | Conteúdo |
|---|---|
| início do cartão | bootloader. No GA36: os 128 MiB do fabricante, com o nosso kernel no setor 172032 |
| `BOOT` (FAT32, 1 GiB) | `SYSTEM`, `VERSION`, DTBs; na VM também kernel, initramfs e `extlinux/`; no GA36 as imagens de boot dos dois painéis em `android-boot/` |
| `ROMS` (exFAT, resto do cartão) | `roms/<sistema>/`, `bios/`, `saves/`, `states/`, `system/` (configurações), `logs/`, `LEIA-ME.txt` |

- Os jogos vão em `ROMS/roms/<sistema>/` pelo PC; as listas são geradas no boot.
- **Restaurar a configuração de fábrica:** apagar a pasta `ROMS/system/`.
- **Logs** (sempre em inglês): `ROMS/logs/`. Formato em [docs/LOGS.md](docs/LOGS.md).
- **GA36, painel:** há duas variantes de tela; a imagem usa a 1 (a do firmware de fábrica).
  A imagem de boot da 2 fica em `BOOT/android-boot/android-boot-panel2.img` (gravá-la no
  setor 172032 troca o painel).
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
| `ROMS` num cartão de 4 GB | cerca de 2,6 GiB (o cartão menos 128 MiB do fabricante e 1 GiB da `BOOT`) | cerca de 2,7 GiB |

## Documentação

- [docs/BRINGUP-GA36.md](docs/BRINGUP-GA36.md): gravar, subir e conferir o GA36
- [docs/PENDENCIAS.md](docs/PENDENCIAS.md): o que falta, para decidir as próximas changes
- [docs/VM.md](docs/VM.md): VM, atalhos de teclado e leitura do teste de aceitação
- [docs/LOGS.md](docs/LOGS.md): logs de diagnóstico
- [docs/CATALOG.md](docs/CATALOG.md): catálogo de sistemas e cores
- [docs/FRONTEND.md](docs/FRONTEND.md): contrato da sessão, troca de frontend e idioma
- [docs/referencia/](docs/referencia/): medições do GA36 no projeto anterior

## Estrutura

```
board/<alvo>/     DTS, extlinux.conf, configs do kernel e do U-Boot, serial, pacotes de hardware
kernel/patches/   patches do kernel (bindings e os drivers do painel e do controle do GA36)
aports/           pacotes Alpine locais (RetroArch, cores, Mesa da VM); mudanças em *.patch
rootfs/           lista de pacotes, overlay e configuração do sistema
initramfs/        init próprio (partição de jogos, SYSTEM, overlay)
src/r36os/        orquestrador (build, imagem, versão, gravação, VM, testes)
tests/            testes unitários, de integração e suítes em shell
openspec/         planejamento (proposta, design, specs e tarefas)
```

Upstream (kernel, U-Boot, aports, RetroArch) fica intocado e fixado por versão e sha256;
toda mudança entra como patch numerado.

## Licença

O Lume Retro OS é distribuído sob a **GNU General Public License, versão 2** (somente a
versão 2, `GPL-2.0-only`); o texto está em [LICENSE](LICENSE).

- Os drivers do painel JD9366 e do controle do GA36 (`kernel/patches/`) são port do
  goodluckOS (GPL-2.0), e os patches do kernel seguem a GPL-2.0, como o próprio Linux.
- Cada pacote em `aports/` mantém a licença do upstream (o `APKBUILD` declara a de cada
  um); os patches desses pacotes seguem a licença do projeto que modificam.
- O bootloader do fabricante do GA36 (boot0 e U-Boot da Allwinner) é binário fechado e
  **não é distribuído**: cada um o extrai da própria imagem de fábrica (`R36OS_GA36_FACTORY`).
- Nenhuma ROM, BIOS ou jogo comercial faz parte do repositório; as ROMs de teste da VM
  são geradas pelo build.
