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
| `logo.bmp` | logo do boot lido pelo U-Boot do R36S (o de fábrica dele), BMP 640x480 de 24 bits; o GA36 mostra o mesmo arquivo da FAT interna e não lê este |
| `dtbs/a33/` | DTBs do GA36: `sun8i-a33-ga36-mb-v1.2-panel1.dtb` (`ga36-panel1`, o padrão) e `sun8i-a33-ga36-mb-v1.2-panel2.dtb` (`ga36-panel2`) |
| `dtbs/rk3326/` | DTB do R36S: `rk3326-r36s-v5.dtb` (`r36s-v5`, o padrão) |
| `dtbs/rk3326/vendor/` | DTBs de clones do R36S convertidos no PC (`<lume,id>.dtb`, cerca de 170), lidos só quando nomeados (README, "Clones do R36S") |
| `dtbs/force` | opcional, criado pelo usuário: o nome do DTB a usar (seção 3.1) |
| `ga36/` | `SYSTEM`, `zImage` (o kernel com que a imagem de boot do setor 172032 é regravada na troca de DTB) e `modules` (os módulos do kernel, montados em `/lib/modules`) |
| `r36s/` | `SYSTEM`, `Image` e `modules` |

A `BOOT` tem só o que os consoles leem. O GA36 inicia pela imagem de boot do setor 172032,
fora da `BOOT`; as imagens dos dois painéis ficam na pasta do build no PC
(`out/images/console/<build>/ga36-android-boot-panel{1,2}.img`, com o SHA256 no
`SHA256SUMS`).

**Logo:** o GA36 mostra o `bootlogo.bmp` da FAT interna da área de fábrica (setor 73728),
que já é o mesmo arquivo do `BOOT/logo.bmp` do R36S (SHA256 `01a2178e…`, conferido pelo
`test_ga36_factory_logo_is_the_boot_logo`): os dois consoles mostram o mesmo logo e o build não
grava nada na área de fábrica. **Trocar o `BOOT/logo.bmp` pelo PC não muda o logo do GA36:** o
U-Boot de fábrica lê arquivos da `BOOT`, mas o `sunxi_bmp_display` não desenha um BMP dela a
partir do `bootcmd` (prova 1.4 de `boot-dtb-select`). Isso fica para o bootloader próprio (P-43,
item 5).

### 3.1 Trocar o painel

O bootloader sempre inicia com o painel 1 (a imagem de boot do setor 172032, com o DTB do
painel 1 anexado). No initramfs, o `lume-bootsel` olha `BOOT/dtbs/a33/` e decide, nesta
ordem: o arquivo `BOOT/dtbs/force`; a lista na tela (tecla segurada ao ligar); a volta ao
último DTB que funcionou; a escolha salva da lista; o aprendido; as regras de cada DTB; o
padrão. Se o escolhido não é o que está rodando, o `lume-bootsel` regrava a imagem de boot
do setor 172032 com o `ga36/zImage` e o DTB escolhido, confere lendo de volta e reinicia o
console (D16: o kexec não funciona no A33, ver o `tasks.md` da change, 8.6). O início
seguinte pergunta na tela se o painel serve (A em 15 s); sem resposta, regrava a imagem do
DTB anterior e reinicia de novo. Os dois painéis usam o mesmo controlador, que responde o
ID `000000` (nunca gravado), então nenhuma regra os distingue: com a tela funcionando, a
escolha entre eles é da lista ou do `force`; com a tela muda (driver sem resposta), a busca
sozinha testa o outro painel.

- **Tela preta, pelo PC:** escrever `ga36-panel2` em `BOOT/dtbs/force`. Apagar o arquivo
  volta ao automático. Um nome que não existe é ignorado (motivo no log).
- **Pela tecla:** segurar **Vol-** ao ligar abre a lista; direcional ou volume navegam e
  **A** confirma. A escolha fica salva em `ROMS/system/etc/dtb-a33-<serial>.conf` (um por
  aparelho; `dtb-a33.conf` sem número de série; o GA36 não tem: nem `soc0` nem
  `/serial-number` do U-Boot) e "Automatic" apaga a escolha. **Não ligue segurando Vol+:**
  ele cai na faixa de fastboot do U-Boot de fábrica, que entra no modo USB da Allwinner
  (`1f3a:efe8`) sem tela até desligar. Vol-, Start, Select e A não mudam nada no U-Boot
  (prova 1.3 de `boot-dtb-select`, boots 122 a 126).
- **Se o DTB escolhido não chegar ao menu**, desligue e ligue: o boot seguinte volta ao
  último DTB que funcionou (`reason: fallback` no log).
