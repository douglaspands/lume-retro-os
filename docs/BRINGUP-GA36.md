# GA36-MB V1.2: gravar, subir e conferir

Guia da primeira subida e da conferência de uma imagem nova no GA36 (Allwinner A33).
Validado no aparelho em 2026-11-11 (imagens `20261111-002830` a `20261111-134121`).

## 1. Gerar e gravar

```sh
uv run lume build console                         # 1ª vez: LUME_GA36_FACTORY e LUME_R36S_FACTORY com as cópias dos cartões originais (README)
uv run lume flash console /dev/sdX --full --eject # cartão novo: imagem + ROMS no resto do cartão
uv run lume flash console /dev/sdX --update --eject   # atualizar: preserva jogos, saves e ajustes
uv run lume eject /dev/sdX                     # ejetar depois de copiar jogos (sem senha)
```

- O `--full` cria a `ROMS` (exFAT) já com as pastas e a configuração de fábrica: dá para
  copiar os jogos antes do primeiro boot (`ROMS/roms/<sistema>/`, BIOS em `ROMS/bios/`).
- O `flash` avisa quando o cartão está no leitor USB `14cd:125d`, que corrompe gravações
  pequenas. Use outro leitor se puder; um cartão afetado aparece no boot como
  `partition 2 ... USB command block ("USBC")`.

## 2. Primeiro boot

- O kernel sobe pelo bootloader do fabricante (área de 128 MiB) e mostra as mensagens na
  tela; o menu do RetroArch aparece em cerca de 20 s.
