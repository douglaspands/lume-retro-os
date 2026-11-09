# VM de teste (x86_64)

A imagem `vm` tem o mesmo layout de cartão, o mesmo `extlinux.conf`, o mesmo initramfs,
os mesmos serviços, cores e configuração do RetroArch dos consoles. Só mudam o kernel (`linux-virt` do
Alpine), o bootloader (SYSLINUX) e os drivers (virtio).

## Pré-requisitos

- `podman` (rootless) e `uv`; nada é instalado no host.
- `/dev/kvm` acessível ao usuário.
- Para a janela: sessão gráfica (Wayland ou X11). Com GPU NVIDIA de driver
  proprietário, a especificação CDI (`/var/run/cdi/nvidia.yaml` ou `/etc/cdi/`, gerada por
  `nvidia-ctk cdi generate`) para o QEMU usar o GL do host.

## Gerar a imagem

```
uv run r36os build vm
```

Saída em `out/vm/`: `vm.img` (imagem do cartão, 1040 MiB), `SYSTEM`, `initramfs`,
`manifest.txt` (pacotes e versões) e `kernel/`. O cache (chave do abuild, fontes,
ccache) fica em `~/.cache/r36os/` (ou `$R36OS_CACHE`).

## Rodar

```
uv run r36os vm              # janela 640x480 com virgl e áudio do host
uv run r36os vm --headless   # sem janela: console serial no terminal
uv run r36os vm --roms ~/Jogos   # jogos de uma pasta do PC, somente leitura
uv run r36os vm --gamepad /dev/input/by-id/usb-...-event-joystick   # controle específico
uv run r36os vm --no-gamepad     # não repassa nenhum controle do PC
```

**Controles do PC:** sem `--gamepad`, os controles em `/dev/input/by-id/*-event-joystick`
que o seu usuário consegue abrir e capturar são repassados à VM automaticamente
(`virtio-input-host-pci`). Enquanto a VM roda, o controle deixa de responder no PC.

**Jogos do PC (`--roms DIR`, ou `--share DIR`):** a pasta é exportada por virtio-9p,
somente leitura, e aparece em `/mnt/host` na VM. Se ela tiver as pastas dos sistemas
(`nes/`, `snes/`, …) ou uma pasta `roms/` com elas, o serviço `r36os-hostshare` a usa
como `/storage/roms`, e `bios/` dela como `/storage/bios`, antes de gerar as listas de
jogos. Saves e estados continuam no disco descartável da VM. A VM nunca altera a pasta.

Cada execução usa uma cópia descartável de `out/vm/vm.img`, aumentada para 4 GB como um
cartão real: o primeiro boot sempre cria a partição `ROMS`. A serial também é gravada em
`~/.cache/r36os/vm/serial.log`, e o QMP fica em `~/.cache/r36os/vm/qmp.sock`.

O console serial aceita `root` sem senha (só nesta fase de validação). Para encerrar,
escolha **Desligar** no menu principal do RetroArch (o sistema grava o pendente e
desliga) ou rode `poweroff` na serial.

### Teclado na janela

| Tecla | Botão do console |
|---|---|
| setas | direcional |
| X / Z | A / B |
| S / A | X / Y |
| Q / W | L1 / R1 |
| E / R | L2 / R2 |
| Enter | Start |
| Shift direito | Select |
| Enter + Shift direito | abre o menu (Start + Select, igual ao console) |
| Shift direito + S | também abre o menu (atalho só do teclado) |

Nenhuma tecla ou combinação encerra o RetroArch: Esc não faz nada. Abrir o menu durante
um jogo pausa o jogo. Ctrl+Alt+G libera o mouse da janela do QEMU.

## Teste de aceitação

```
uv run r36os test-vm          # --keep mantém o disco da VM em ~/.cache/r36os/vm/test.img
```

O teste sobe a VM sem tela com `r36os.selftest=1` e um segundo disco FAT (`TESTDATA`)
com as ROMs de teste geradas pelo build. O serviço `r36os-selftest` roda dentro da VM,
fase por fase (um boot por fase), e imprime na serial:

```
SELFTEST <verificação> PASS|FAIL [detalhe]
SELFTEST REQUEST <ação>        # o host atende: reset abrupto, teclas via QMP
```

Ao final o teste pede `QUIT` ao RetroArch e confere que o sistema desligou.

Resultado em `out/vm/test-vm/`:

| Arquivo | Conteúdo |
|---|---|
| `serial.log` | log serial completo de todos os boots |
| `summary.txt` | uma linha por verificação (`PASS`/`FAIL nome detalhe`) e o tempo até o frontend |
| `results.txt` | resultados gravados pela VM no disco TESTDATA |
| `results/core-*.log` | log do RetroArch de cada core testado |

Para ler o log serial: procure `SELFTEST ... FAIL`, as mensagens do initramfs e dos
serviços (`lume: ...`) e o resumo de hardware. Os logs de boot também ficam na
partição `BOOT`, em `logs/boot-<n>.log`, e o log do frontend em
`logs/frontend-erro.log` quando ele falha 3 vezes.

## Depuração

```
uv run python tests/vm/console.py 'comando' 'outro comando'
```

Sobe a VM sem tela, entra como root na serial, roda os comandos e imprime a saída
(`CONSOLE_TAIL=<segundos>` estende a espera depois do último comando).

Limitação conhecida: com GPU NVIDIA proprietária, o QMP `screendump` não captura a tela
em modo GL (virgl). As capturas usam o próprio RetroArch ou a VM sem GL.