- **Log:** `boot/boot-<n>.log` tem `lume-bootsel: selected <id> (reason: …)`, e o
  `hw/boot-<n>.txt` tem `dt in use` (formato em `docs/LOGS.md`).

**Lista e `force` provados (2026-11-16, build `20261116-161851`):** com o Vol- segurado ao
ligar a lista abre (boots 129 a 131; o patch `0034` lê o LRADC já com a tecla segurada), a
escolha vale no boot seguinte e "Automatic" a apaga. Com `force` = `ga36-panel2` num GA36 de
painel 1 (boot 132): o primeiro início gravou a imagem do painel 2 no setor 172032 e reiniciou;
com o DTB do painel 2 a tela ficou preta com riscos (a sequência do painel 2 num painel 1), a
pergunta não pôde ser vista e, em 15 s, o aparelho regravou o painel 1 e reiniciou sozinho; o
início seguinte registrou `force ignored: ga36-panel2 was discarded on this device (bad)` e
seguiu no painel 1. Confirmar o painel 2 com A só se prova num GA36 com o painel 2.

**À mão, sem o `lume-bootsel`** (por exemplo, se o sistema não chega ao initramfs): gravar
a imagem de boot do painel 2, da pasta do build gravado no cartão, no setor 172032, pelo PC:

```sh
sudo dd if=out/images/console/<build>/ga36-android-boot-panel2.img of=/dev/sdX \
    bs=512 seek=172032 conv=notrunc,fsync
```

Para voltar ao painel 1, a mesma coisa com `ga36-android-boot-panel1.img`. O `<build>` é o
do `BOOT/VERSION`: a imagem de boot leva o kernel e o initramfs, que precisam ser do mesmo
build do `ga36/SYSTEM`.

## 4. Controle

O driver do kernel junta os botões e os dois analógicos num único "GA36-MB Gamepad". O
daemon de entrada `r36os-input` (perfil `/usr/share/r36os/input/ga36.conf`, change
`lume-launcher`, D8) captura esse dispositivo e os botões de volume (LRADC) com exclusividade e
publica um controle virtual com o **mesmo nome**, então a autoconfiguração do RetroArch
(`/usr/share/libretro/autoconfig/udev/GA36-MB Gamepad.cfg`) não muda: A, B, X, Y, L1, R1, L2,
R2, Start, Select, direcional, L3, R3 e os dois analógicos. A regra do udev esconde do
RetroArch só o dispositivo do kernel (`BUS_HOST`); o virtual é `BUS_VIRTUAL`.

- **Fn sozinho** abre o menu do RetroArch quando é solto; **Start + Select** também abre.
- **Fn+Start** encerra o jogo aberto pelo launcher e volta à lista (fora de um jogo, nada
  acontece).
- **Volume**: os botões mudam o controle `DAC` do `GA36MB` em passos de 3%, em qualquer
  programa.
- No menu, A confirma e B volta.

`r36os-input --list` mostra os dispositivos de entrada e o barramento de cada um.

## Pelo cabo USB

Ligue o PC na porta **OTG** do GA36, não na de carga (DC), e sem adaptador. O console
aparece no PC como **"Lume GA36"** (fabricante "Lume Retro OS"), com duas funções:

- **MTP:** a `ROMS` como armazenamento "ROMS" no gerenciador de arquivos;
- **rede USB:** o PC recebe `10.55.0.2` e o console fica em `10.55.0.1`:
  `ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null root@10.55.0.1` (root sem
  senha, só por esse cabo) e `uv run r36os push` (atualização sem tirar o cartão; ver o
  `README.md`).

**Como funciona no GA36:** o papel da porta vem só do pino ID (PH8): sem adaptador, o MUSB
fica pronto como device. Uma medição anterior de 2026-11-13 dizia que o VBUS da porta OTG não
chegava a nada que o kernel lesse e que a entrada USB do AXP era a da porta DC. **A prova de
2026-11-13 com o build `20261113-221126` (commit `d5ba1b9`, `x-powers,drive-vbus-en` no AXP)
mostrou o contrário:** só com o cabo do PC na porta OTG, nada na DC, `axp20x-usb` fica
`present=1` e `online=1`, e a bateria carrega (`status=Charging`, 152 mA com 4,25 V, quase
cheia). O console carrega pelo cabo do PC. Ainda falta medir se o `online` cai ao tirar o cabo
e se um carregador na DC também acende o `axp20x-usb` (as duas entradas podem ser a mesma).

**Diagnóstico:**
- a linha `usb:` do `ROMS/logs/trace/boot-<n>.log` mostra o PHY (`extcon`), o modo do MUSB e
  o estado do gadget (`udc=…:configured` com o PC ligado);