- O primeiro boot só lê as marcas da `ROMS` (`roms OK clean: check skipped (flags 0x0000)` no
  `events.log`; com o volume sujo, `roms OK dirty: checked: ...`). Se ela não existir, é criada
  com o resto do cartão.
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
daemon de entrada `lume-input` (perfil `/usr/share/lume/input/ga36.conf`, change
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

`lume-input --list` mostra os dispositivos de entrada e o barramento de cada um.

## Pelo cabo USB

Ligue o PC na porta **OTG** do GA36, não na de carga (DC), e sem adaptador. O console
aparece no PC como **"Lume GA36"** (fabricante "Lume Retro OS"), com duas funções:

- **MTP:** a `ROMS` como armazenamento "ROMS" no gerenciador de arquivos;
- **rede USB:** o PC recebe `10.55.0.2` e o console fica em `10.55.0.1`:
  `ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null root@10.55.0.1` (root sem
  senha, só por esse cabo) e `uv run lume push` (atualização sem tirar o cartão; ver o
  `README.md`). Para o dia a dia use o `lume dev` (esperar, comando, tela, botões, log e
  autoteste, em [BUILD.md](BUILD.md)); o ssh direto fica para o que ele não cobre. O cartão
  vai de um console ao outro e só um deles fica no PC; ambos respondem em `10.55.0.1`, e
  `lume dev check --console ga36` recusa o R36S. Testar do PC sem reboot: `lume push --hot
  <fragmento>` e `lume dev watch <fragmento>` (só na RAM; ver "Testar no console pelo cabo"
  em [BUILD.md](BUILD.md)).

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
- no `boot/boot-<n>.log`, as mensagens `lume-usb:` e `umtprd:` (a saída do servidor MTP).

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

**2. Entrar no console:** `lume` (shell de root). Um comando só: `lume <comando>`. O
equivalente do `lume dev` (um comando por chamada, sem apelido): `.venv/bin/lume dev sh
<comando>`; `.venv/bin/lume dev wait` espera o console responder; `.venv/bin/lume dev
check --console ga36` roda o autoteste.

| Para quê | Comando |
|---|---|
| Bateria (%) e estado | `lume cat /sys/class/power_supply/axp20x-battery/capacity /sys/class/power_supply/axp20x-battery/status` |
| Versão do build | `lume cat /boot/VERSION` |
| Log do kernel | `lume dmesg` (ou `lume dmesg \| tail -n 30`) |
| Eventos do sistema | `lume cat /storage/logs/events.log` |
| Log do boot atual e seus eventos | `.venv/bin/lume dev log` |
| Saída do servidor MTP | `lume cat /run/lume/usb/umtprd.log` |
| Processos | `lume ps` |
| Reiniciar o USB (gadget, MTP, rede e ssh) | `lume start-stop-daemon -S -b -x /sbin/rc-service -- lume-usb restart` |
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
  arquivo vai pela entrada do comando (é assim que o `lume push` envia o build):

  ```sh
  lume 'cat > /storage/roms/<sistema>/jogo.zip' < jogo.zip                  # PC -> console
  lume 'cat /storage/logs/events.log' > events.log                         # console -> PC
  sha256sum jogo.zip ; lume sha256sum /storage/roms/<sistema>/jogo.zip     # conferir
  ```

**4. Atualizar o console:** `uv run lume push --build <carimbo>` (ver o `README.md`). Depois
do reboot o `push` espera o console voltar e confere o boot novo (número do boot, build do
`/boot/VERSION` e `boot OK completed` no `events.log`), terminando em `ok: boot N completed
with build X (...)`; `--no-wait` só reinicia. Detalhes em [BUILD.md](BUILD.md).

**Medido (2026-11-13):** com o build `20261113-192923`, o PC enumerou o "Lume GA36" em
high-speed, com MTP e NCM: o papel pelo pino ID funciona. Naquele build, o PC ficou sem
endereço (o `udhcpd` vem no `busybox-extras`, que faltava; corrigido no build seguinte).

**Módulos do kernel fora do `SYSTEM` (change `kernel-modules-image`, 2026-11-14):**
- Primeiro `push` com o build `20261114-013857`, saindo do `20261114-002340`: mandou os dois
  `SYSTEM` (agora sem módulos), os kernels e `ga36/modules` e `r36s/modules`, ~650 MB em
  376 s. No boot seguinte, `/lib/modules/6.18.62-lume/modules.dep` existe, o log de boot tem
  `lume: modules: ga36/modules (6.18.62-lume)`, o `bluetooth` sobe no boot e o
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
`lume flash --update`. Se a energia cair entre os dois `mv` da troca, o boot usa o `.old` e
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

- **Tela:** `lume-shot /tmp/s.png` (pacote `lume-input`) grava a imagem do que está na tela,
  lida do DRM; serve para o lume, o menu do RetroArch e os jogos. Do PC, um comando só faz o
  caminho todo (captura, `cat` pelo ssh e verificação do PNG):
  `.venv/bin/lume dev shot cache/tmp/tela.png`. Para comparar com a referência do GA36:
  `.venv/bin/lume dev shot --compare home` (ver [BUILD.md](BUILD.md)).
- **Botões pelo cabo:** `.venv/bin/lume dev keys 'a,down*3,wait:500,fn+start'` (o texto
  abaixo explica o que ele faz por dentro).
- **Botões:** escrever `struct input_event` de 32 bits (16 bytes: dois `long` de tempo, tipo,
  código e valor, seguidos de um `EV_SYN`) num nó de entrada. No `/dev/input/event3` (o
  controle virtual do `lume-input`) chegam ao lume e ao RetroArch. Combinações do
  `lume-input` (Fn+Start) vão no `/dev/input/event2` (o controle do kernel) e numa escrita só:
  o driver relê o estado real dos botões em poucos ms e solta o botão injetado.

### Medidas do lume-launcher (2026-11-14, build `20261114-143705`, boot 46)

- **Boot:** `boot OK completed: frontend in 32.5s from kernel`, mais ~0,9 s até o `lume-ui`
  ter o renderer pronto. O kernel e o `initramfs` terminam em 3,2 s; o resto é o OpenRC
  (P-58).
- **Fim do jogo até a grade:** 0,80–0,93 s em 3 rodadas (meta de 1 s), sempre no mesmo jogo
  de antes. Do aperto de Fn+Start até a grade, 1,70–1,78 s, dos quais 0,85–0,90 s são o
  RetroArch fechando.
- **Parado na grade:** `lume-ui` com 0,1% de um núcleo e 59 MB de RSS; o menu do RetroArch
  parado, 73% e 79 MB. No jogo, `lume-run` (696 KB) e `lume-input` (500 KB) sem CPU.
  Detalhes em [orcamento-de-performance.md](lume-launcher/orcamento-de-performance.md).

### Janela J1 da `lume-hud-actions` (2026-11-17, build atual, boot 168)

**Fontes da barra de status (tarefa 4.1):**

| Campo | GA36 (AXP223, `lima`) |
|---|---|
| Uso da GPU por cliente (`drm-engine-*` no `fdinfo`) | **não existe**: o `lima` do kernel 6.18 não tem `show_fdinfo` (o `fdinfo` dos fds do `renderD128` e do `card1` só traz `pos`, `flags`, `mnt_id`, `ino`) |
| devfreq da GPU (`/sys/class/devfreq/1c40000.gpu`) | `simple_ondemand`, 144/240/384 MHz, `cur_freq` e `trans_stat` legíveis; `load` vazio |
| `status` | `Charging` com o cabo USB, `Discharging` sem ele |
| `current_now` | positivo carregando (+100 a +346 mA), **negativo** descarregando (−371 a −390 mA num jogo LÖVE) |
| `voltage_now` | 4,25 V carregando a 100%; 4,18 a 4,17 V descarregando |
| `charge_now`, `charge_full` | ausentes |
| `charge_full_design` | 3000000 (3000 mAh) |
| `capacity` | 100 durante toda a prova |

**Menu pelo sistema (tarefa 4.6, D14):** passou nos três casos, com o programa de prova
rodando como `game` (o mesmo usuário do `lume-run`), sem `setcap`; o kernel não tem o Yama.
O usuário viu o retângulo sobre o último quadro e a volta normal do jogo, sem tela preta nem
quadro trocado, nos três:

| Caso | Pausa | Formato do quadro | Retângulo na tela em | Volta |
|---|---|---|---|---|
| RetroArch num jogo | `PAUSE_TOGGLE` (PLAYING → PAUSED) | XRGB8888 640x480 | 239 ms | quadro do jogo na 1ª tentativa, despausado |
| RetroArch travado de propósito (`SIGSTOP` antes) | sem resposta ao `GET_STATUS` em 1 s | XRGB8888 | 1143 ms (1 s de espera + 0,14 s) | quadro do jogo na 1ª tentativa |
| Jogo LÖVE | só o `SIGSTOP` | ARGB8888 | 79 a 86 ms | quadro do jogo na 1ª tentativa |

O fd do DRM duplicado pelo `pidfd_getfd` é o `card0` (`sun4i-drm`) do jogo; o `GETFB2` entrega
o handle do plano primário (33, CRTC 49) porque o fd é o mesmo arquivo aberto, master. O
`SETPLANE` nunca deu `EBUSY`. **Regra achada:** tudo o que o desenho cria vive no arquivo
aberto da aplicação; sem `RMFB`, `DESTROY_DUMB` e `GEM_CLOSE` ao fechar, os buffers ficam até o
jogo acabar, e a CMA acabou na terceira rodada (`CREATE_DUMB: Out of memory`).

### Governor por gargalo da `game-governor` (2026-11-18, builds `20261118-005049` a `-011308`, boots 180 a 182)

Medido pelo cabo, com o console no carregador (a corrente da bateria não vale nestas provas) e
os jogos abertos pelo `lume dev run` e deixados rodando (telas de título e demonstração; no GBA,
uma corrida com os karts da IA). Só números por sistema; nenhum nome de jogo.

**Sinais do controlador no kernel real:** o `fdinfo` dos arquivos do DRM do jogo traz
`drm-page-flips` no `card0` (`sun4i-drm`, patch 0036) e `drm-engine-gp`/`drm-engine-pp` no
`renderD128` (`lima`, patch 0035); o mesmo cliente aparece em dois ou três fds com o mesmo
`drm-client-id` (contado uma vez). O `GET_STATUS` do RetroArch dá o ritmo do core (patch 0004).

**O gargalo dos jogos simples (P-93):** o painel faz 55,7 vblanks/s. Com o vídeo na thread
principal do RetroArch, o core rodava na velocidade certa, mas poucas trocas de quadro chegavam
ao painel, com a CPU e a GPU quase paradas, e nenhum clock mudava isso:

| Caso (vídeo na thread principal) | Core (quadros/s) | Trocas no painel/s | Thread principal | GPU (`pp`) |
|---|---|---|---|---|
| NES, padrão do kernel | 60,3 | 42 | ~10% | 8% (144 MHz) |
| NES, GPU travada em 384 MHz | — | 43 | — | 5% |
| NES, GPU 384 MHz e CPU em `performance` | — | 47 | — | 5% |
| NES, `video_vsync` desligado | — | 43 | — | 4% |
| CPS-1, controlador ou padrão do kernel | 59,7 | 45 a 48 | 52% (1008 MHz) | 6 a 9% |
| GBA, perfil `gba` (1008 MHz) | 59,7 | 47 | 45% | 8% |

Com `video_threaded = "true"` (agora fixo no `retroarch-ga36.cfg`):

| Caso (vídeo em thread) | Core | Trocas no painel/s | Clock que o controlador escolheu |
|---|---|---|---|
| NES | 60,3 | 54,4 | CPU 720 MHz, GPU 144 MHz |
| CPS-1 | 59,8 | 54,3 a 54,6 | CPU 816 a 1008 MHz, GPU 144 MHz |
| CPS-1 com a barra de status ligada | 59,7 | 53,2 | CPU 1008 MHz |
| SNES (`snes9x2005_plus` do upstream) | 60,1 | 54,4 | CPU 816 MHz |
| GBA, tela de título, perfil `game` (sem o piso de 1008) | 59,7 | 55,1 | CPU 648 MHz |
| GBA, corrida, perfil `game` | 59,8 | 55,1 | CPU 912 MHz (thread em 67%) |

**Provas do controlador e dos ajustes:** o controlador marca `sync` a perda de quadros com a CPU
e a GPU ociosas (não sobe clock por ela) e desce o que sobra (linha
`power OK controller: cpu: 1008000=3.0s 912000=6.0s 816000=9.0s 720000=35.7s gpu: ... 144000000=43.8s up=0 down=5 ... sync=1`
num jogo de NES); com a primeira versão (queda abaixo de 95% numa janela só) ele oscilava no
CPS-1 com o vídeo em thread (`up=14 down=14`), corrigido com 90% e duas janelas (`up=0` na
prova seguinte). Perfil por jogo: uma linha `game <chave>` no `power.conf` com
`gpu_min=gpu_max=384000000`, `lume-power reload` e o jogo aberto de novo: `current gpulock`, GPU
travada em 384 MHz pela mão e a CPU no controlador (720 MHz), na velocidade cheia. Fn+Start
encerra um jogo normal (`end=quit-combo`) e um congelado de propósito com `SIGSTOP`
(`end=killed`, volta ao menu). O `snes9x2005_plus` novo abre e roda a 60,1.

**Custo no launcher parado (60 s, P-60):** o `logd` barato (1.2) com os filhos gastou 5,5 a 7,3%
de um núcleo (era ~30%; a meta de 1% ainda não foi alcançada). A thread `sugov:0` do `schedutil`
gastava **30%** com o `rate_limit_us` padrão do kernel (366 µs); com 50 ms, 6,9%; 100 ms, 4,4%;
200 ms, 2,8%. O `ga36.conf` passou a usar 100 ms no menu e 200 ms no launcher parado.

**DRAM (P-23):** o retrato mostra `PLL_DDR1` com sigma-delta ligado e o clock efetivo de 540 MHz
(controlador a 270 MHz), sem variação.

**Provas à mão do usuário (2026-11-18, J3):** o menu do sistema (Fn) abre durante um jogo com o
vídeo em thread; a marca de carga aparece e some ao ligar e desligar o carregador; os jogos de
CPS-1 e de GBA que tinham queda rodam lisos no perfil com o controlador por gargalo. As provas
com a bateria acabando de verdade (aviso e desligamento) ficaram para o P-98, por decisão do
usuário.

### `device-fixes` (2026-11-18)

**J1 (build `20261118-104230`, nomes antigos):** resultados no `design.md` da change (D6, D9,
D10, D11, D12, D15) e no P-95. Em resumo:
- read-ahead sem ganho claro (~21 MB/s; no máximo 5%);
- `Headphone` limpo até 63, sem chiado em silêncio;
- o fone corta o alto-falante por chave mecânica, sem detecção;
- suspensão `freeze` 10 de 10 pelo botão, com o gadget USB solto e religado em volta;
- RTC sobrevive a um desligamento de 6 min;
- **P-95 reproduzido a ~66 °C** (falha de temporização, não da luz de fundo).

**J0 (1.5), build `20261118-143150`, primeiro `lume push` depois da troca de nomes:**
- **Compilação e envio:** o build levou 1h26min (todos os pacotes armv7 e o kernel; o
  `out/repo` foi reassinado com a chave `lume.rsa`, 167 pacotes). O `push` antigo lia
  `/etc/lume/board`, ausente num console com os nomes velhos; passou a ler também o caminho
  antigo. O envio levou 3m41s e o boot 38 s.
- **Boot 193:** subiu até o menu com o kernel `6.18.62-lume`, o `frontend` em 20,5 s, a ROMS
  limpa e o `kernel OK no error messages`.
- **Nomes:** `rc-status` só com serviços `lume-*`; nenhum nome antigo nos runlevels nem no
  `inittab`; `/etc/lume` e `/run/lume` no lugar.
- **Cartão:** nenhum caminho do cartão precisou de migração (nenhum evento
  `persist OK migrated`); a indexação viu os mesmos 60 jogos.
- **`lume-index`:** aparece `crashed` no `rc-status` porque a varredura termina e o processo
  sai (o OpenRC espera um daemon). É cosmético e anterior à troca.

**Brilho desde o boot (9.16, código; falta a prova no aparelho, J2):** o device tree dos dois
painéis acende a luz de fundo no nível 7 (`default-brightness-level`, antes o 8 de fábrica;
do 7 para cima este GA36 pode mostrar a imagem quebrada, P-95) e o initramfs aplica o brilho
salvo (`ROMS/system/display/brightness`) logo depois de montar a ROMS, sem esperar nada; o
`lume-input` reaplica ao subir. Ver "Brilho salvo" em [LAUNCHER.md](LAUNCHER.md).

### Avaliação do coletor de logs e dos laços em segundo plano (2026-11-19, build `20261119-164004`)

Pedida pelo usuário para a `game-governor` 1.2 (P-60). Ticks próprios e dos filhos em
`/proc/<pid>/stat`, 60 s por medida:

| Processo | Launcher parado | Jogo de SNES |
|---|---|---|
| `lume-logd` (o coletor em C) | 0,85% de um núcleo (0,35 + 0,50 dos filhos) | 0,94% (0,31 + 0,63) |
| `usb-gadget` (`lume-usb`) | — | **5,08%** (0,68 + 4,40) |
| `persist`, `savesync`, `ssh-wifi` | — | 0,51%, 0,49%, 0,43% |
| `lume-powerctl` | — | 0,38% |
| `sugov:0` (`schedutil`) | 2,85% | — (governor `userspace` no jogo) |

O coletor cumpre a meta de 1% (os 5,5 a 7,3% de 2026-11-18 eram do coletor anterior em shell).
O sistema cria ~930 processos por minuto parado; quem os cria são os laços em shell de 1 s
(`usb-gadget`, `persist`, `savesync`, `ssh-wifi`), que leem o sysfs com `$(cat ...)` e dormem
com o `sleep` externo: P-112.

**Também visto:** o `logd` sobe antes do fuso ser aplicado (`lume-persist`) e grava em UTC até o
boot seguinte, enquanto o `lume-run` grava na hora local (P-112 cita, a corrigir junto).

### Laços sem processo por volta (`game-governor` 7.6, D20; 2026-11-19, builds `20261119-183440` e `-184744`, boots 219 e 220)

Medido pelo cabo com o `tests/device/loops_cost.sh` (60 e 120 s; o contador `processes` de
`/proc/stat` lido sem processo entre as duas fotos; a CPU de cada laço pelo
`se.sum_exec_runtime` de `/proc/<pid>/sched`, o tempo exato: os ticks cobram 10 ms inteiros a
um laço que acorda no tick do relógio):

| | Antes (build `20261119-164004`) | Depois, launcher parado | Depois, jogo de SNES |
|---|---|---|---|
| Processos novos no sistema | 945 por minuto | **24 por minuto** | 24 por minuto |
| Laços (`usb-gadget`, `persist`, `savesync`, `ssh-wifi`), % de um núcleo | 12,5% (ticks) | **0,78%** (0,73% em 120 s) | **0,17%** |
| `usb-gadget` | 8,4% (1,1 + 7,3 dos filhos) | 0,41% | 0,09% |
| `ssh-wifi` (opção desligada) | 1,1% | 0,24% | 0,05% |
| `persist`, `savesync` | 1,5%, 1,6% | 0,05%, 0,07% | 0,01%, 0,02% |
| `lume-logd` com os filhos | 0,7% | 0,95% em 120 s (0,51 + 0,44 dos filhos; em janelas de 60 s, 0,7 a 1,1%, conforme caem uma ou duas descargas) | 0,6% (0,29 + 0,31) |

**Achado:** sem processo nenhum, a primeira versão ainda gastava 1,26% parada. O shell do
busybox custa ~0,1 a 0,2 ms por chamada de função ou leitura do sysfs a 720 MHz, e o laço acorda
com a CPU no clock mais baixo: ~15 ms por volta do `usb-gadget`. A volta parada passou a ler só
o estado do UDC e o VBUS, de caminhos guardados; a guarda do FIFO olha o relógio a cada 32 voltas
e a procura do role switch (que o GA36 não tem) a cada 16.

**Funções conferidas no aparelho:** a rede e o SSH pelo cabo voltam depois dos dois reboots do
`push`; o cabo tirado e posto de volta pelo usuário (boot 220): `network: down` e
`device: disconnected` ao tirar, `network: up` 6 s depois de pôr e o SSH aceito 5 s depois, sem
nada à mão; os eventos do `lume-logd` (as linhas `otg`) já saem na hora local desde o boot (7.3); um save de teste de nome neutro em `saves/` aparece no `savesync.log` em menos de 2 s (o
jogo de SNES medido não grava save ao fechar); uma mudança de teste na configuração do RetroArch
chega ao `ROMS/system/retroarch/` depois do debounce, e a remoção também; o `inotifyd` do
`persist` é refeito quando o RetroArch cria uma pasta no jogo.

### Kernels de experimento (`device-fixes` 6.3, P-95 e P-25)

Variantes do kernel que **nunca entram na imagem padrão**, em `kernel/variants/ga36/<nome>/`
(patches aplicados depois de `kernel/patches/`, um `board.dtsi` opcional incluído no fim de
cada DTS e o `variant.toml`). O build compila no mesmo tree e na mesma pasta de build do
padrão, mas grava em `out/ga36/variants/<nome>/`, não publica nada em `out/repo` e arquiva
um build que o `latest` **não** aponta: só o kernel, os DTBs (no `e1`), o `VERSION` (com a
linha `kernel variant: ga36 <nome> (base <build>)`) e as imagens de boot dos painéis mudam
em relação ao build base. Um patch de variante só pode mexer em driver embutido no kernel
(`panel-ga36mb-jd9366.c`, `sun6i_mipi_dsi.c`); os módulos continuam os do padrão. No log de
boot, cada uma se anuncia com `experiment kernel <nome>: …`.

| Variante | O que muda | Link por via | Quadro |
|---|---|---|---|
| (padrão) | modo de 30 MHz pedido; o `pll-mipi` só chega a 297 × 6 / 5 = 356,4 MHz | 356,4 Mbit/s | 29,7 MHz / (1040 × 518) = **55,13 Hz** reais (o `retroarch-ga36.cfg` diz 55,69, falta medir) |
| `e4-slow` | pixel de 27,5 MHz (`pll-mipi` 297 × 10 / 9 = 330 MHz exatos), totais de fábrica | 330 (−7,4%) | 51,05 Hz |
| `e4-nonburst` | vídeo sem rajada com pulsos de sincronia (link em HS na linha toda) | 356,4 | 55,13 Hz |
| `e4-eotp` | pacote EoT depois de cada transmissão HS (`lcd_dsi_eotp = 1` da fábrica) | 356,4 | 55,13 Hz |
| `60hz` | pixel de 32,175 MHz (297 × 13 / 10 = 386,1 MHz exatos), front porch 275 (`htotal` 1035) | 386,1 (+8,3%) | 60,013 Hz |
| `60hz-porch` | link de hoje (29,7 MHz), front porch 196 (`htotal` 956) | 356,4 | 59,975 Hz |
| `e1` | só o DTB: DCDC1 (`vcc-io` e, pelo `dc1sw`, o painel) a 3,3 V | 356,4 | 55,13 Hz |

**Na janela (J2a), com o console no cabo e a bateria acima de 20%:**

```sh
uv run lume build --console ga36 kernel                    # o controle (padrão), vira o latest
uv run lume build --console ga36 kernel --variant e4-nonburst
uv run lume push --console ga36 --build <id impresso pelo build da variante>
# só nas variantes que mudam o quadro (e4-slow, 60hz, 60hz-porch), a cada boot:
uv run lume dev sh --console ga36 'echo video_refresh_rate = \"60.013430\" > /run/lume/retroarch-extra.cfg'
uv run lume push --console ga36                            # desfaz: volta ao latest (padrão)
```

O build da variante imprime o id, o comando de envio, o de desfazer e, quando o quadro muda,
a taxa do RetroArch (também no `variant.toml`). O `SLOTS.old` não desfaz um kernel: ele é o
conjunto anterior da raiz; quem volta o kernel é o `push` do `latest`, que manda de novo o
`ga36/zImage` e a imagem do setor 172032. **Se a variante não der imagem**, o console
continua respondendo pelo cabo (o painel não tem relação com o USB): `lume push --console
ga36`. **Se nem o cabo responder**, gravar pelo PC a imagem do painel 1 do build base no setor
172032 (ver "À mão" na seção 3.1, conferindo o SHA256 depois: leitor `14cd:125d`) e depois
`lume push`.

**Riscos não verificados:** o JD9366 não tem datasheet aqui (faixa de pixel clock e de
tensão); o `pll-mipi` a 330 e a 386,1 MHz não foi medido (hoje roda a 356,4); no `e1`, os
limites do microcontrolador do controle e de outros chips nas linhas PB/PF/PG/PH a 3,3 V são
desconhecidos (o A33-OLinuXino roda o DCDC1 a 3,3 V no mainline). Só o painel 1 existe neste
aparelho: o painel 2 fica sem prova.

## Cartão trocado com o console suspenso (2026-11-19)

Seis `gamelist.xml` do cartão apareceram com o tamanho de um XML e conteúdo de outro arquivo
(`game-experience-tuning` 9.1). O `events.log` e os `boot/boot-<n>.log` mostram a causa:

- o GA36 suspendeu no boot 204 (`sleep OK suspend freeze`, 04:41 UTC);
- o mesmo cartão iniciou no R36S nos boots 205 a 214 (14:28 a 16:04 -03), que gravou as listas;
- o cartão voltou ao GA36, que acordou às 19:39 (`sleep OK resume after 53863`) e gravou com a
  tabela de alocação do exFAT de antes da troca, guardada na RAM. As linhas do boot 204 caíram
  sobre o começo do boot 205 no `events.log`, e os boots 207 a 214 sumiram dele.

O kernel não percebe a troca (é o mesmo cartão, mesmo CID). Não foi o leitor USB do PC nem a
gravação atômica do índice. Os `gamelist.xml.corrupt` foram apagados do cartão. A correção
(conferir o contador de boots do cartão ao acordar e reiniciar sem gravar se ele mudou) é a
tarefa 9.3 da mesma change. Até ela entrar: **não tirar o cartão de um console suspenso**;
desligar antes.

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
