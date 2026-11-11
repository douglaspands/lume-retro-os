# GA36-MB V1.2: gravar, subir e conferir

Guia da primeira subida e da conferência de uma imagem nova no GA36 (Allwinner A33).
Validado no aparelho em 2026-11-11 (imagens `20261111-002830` a `20261111-134121`).

## 1. Gerar e gravar

```sh
uv run r36os build ga36                         # 1ª vez: R36OS_GA36_FACTORY com a área de boot do cartão original (README)
uv run r36os flash ga36 /dev/sdX --full --eject # cartão novo: imagem + ROMS no resto do cartão
uv run r36os flash ga36 /dev/sdX --update --eject   # atualizar: preserva jogos, saves e ajustes
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

## 3. Trocar o painel

A imagem usa o painel 1 (o do firmware de fábrica). Se a tela ficar preta ou com cores
erradas, grave a imagem de boot do painel 2 no setor 172032, pelo PC:

```sh
sudo dd if=/run/media/$USER/BOOT/android-boot/android-boot-panel2.img of=/dev/sdX \
    bs=512 seek=172032 conv=notrunc,fsync
```

Para voltar ao painel 1, a mesma coisa com `android-boot-panel1.img`.

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