- no `events.log`, `usb OK device: connected|disconnected`, `network: up|down` e
  `ssh: login accepted`;
- no `boot/boot-<n>.log`, as mensagens `r36os-usb:` e `umtprd:` (a saída do servidor MTP).

### Guia rápido pelo cabo (sem precisar de ajuda)

Todos os comandos rodam no PC. Para não repetir as opções do ssh, crie um apelido no
`~/.bashrc`:

```sh
alias lume='ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR root@10.55.0.1'
```

**1. O PC está vendo o console?**

```sh
lsusb -d 1d6b:0104          # deve listar "Linux Foundation Multifunction Composite Gadget"
ip -br addr | grep 10.55    # a interface enp...u...i1 com 10.55.0.2/30
journalctl -k -f            # ao ligar o cabo: "Product: Lume GA36" e "cdc_ncm ... usb0"
```

Se o `lsusb` não mostra nada: o console terminou de ligar? O cabo está na porta OTG? O cabo
transmite dados (muitos só carregam)? Teste outro cabo ou outra porta do PC.

**2. Entrar no console:** `lume` (shell de root). Um comando só: `lume <comando>`.

| Para quê | Comando |
|---|---|
| Bateria (%) e estado | `lume cat /sys/class/power_supply/axp20x-battery/capacity /sys/class/power_supply/axp20x-battery/status` |
| Versão do build | `lume cat /boot/VERSION` |
| Log do kernel | `lume dmesg` (ou `lume dmesg \| tail -n 30`) |
| Eventos do sistema | `lume cat /storage/logs/events.log` |
| Saída do servidor MTP | `lume cat /run/r36os/usb/umtprd.log` |
| Processos | `lume ps` |
| Reiniciar o USB (gadget, MTP, rede e ssh) | `lume start-stop-daemon -S -b -x /sbin/rc-service -- r36os-usb restart` |
| Reiniciar o console | `lume reboot` |

- O restart do USB derruba a rede do cabo por uns 2 s, e o ssh volta sozinho. Ele precisa
  rodar desligado da sessão (`start-stop-daemon -b`), senão o ssh cai no meio e o serviço
  fica parado. O `setsid` do busybox não tem `-f`.
- O sistema do console é só leitura com uma camada em RAM: uma mudança feita pelo ssh fora
  da `ROMS` (`/storage`) some no próximo boot. Bom para testar, ruim para guardar.

**3. Arquivos por MTP**

O gerenciador de arquivos mostra "Lume GA36". Pelo terminal:

```sh
gio mount -li | grep -A3 Lume                        # o volume e o endereço mtp://
gio mount mtp://Lume_Retro_OS_Lume_GA36_<serial>/    # montar
gio list mtp://Lume_Retro_OS_Lume_GA36_<serial>/ROMS/
gio copy arquivo.zip mtp://Lume_Retro_OS_Lume_GA36_<serial>/ROMS/roms/<sistema>/
gio mount -u mtp://Lume_Retro_OS_Lume_GA36_<serial>/ # desmontar
```

- Copie para dentro de uma pasta (`ROMS/roms/<sistema>/`, `ROMS/bios/`…). Uma cópia para a
  raiz da `ROMS` pelo GNOME falhou ("Não foi possível escrever neste local") na prova de
  2026-11-13, ainda com o problema do kernel descrito abaixo.
