# GA36-MB V1.2: gravar, subir e conferir

Guia da primeira subida e da conferência de uma imagem nova no GA36 (Allwinner A33).
Validado no aparelho em 2026-11-11 (imagens `20261111-002830` a `20261111-134121`).

## 1. Gerar e gravar

```sh
uv run r36os build console                         # 1ª vez: R36OS_GA36_FACTORY e R36OS_R36S_FACTORY com as cópias dos cartões originais (README)
uv run r36os flash console /dev/sdX --full --eject # cartão novo: imagem + ROMS no resto do cartão
uv run r36os flash console /dev/sdX --update --eject   # atualizar: preserva jogos, saves e ajustes
uv run r36os eject /dev/sdX                     # ejetar depois de copiar jogos (sem senha)
```

- O `--full` cria a `ROMS` (exFAT) já com as pastas e a configuração de fábrica: dá para
  copiar os jogos antes do primeiro boot (`ROMS/roms/<sistema>/`, BIOS em `ROMS/bios/`).
- O `flash` avisa quando o cartão está no leitor USB `14cd:125d`, que corrompe gravações
  pequenas. Use outro leitor se puder; um cartão afetado aparece no boot como
  `partition 2 ... USB command block ("USBC")`.

## 2. Primeiro boot

- O kernel sobe pelo bootloader do fabricante (área de 128 MiB) e mostra as mensagens na
  tela; o menu do RetroArch aparece em cerca de 20 s.
- O primeiro boot só verifica a `ROMS` (`roms OK checked: clean` no `events.log`). Se ela
  não existir, é criada com o resto do cartão.
- **Serial (opcional):** `ttyS1`, 115200 baud, a mesma velocidade do bootloader ao kernel.

## 3. A partição `BOOT`

A mesma nos dois consoles (`docs/BRINGUP-R36S.md` tem a mesma tabela):

| Caminho | O que é |
|---|---|
| `VERSION` | build gravado no cartão |
| `boot.ini` | lido pelo U-Boot do R36S (o GA36 não lê) |
| `rg351mp-kernel.dtb`, `rg351p-kernel.dtb` | de fábrica, exigidos pelo U-Boot do R36S |
| `logo.bmp` | logo do boot (o de fábrica do R36S), BMP 640x480 de 24 bits |
| `dtbs/a33/` | DTBs do GA36: `sun8i-a33-ga36-mb-v1.2-panel1.dtb` (`ga36-panel1`, o padrão) e `sun8i-a33-ga36-mb-v1.2-panel2.dtb` (`ga36-panel2`) |
| `dtbs/rk3326/` | DTB do R36S: `rk3326-r36s-v5.dtb` (`r36s-v5`, o padrão) |
| `dtbs/force` | opcional, criado pelo usuário: o nome do DTB a usar (seção 3.1) |
| `ga36/` | `SYSTEM` e `zImage` (o kernel recarregado na troca de DTB) |
| `r36s/` | `SYSTEM` e `Image` |

A `BOOT` tem só o que os consoles leem. O GA36 inicia pela imagem de boot do setor 172032,
fora da `BOOT`; as imagens dos dois painéis ficam na pasta do build no PC
(`out/images/console/<build>/ga36-android-boot-panel{1,2}.img`, com o SHA256 no
`SHA256SUMS`).

**Logo:** hoje o GA36 mostra o `bootlogo.bmp` da área de fábrica. Passar a usar o
`BOOT/logo.bmp` (o mesmo logo nos dois) é a tarefa 2.2 de `boot-dtb-select`, que depende da
prova 1.4.

### 3.1 Trocar o painel

O bootloader sempre inicia com o painel 1 (a imagem de boot do setor 172032, com o DTB do
painel 1 anexado). No initramfs, o `lume-bootsel` olha `BOOT/dtbs/a33/` e decide, nesta
ordem: o arquivo `BOOT/dtbs/force`; a lista na tela (tecla segurada ao ligar); a volta ao
último DTB que funcionou; a escolha salva da lista; as regras de cada DTB; o padrão. Se o
escolhido não é o que está rodando, o kernel reinicia uma vez com ele (kexec do
`ga36/zImage`). Os dois painéis ainda não têm uma regra que os distinga, então sem
escolha o GA36 fica no painel 1.

