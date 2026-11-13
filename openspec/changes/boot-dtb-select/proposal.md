# Proposal

## Why

Cada console sobe hoje com um DTB fixo: no GA36 ele vai anexado ao kernel numa imagem de
boot Android gravada no setor 172032, e trocar de painel exige gravar outra imagem com
`dd` pelo PC; no R36S o `boot.ini` aponta para um único DTB. Não há como o boot escolher
a descrição do hardware certa para uma variante (outro painel, outra revisão, um clone), nem
como o usuário escolher na hora quando a escolha automática falhar. O GA36 também guarda o
logo do boot dentro da área de fábrica, invisível pelo PC, enquanto o R36S lê o
`BOOT/logo.bmp`. O usuário pediu (2026-11-13) um boot mais simples e "universal": uma pasta
com os DTBs, uma escolha automática, uma escolha manual segurando uma tecla, como no
Android, e o logo externo e igual nos dois consoles. Esta change é o **degrau 1**: sem
escrever nem recompilar bootloader, sobre as cadeias de fábrica que já iniciam o cartão
único. O U-Boot próprio (P-43) só entra se este degrau não bastar.

## What Changes

- **Pasta de DTBs por SoC na `BOOT`** (`dtbs/a33/`, `dtbs/rk3326/`): cada DTB traz dentro
  de si um nó do Lume com o nome, a prioridade e as regras de reconhecimento da variante, e
  um deles é o padrão (o DTB de hoje). Pôr um DTB na pasta basta para o boot considerá-lo.
- **Escolha automática no initramfs**, igual nos dois consoles: leituras só de leitura do
  hardware (ADC, GPIO, presença de chips no I2C), a regra de maior prioridade que bater
  vence e, se nenhuma bater, fica o DTB padrão, com o boot igual ao de hoje.
- **Troca do DTB por kexec**: se o DTB escolhido não é o que o bootloader carregou, o
  initramfs reinicia o mesmo kernel com o DTB escolhido, no máximo uma vez por boot.
- **Escolha manual**: segurando a tecla de seleção ao ligar, o initramfs mostra na tela a
  lista dos DTBs do SoC; a escolha fica gravada na `ROMS`, separada por aparelho.
- **Escolha forçada pelo PC**: um arquivo de texto `BOOT/dtbs/force` com o nome do DTB, que
  funciona mesmo com a tela preta. Apagar o arquivo volta ao automático.
- **Confirmação na tela** (pedido do usuário, 2026-11-13): no primeiro boot com um DTB novo
  (diferente do padrão e nunca confirmado naquele aparelho), a tela pede para apertar A em
  15 s. Sem resposta, o kernel volta sozinho ao DTB anterior: a tela preta de um painel
  errado se resolve sem PC e sem desligar. Chegar ao frontend não basta como prova, porque
  com o painel errado o sistema sobe com a tela apagada.
- **Volta ao último DTB que funcionou**: um DTB que trava antes da confirmação é descartado
  no boot seguinte, que volta ao último que funcionou (ou ao padrão). O watchdog do SoC,
  armado antes do kexec, reinicia o aparelho sozinho quando o kernel novo trava.
- **Escolha por aparelho** (pedido do usuário, 2026-11-13): a escolha salva, os confirmados
  e os descartados ficam por aparelho (número de série do SoC), de modo que o cartão levado
  a outro GA36 com outro painel não leva a escolha do primeiro.
- **Logo único**: o `BOOT/logo.bmp`, que é o logo de fábrica do R36S, passa a ser o logo
  dos dois consoles. No GA36, o build grava o mesmo arquivo como `bootlogo.bmp` na FAT
  interna da área de fábrica, e o env do U-Boot de fábrica é editado para carregar o logo da
  `BOOT`, de modo que trocar o arquivo pelo PC muda o logo dos dois.
- **Provas no aparelho antes do código**: o que os U-Boots de fábrica aceitam (`if`/`test` e
  `fatwrite` no `boot.ini`, `fatload` da `BOOT` e `sunxi_bmp_display` no env do GA36), que
  teclas cada um já usa no boot, se o kexec funciona nos dois kernels, se o watchdog
  atravessa o kexec e se o kernel informa o número de série do SoC.
- O caminho do `dd` da imagem do painel 2 do GA36 continua valendo até a troca por kexec
  ser provada no GA36.

Fora do escopo: U-Boot próprio ou mainline (P-43, P-19, P-34); detecção do painel pelo ID
lido por DSI (só se uma prova mostrar que dá para ler sem driver de painel); menu às cegas
por piscadas do LED; perfis de userland por variante (mixer, autoconfiguração, taxa), que
continuam no P-33; o mapa completo do hardware (P-40).

## Capabilities

### New Capabilities

- `dtb-selection`: como o boot escolhe a descrição do hardware (DTB) do aparelho: a pasta
  por SoC, as regras dentro de cada DTB, o padrão, a escolha manual pela tecla, a escolha
  forçada pelo PC, a confirmação na tela, a persistência por aparelho, a volta ao último
  que funcionou e o registro no log.

### Modified Capabilities

- `system-image`: a `BOOT` da `console` ganha `dtbs/<soc>/`, o arquivo opcional
  `dtbs/force` e o kernel do GA36 como arquivo; o `logo.bmp` passa a valer para os dois
  consoles; a área de boot do GA36 leva o env editado e o `bootlogo.bmp` trocado.
- `device-support`: os DTBs dos consoles ficam em `BOOT/dtbs/<soc>/`; a troca de variante
  pelo PC passa a ser pelo `dtbs/force`, sem `dd`.

## Impact

- **Código**: `initramfs/init` e um utilitário novo em C para o initramfs (sondas, menu na
  tela, leitura de teclas por evdev); `kexec-tools` no initramfs; `src/r36os/image.py`
  (layout da `BOOT`), `src/r36os/vendor.py` (env do GA36 com CRC recalculado e
  `bootlogo.bmp` na FAT interna), `src/r36os/initramfs.py`; `board/r36s/boot.ini` (caminho
  do DTB); `board/*/dts/` (nó de detecção); fragmentos de kernel dos dois consoles
  (`CONFIG_KEXEC`, as teclas e o watchdog embutidos, `CONFIG_WATCHDOG_OPEN_TIMEOUT`); o
  `logd` (confirma o DTB quando o frontend sobe, se a confirmação na tela não pôde
  aparecer).
- **Testes**: unitários da escolha (precedência, regras, `force` inválido, volta ao último
  que funcionou, sem laço de kexec), do layout da `BOOT`, do env do GA36 (CRC) e do
  `bootlogo.bmp`; integração na VM do caminho padrão (sem kexec); provas no aparelho.
- **Usuário**: cartões precisam de `flash console --update` para receber o layout novo; a
  `ROMS` não muda de lugar.
- **Documentação**: `README.md` (como escolher o DTB: `force`, lista, confirmação na tela,
  escolha por aparelho), `docs/BRINGUP-GA36.md` e `docs/BRINGUP-R36S.md` (escolha do DTB,
  teclas, `force`), `docs/LOGS.md` (linhas da escolha), `docs/PENDENCIAS.md` (P-33 e P-43).