- Se o MTP não montar ("Não foi possível abrir o dispositivo MTP" ou "Unable to read device
  information"): reinicie o USB do console (tabela acima) e monte de novo. O ssh continua
  sendo o caminho garantido para ler `logs/`, porque não depende do MTP.
- Para copiar sem MTP, use o ssh. O console não tem `scp`, `sftp` nem `rsync`, então o
  arquivo vai pela entrada do comando (é assim que o `r36os push` envia o build):

  ```sh
  lume 'cat > /storage/roms/<sistema>/jogo.zip' < jogo.zip                  # PC -> console
  lume 'cat /storage/logs/events.log' > events.log                         # console -> PC
  sha256sum jogo.zip ; lume sha256sum /storage/roms/<sistema>/jogo.zip     # conferir
  ```

**4. Atualizar o console:** `uv run r36os push --build <carimbo>` (ver o `README.md`).

**Medido (2026-11-13):** com o build `20261113-192923`, o PC enumerou o "Lume GA36" em
high-speed, com MTP e NCM: o papel pelo pino ID funciona. Naquele build, o PC ficou sem
endereço (o `udhcpd` vem no `busybox-extras`, que faltava; corrigido no build seguinte).

**Módulos do kernel fora do `SYSTEM` (change `kernel-modules-image`, 2026-11-14):**
- Primeiro `push` com o build `20261114-013857`, saindo do `20261114-002340`: mandou os dois
  `SYSTEM` (agora sem módulos), os kernels e `ga36/modules` e `r36s/modules`, ~650 MB em
  376 s. No boot seguinte, `/lib/modules/6.18.62-r36os/modules.dep` existe, o log de boot tem
  `lume: modules: ga36/modules (6.18.62-r36os)`, o `bluetooth` sobe no boot e o
  `modprobe uhid` carrega e descarrega. O `zram` é embutido no kernel (`CONFIG_ZRAM=y`) e não
  aparece no `lsmod`; o `zram0` fica ativo como swap.
- Mudança só de kernel (build `20261114-022015`, `CONFIG_DUMMY=m` temporário no
  `board/ga36/kernel.config`): os dois `SYSTEM` e todos os arquivos do R36S saíram com o mesmo
  SHA256, e o `push` mandou só `ga36/modules`, `ga36/zImage` e `VERSION` (~9 MB) e a imagem
  de boot do painel 1, em 60 s no total (10 s descompactando a imagem no PC), contra ~650 MB
  em 376 s antes. No boot seguinte, o `modprobe dummy` carrega o módulo novo.
- Sem a imagem (`ga36/modules` renomeado pelo `ssh`, boot 37): o RetroArch abre,
  `/lib/modules` fica vazio, e o log de boot e o `events.log` têm
  `ERROR: BOOT has no ga36/modules; starting without kernel modules`. Com o arquivo de volta,
  o boot 38 monta os módulos de novo.
- Antes desse `push`, a `BOOT` tinha só 313 MiB livres: cada `push` anterior que trocou o
  `SYSTEM` deixou o antigo como cadeia de clusters perdida na FAT (ele é apagado ainda aberto
  pelo loop e o desligamento não libera). O `fsck.vfat -a` pelo PC as salvou como 4
  `FSCK000N.REC` de 283 MB, apagados depois pelo `ssh`.

**Troca sem vazamento (change `push-boot-swap`):** desde essa change, o `push` renomeia o
`ga36/SYSTEM` e o `ga36/modules` em uso para `.old` em vez de apagá-los, então nada aberto
perde o nome, a `BOOT` volta a somente leitura antes do reboot e nenhum cluster se perde. O
`push` seguinte apaga os `.old` antes de copiar e conta esse espaço. Se a `BOOT` já tiver
espaço perdido (de `push` antigos ou de um corte de energia), o `push` avisa com
`warning: BOOT has <N> MiB in lost clusters` e segue; a recuperação é pelo PC, com o cartão
no leitor: `sudo fsck.vfat -a /dev/sdX1` e apagar os `FSCK*.REC` da raiz da `BOOT`, ou
`r36os flash --update`. Se a energia cair entre os dois `mv` da troca, o boot usa o `.old` e
o log tem `ERROR: BOOT has no ga36/SYSTEM; using ga36/SYSTEM.old from the previous build`.


**Prova no GA36 (2026-11-14):**
- **Cartão sujo:** o primeiro `push` com a change (build `20261114-030914`) avisou
  `BOOT has 276 MiB in lost clusters` (`df` 921 672 KiB contra `du` 638 252 KiB) e seguiu.
  Era mais um `SYSTEM` vazado por um `push` antigo. O `fsck.vfat -a` pelo PC o salvou como
  `FSCK0000.REC` (290 222 080 bytes, começando com `hsqs`). Os arquivos da `BOOT` conferiram
  com o build, e o `.REC` foi apagado pelo ssh, não pelo leitor `14cd:125d`. Nesse mesmo
  `push`, a troca do `ga36/modules` em uso deixou o `modules.old`, e o `remount,ro` passou.
- **Dois `push` que trocam o `ga36/SYSTEM`** (builds `20261114-032036` e
  `20261114-033137`, com um marcador provisório no overlay): nos dois, sem aviso e com o
  `remount,ro` aceito antes do reboot. Antes desta change, essa troca dava "Resource busy".
  O `ga36/SYSTEM.old` ficou com o SHA256 do `SYSTEM` do `push` anterior, e o `.old` mais
  velho foi apagado antes da cópia. O `r36s/SYSTEM` não virou `.old`. No boot seguinte, a
  `BOOT` estava em `ro` e sem linhas `ERROR`.
- **Depois:** `df` = `du` = 920 376 KiB. O `fsck.fat -n` (binário do `dosfstools` do
  Alpine armv7 levado ao `/tmp` do console pelo ssh, só leitura) terminou com código 0:
  `21 files, 230094/523260 clusters`, sem clusters sem dono.

### Adaptador OTG: controles, teclado e pendrive (só com hub alimentado)

**A porta OTG do GA36 não fornece energia.** Com um adaptador OTG, o console troca para host
(o pino ID funciona), mas nada ligado direto nele acende. Medido em 2026-11-14: o kernel liga
o pino DRIVEVBUS do AXP223, mas a porta fica sem 5 V, e o log do kernel mostra
`musb-hdrc ... VBUS_ERROR in a_wait_vrise`. O pino que liga os 5 V, se existir, está no P-54.

**Com um hub USB alimentado (fonte própria) na porta OTG, o host funciona:**

- **Controle USB:** reconhecido pelo RetroArch como jogador 2; o controle do console continua
  como jogador 1. Qualquer controle mexe no menu (*Configurações → Entrada → Todos os usuários
  controlam o menu*, ligado de fábrica). Testado com um controle Xbox 360 com fio.
- **Teclado e mouse:** funcionam no menu (testado com um receptor sem fio).
- **Pendrive:** cada partição `vfat`, `exfat` ou `ext4` aparece em `/storage/usb/<rótulo>`
  (*Carregar conteúdo* → `/storage/usb/`) e é desmontada ao tirar. Partições de outros tipos
  (por exemplo, `iso9660` de um pendrive de instalação) ficam de fora, com um aviso
  `usb FAIL storage` no `events.log`.
- Hubs USB-C com vídeo mostram um dispositivo a mais sem driver (classe Billboard): é normal.

O `events.log` registra cada troca na linha `usb OK otg: ... musb=a_host ... host_devs=<n>`
e cada pendrive (`storage: mounted|removed`). Para voltar ao PC, tire o hub e ligue o cabo.

**MTP no GA36 (2026-11-13, build `20261113-221126`):** rede e ssh funcionam pelo cabo, mas o
GNOME não montava o MTP. Causa: no kernel, o driver MUSB descarta o pacote que chega antes
de o `umtprd` voltar a ler o endpoint (commit upstream `3fc137386c46`), e o PC manda o
próximo pedido MTP uns 30 µs depois de cada resposta. Medido do PC: sem intervalo entre os
pedidos, o primeiro já se perde; com 5 ms, 50 de 50 respondidos. A correção é o patch
`0028` do kernel (tarefa 3.6 da change `usb-device-access`). Sem ele, uma tentativa às vezes
monta, depois de reiniciar o USB do console. Dois detalhes do `umtprd` 1.6.8, sem efeito
aqui: a resposta "sessão já aberta" sai com 13 bytes em vez de 16, e o gid do armazenamento
recebe o uid (os dois são 1000).

### Ver a tela e apertar botões pelo cabo

- **Tela:** `r36os-shot /tmp/s.png` (pacote `r36os-input`) grava a imagem do que está na tela,
  lida do DRM; serve para o lume, o menu do RetroArch e os jogos. Como o `dropbear` não tem
  `scp`, a imagem vem pelo ssh com `cat`.
- **Botões:** escrever `struct input_event` de 32 bits (16 bytes: dois `long` de tempo, tipo,
  código e valor, seguidos de um `EV_SYN`) num nó de entrada. No `/dev/input/event3` (o
  controle virtual do `r36os-input`) chegam ao lume e ao RetroArch. Combinações do
  `r36os-input` (Fn+Start) vão no `/dev/input/event2` (o controle do kernel) e numa escrita só:
  o driver relê o estado real dos botões em poucos ms e solta o botão injetado.

### Medidas do lume-launcher (2026-11-14, build `20261114-143705`, boot 46)

- **Boot:** `boot OK completed: frontend in 32.5s from kernel`, mais ~0,9 s até o `lume-ui`
  ter o renderer pronto. O kernel e o `initramfs` terminam em 3,2 s; o resto é o OpenRC
  (P-58).
- **Fim do jogo até a grade:** 0,80–0,93 s em 3 rodadas (meta de 1 s), sempre no mesmo jogo
  de antes. Do aperto de Fn+Start até a grade, 1,70–1,78 s, dos quais 0,85–0,90 s são o
  RetroArch fechando.
- **Parado na grade:** `lume-ui` com 0,1% de um núcleo e 59 MB de RSS; o menu do RetroArch
  parado, 73% e 79 MB. No jogo, `lume-run` (696 KB) e `r36os-input` (500 KB) sem CPU.
  Detalhes em [orcamento-de-performance.md](lume-launcher/orcamento-de-performance.md).

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