- **Tela preta, pelo PC:** escrever `ga36-panel2` em `BOOT/dtbs/force`. Apagar o arquivo
  volta ao automático. Um nome que não existe é ignorado (motivo no log).
- **Pela tecla:** segurar **Vol-** ao ligar abre a lista; direcional ou volume navegam e
  **A** confirma. A escolha fica salva em `ROMS/system/etc/dtb-a33.conf` e "Automatic"
  apaga a escolha. (Teclas provisórias até a prova 1.3 de `boot-dtb-select`.)
- **Se o DTB escolhido não chegar ao menu**, desligue e ligue: o boot seguinte volta ao
  último DTB que funcionou (`reason: fallback` no log).
- **Log:** `boot/boot-<n>.log` tem `lume-bootsel: selected <id> (reason: …)`, e o
  `hw/boot-<n>.txt` tem `dt in use` (formato em `docs/LOGS.md`).

**Enquanto a troca por kexec não estiver provada no GA36** (prova 1.5 de
`boot-dtb-select`), o caminho antigo continua valendo: gravar a imagem de boot do painel 2,
da pasta do build gravado no cartão, no setor 172032, pelo PC:

```sh
sudo dd if=out/images/console/<build>/ga36-android-boot-panel2.img of=/dev/sdX \
    bs=512 seek=172032 conv=notrunc,fsync
```

Para voltar ao painel 1, a mesma coisa com `ga36-android-boot-panel1.img`. O `<build>` é o
do `BOOT/VERSION`: a imagem de boot leva o kernel e o initramfs, que precisam ser do mesmo
build do `ga36/SYSTEM`.

## 4. Controle

O driver do kernel junta os botões e os dois analógicos num único "GA36-MB Gamepad", com
autoconfiguração do RetroArch (`/usr/share/libretro/autoconfig/udev/GA36-MB Gamepad.cfg`):
A, B, X, Y, L1, R1, L2, R2, Start, Select, direcional, L3, R3 e os dois analógicos. **Fn**
abre o menu; **Start + Select** também. Os botões de volume ajustam de 5 em 5% (0 a 100%).
No menu, A confirma e B volta.

## 5. Checklist de conferência

| Item | Como conferir | Onde ver |
|---|---|---|
| Painel e brilho | imagem desde as mensagens do kernel | tela |
| Controle | todos os botões e analógicos no menu e num jogo | tela |
| Áudio e volume | som no alto-falante e no fone, botões de volume | ouvido; `events.log` sem `audio FAIL` |
| Jogos | NES, SNES, GB/GBC, GBA e PS1 sem travar | `events.log` (`game`), coluna `fps` das métricas |
| Ajustes | mudar a fonte, abrir/fechar um jogo, reiniciar: o ajuste continua | menu |
| Bateria | porcentagem e corrente | `metrics/boot-<n>.csv` (`bat_*`) |
| Temperatura | abaixo de 75 °C (primeiro gatilho) | `metrics/boot-<n>.csv` (`temp_cpu_thermal_c`) |
| Desligar | "Shut Down" duas vezes: a tela apaga e o aparelho desliga | `events.log` (`shutdown OK clean`) |

Os logs ficam em `ROMS/logs/` (formato em [LOGS.md](LOGS.md)): `events.log` (eventos),
`boot/` (kernel e serviços), `frontend/` (RetroArch), `hw/` (retrato do hardware),
`metrics/` (CPU por núcleo, temperatura, bateria e FPS a cada ~7 s) e `trace/` (rastreio
quando o RetroArch para de responder).

## 6. O que ainda não funciona (pendências)

Mega Drive e Master System (`picodrive`, P-30), arcade (romsets e BIOS, P-26), chiado
constante no alto-falante (volume analógico, P-29), relógio do menu (P-31), brilho pelo
menu (P-32). Lista completa em [PENDENCIAS.md](PENDENCIAS.md).
