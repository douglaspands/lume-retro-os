# Design

## Context

Motivação em `proposal.md`. O estado medido no código em 2026-11-13:

| | GA36 (A33, armv7) | R36S (RK3326, arm64) |
|---|---|---|
| Controlador da OTG | MUSB (`USB_MUSB_SUNXI`, dual-role) | DWC2 (`USB_DWC2_DUAL_ROLE`) |
| PHY | `sun4i-usb-phy`, ID em PH8, VBUS lido de `usb_power_supply` (entrada USB do AXP) | `u2phy` `otg-port`, sem pino ID nem VBUS declarados |
| Gadget | `USB_GADGET=y`, **configfs desligado** | configfs e funções como módulos (`=m`) |
| Boot 23 (GA36) | `musb-hdrc ... MUSB HDRC host driver`: a porta sobe como host | ainda não medido |

- O build já instala os módulos do kernel no `SYSTEM` (`src/r36os/kernel.py`).
- No Alpine 3.24 existem `umtprd` 1.6.8, `dropbear`, `dropbear-convert` e
  `dropbear-openrc` 2026.91. O `busybox` já traz o `udhcpd`.
- O GA36 inicia pela imagem Android do setor 172032, que leva o kernel com o initramfs e o
  DTB do painel 1; a `BOOT` tem o `SYSTEM`, os DTBs e o `zImage` do kexec
  (`docs/BRINGUP-GA36.md`, seção 3).
- O root não tem senha e só entra pela serial de debug (`rootfs/configure.sh`).
- Os dois consoles têm uma porta de carga (DC) e uma porta OTG.

**Medição da porta OTG (tarefa 1.2, build `20261113-171347`, GA36 boot 24 e R36S boot 25,
2026-11-13).** Num mesmo boot, nesta ordem, cerca de 30 s cada; linhas `usb:` do `trace/`:

| Situação | GA36: `extcon` (VBUS, ID) / `musb` / `vbus` do AXP | R36S: `extcon` (VBUS, ID) / `udc` / `vbus` do RK817 |
|---|---|---|
| Nada ligado | `USB=0,USB-HOST=0` / `b_idle` / `0` | `USB=0,USB-HOST=0` / `not_attached` / `0` |
| Carregador na DC | **`USB=1`**`,USB-HOST=0` / `b_idle` / **`1`** | `USB=0,USB-HOST=0` / `not_attached` / **`1`** |
| PC na OTG (cabo de dados) | `USB=0,USB-HOST=0` / `b_idle` / `0` (**nada**) | `USB=0,USB-HOST=0` / `not_attached` / `0` (**nada**) |
| Adaptador OTG + pendrive | `USB=0,`**`USB-HOST=1`** / `b_idle`, pendrive **não** enumera | `USB=0,`**`USB-HOST=1`** / dwc2 enumera o pendrive (`host_devs=1`) |

- **Pino ID funciona nos dois:** o adaptador OTG é sempre reconhecido.
- **O VBUS da porta OTG não chega a nada que o kernel leia, nos dois.** O PC na OTG não
  muda nenhum campo. No GA36, o `VBUS` do PHY é o da entrada do AXP, que é a porta DC: o
  carregador aparece como se fosse VBUS da OTG (o risco previsto no D1).
- **Host:** o R36S já troca para host sozinho pelo ID; no GA36 o MUSB fica em `b_idle` com
  o ID baixo e o pendrive não enumera (fica para o P-38).
- Na linha `k` do R36S aparece `otg_switch: disabling` aos 33 s: o regulador de 5 V da
  OTG é desligado pelo kernel por estar sem uso (relevante para o host, P-38).

## Goals / Non-Goals

**Goals:**
- Ciclo de desenvolvimento sem tirar o cartão: ler logs, enviar build, reiniciar.
- Uma detecção de papel que o P-38 (host) reaproveite sem mudar o DTS de novo.
- As mesmas funções, nomes e endereços nos dois consoles.

**Non-Goals:**
- Suporte a Windows e macOS no PC além do que funcionar sem driver (o alvo é Linux com
  NetworkManager; ver Riscos).
- Acesso ao cartão antes do Linux (comando `ums` do U-Boot): fica como investigação na
  tarefa 1.3, sem entrega nesta change.

## Decisions

### D1. Papel pela detecção do hardware, medida antes de mexer no DTS

A primeira tarefa é medir, nos dois consoles, o nível do pino ID, o VBUS visto pelo PHY e o
papel do controlador em quatro situações: nada ligado, carregador na DC, PC na OTG,
adaptador OTG com pendrive na OTG. O resultado define o DTS:

```
              medicao (tarefa 1.1)
                     |
     +---------------+------------------+
     |                                  |
 ID e VBUS da OTG distinguem        nao distinguem (ex.: VBUS do PHY
 PC / carregador / adaptador        e a entrada do AXP ligada a DC)
     |                                  |
     v                                  v
 dr_mode = "otg": o kernel          dr_mode = "otg" com papel padrao
 troca o papel sozinho              device; host so por troca explicita
 (MUSB: ID + VBUS; DWC2: iddig      (/sys .../mode ou usb-role-switch),
  + bvalid do u2phy)                que o P-38 liga a um item do menu
```

A dúvida principal é o GA36: o DTS lê o VBUS da entrada USB do AXP. Se essa entrada for a
da porta DC, o carregador seria visto como PC.

**Decisão (medição da tarefa 1.2, 2026-11-13): ramo da direita, papel padrão device.**
Nenhum dos dois consoles vê o VBUS da OTG, então o PC não pode ser detectado. O pino ID
funciona, então a regra é: **ID alto (sem adaptador) = device; ID baixo = host.**

- **GA36:** sai `usb0_vbus_power-supply` do `usbphy`. Sem fonte de VBUS, o
  `sun4i_usb_phy0_get_vbus_det()` do kernel 6.18 informa VBUS presente ("Fallback: report
  vbus as high"), e com o ID alto o MUSB fica pronto como device; o carregador da DC deixa
  de passar pelo PHY. O ID (PH8) continua trocando para host; fazer o host enumerar fica no
  P-38.
- **R36S:** `usb-role-switch` e `role-switch-default-mode = "peripheral"` no `usb20_otg`.
  O `dwc2_drd_init()` registra o role switch e força o `bvalid` por override
  (`dwc2_ovr_init`), o que supre o VBUS que o `u2phy` não vê. A troca para host passa a ser
  explícita: o serviço `r36os-usb` lê o `USB-HOST` do `extcon` do `u2phy` e escreve o papel
  em `/sys/class/usb_role/*/role`. A mesma leitura serve ao P-38. **Alternativa descartada:** fixar
`dr_mode = "peripheral"` agora; seria mais rápido, mas o P-38 mexeria na mesma porta de novo
(decisão do usuário: projetar os dois papéis já).

### D2. Gadget composto por configfs, montado por um serviço do OpenRC

O serviço `r36os-usb` monta, no boot, um gadget "Lume" pelo configfs, com duas funções:
FunctionFS para o MTP e NCM para a rede. O gadget fica pronto desde o boot e é ligado ao
controlador da OTG (`UDC`); com `dr_mode = "otg"`, ele só enumera no PC quando o papel é
device. A ordem importa: o FunctionFS exige que o `umtprd` escreva os descritores antes de
ligar o `UDC`.

```
 boot: r36os-usb start
   configfs: gadgets/lume (VID/PID, serial, "Lume GA36" | "Lume R36S")
     +-- functions/ffs.mtp  --> mount -t functionfs mtp /dev/ffs-mtp --> umtprd
     +-- functions/ncm.usb0 --> usb0 10.55.0.1/30 --> udhcpd (so 10.55.0.2)
     |                                             --> dropbear (so 10.55.0.1:22)
     +-- UDC <- controlador da OTG (depois do umtprd pronto)
```

- **Configfs embutido nos dois kernels** (`=y`, inclusive no R36S, hoje `=m`): sem
  `modprobe` no caminho do boot e com o mesmo teste de config nos dois.
- **Script de shell, sem `libusbgx`:** o configfs são poucos `mkdir`/`echo`; um script em
  `rootfs/overlay/usr/libexec/r36os/usb-gadget` é testável no PC com um diretório falso,
  como os outros scripts do projeto.
- **IDs USB:** VID/PID de teste da Linux Foundation para gadgets (`1d6b:0104`, multifunction
  composite), como nos guias do configfs; nome e serial identificam o console. Um VID/PID
  próprio fica para quando houver distribuição pública (pergunta aberta).
- **Eventos:** o `logd` já roda um laço; ele passa a olhar `/sys/class/udc/*/state` e
  registra `usb OK device: connected|disconnected` na transição (`docs/LOGS.md`).

### D3. Arquivos por MTP (`umtprd`), não por mass storage

O `umtprd` exporta `/storage` (a `ROMS` montada) como um armazenamento "ROMS", com o dono
do frontend (`game`, uid 1000). O kernel continua dono do exFAT, então o RetroArch segue
rodando e não há risco de dois sistemas montarem a mesma partição.

**Alternativa descartada:** `f_mass_storage` com a partição 2. É mais rápido, mas exige
desmontar a `ROMS` (o RetroArch para) e um PC que não ejeta pode corromper o exFAT. Fica
como extra futuro, fora desta change.

### D4. Root por `dropbear` com chave, e chave de host única por PC

- O `dropbear` sobe só se `/boot/ssh/authorized_keys` existir, com `-s` (sem senha), `-p
  10.55.0.1:22` (só a rede USB) e sem encaminhamento (`-j -k`). Como a FAT não tem
  permissões, o serviço copia a lista para `/root/.ssh/authorized_keys` (camada em RAM)
  com modo `0600`.
- **Chave de host:** o `r36os flash --ssh-key <pub>` gera uma vez, no PC, uma chave
  ed25519 em `~/.config/r36os/ssh_host_ed25519` e a grava em `BOOT/ssh/` junto com a
  chave pública do usuário. No console, o `dropbearconvert` a converte para a RAM a cada
  boot. Assim:
  - o console não grava nada no cartão para ter SSH;
  - a chave privada fica na `BOOT`, que o MTP não expõe;
  - todos os cartões gravados por esse PC têm a mesma chave de host, e o `known_hosts`
    não avisa ao trocar de cartão ou de console.
- **Alternativas descartadas:** gerar a chave no console e guardá-la em `ROMS/system/`
  (ficaria visível por MTP e mudaria a lista de persistência do `boot-runtime`); gerar a
  cada boot (o PC avisaria de troca de chave a cada reinício); OpenSSH (maior que o
  `dropbear`, sem ganho aqui).
- O `flash --update` preserva `BOOT/ssh/` (lê antes e regrava depois), porque a `BOOT` é
  regravada inteira.

### D5. Rede USB fixa: console 10.55.0.1, PC 10.55.0.2, sem rota

Uma sub-rede `/30` com dois endereços, o `udhcpd` do busybox entregando só o `10.55.0.2` e
sem opções de roteador nem DNS: o PC não troca a rota padrão nem o DNS ao ligar o console.
O NetworkManager configura a interface NCM sozinho por DHCP. A faixa `10.55.0.0/30` foi
escolhida por ser incomum em redes domésticas; se colidir, muda-se uma constante no console
e no `push`.

### D6. `r36os push`: área temporária na ROMS, conferência no console, troca arquivo a arquivo

```
 PC (r36os push)                                console (ssh root@10.55.0.1)
  1. ssh: le VERSION, console (ga36|r36s),
     espaco livre em /storage
  2. rsync dos arquivos do build -------------> /storage/.lume-push/<build>/
  3. ------------------------------------------> sha256sum -c SHA256SUMS
                                                (para tudo se algo diferir)
  4. ------------------------------------------> mount -o remount,rw /boot
                                                para cada arquivo: cp para .new,
                                                sync, mv sobre o antigo
                                                VERSION por ultimo
                                                GA36: dd da imagem do painel 1 no
                                                setor 172032, sync, le de volta e
                                                compara o SHA256
                                                mount -o remount,ro /boot
  5. ------------------------------------------> rm -r /storage/.lume-push, reboot
```

- Os arquivos e os SHA256 vêm da pasta do build arquivado
  (`out/images/console/<build>/`), a mesma que o `flash` usa; a lista dos arquivos da
  `BOOT` sai do mesmo módulo que monta a FAT, para não divergir do `flash`.
- `VERSION` por último: um `push` interrompido deixa o `VERSION` antigo, e o próximo `push`
  reenvia tudo.
- A troca arquivo a arquivo exige, na `BOOT`, espaço livre para o maior arquivo (um
  `SYSTEM`, até 448 MiB); o `push` confere isso antes do passo 4.
- O `push` usa `ssh` com `UserKnownHostsFile` próprio (`~/.config/r36os/known_hosts`),
  preenchido com a chave de host do D4: não toca no `known_hosts` do usuário.

**Alternativa descartada:** gravar a `BOOT` inteira como imagem pelo cabo (como o `flash
--update`): exigiria desmontar a `BOOT` com o sistema rodando a partir dela (`SYSTEM` é um
arquivo dentro da `BOOT`), o que não é possível.

## Risks / Trade-offs

- **[O GA36 não distingue PC de carregador]** → D1: papel padrão device e troca explícita
  para host. O P-38 fica com o item de menu.
- **[Queda de energia no meio do passo 4 do `push`]** → `SYSTEM` antigo e novo podem ficar
  misturados e o console não iniciar. Mitigação: `.new` + `mv` por arquivo, `VERSION` por
  último, e o `flash --update` pelo leitor continua como recuperação. O `push` recusa rodar
  com bateria abaixo de 20% (lida de `power_supply` pelo SSH).
- **[Imagem de boot do GA36 gravada errada]** → o aparelho não inicia; recuperação pelo
  `flash --update`. Mitigação: leitura de volta com SHA256 antes do reboot, e o `push` só
  grava o setor 172032 se a imagem mudou.
- **[Trocar o `SYSTEM` em uso]** → o `SYSTEM` é um arquivo
  aberto pelo loop do squashfs; `mv` sobre ele troca a entrada de diretório e o arquivo
  antigo continua aberto até o reboot. Conferir na prova (tarefa 6.3) que o FAT do kernel
  aceita isso sem erro.
- **[Windows e macOS]** → o Windows 10/11 tem driver de NCM e de MTP; o macOS não tem MTP
  nativo. Fora do alvo; documentado.
- **[Chave privada de host na BOOT]** → quem tem o cartão na mão lê a chave e pode se passar
  pelo console. Aceito: quem tem o cartão já tem tudo; a chave serve a um cabo, não a uma
  rede.
- **[Consumo e tempo de boot]** → o `umtprd` precisa estar rodando antes do `UDC`, mesmo
  sem cabo; o `dropbear` e o `udhcpd` só sobem quando a `usb0` fica ativa. Custo medido na
  tarefa 4.4 (memória e tempo de boot até o frontend).

## Migration Plan

- Cartões existentes: sem a opção `--ssh-key`, nada muda além do MTP, que aparece ao ligar
  o cabo. Para ter root pelo cabo, um `flash --update --ssh-key ~/.ssh/id_ed25519.pub`
  pelo leitor, uma vez; depois disso, `r36os push`.
- Rollback: tirar `BOOT/ssh/` desliga o SSH; o serviço `r36os-usb` pode ser desligado sem
  afetar o resto do boot.

## Open Questions

- VID/PID próprio para uma distribuição pública (não muda o design: é uma constante).
- Se o U-Boot de fábrica do GA36 tem o comando `ums` (tarefa 1.3): se tiver, vira uma
  pendência própria de acesso ao cartão antes do Linux.
  **Resposta (2026-11-13, strings de `.cache/vendor/ga36-factory-128M.bin`, só leitura):**
  o U-Boot `2017.09-g05bceb2-dirty` **não tem `ums`**. Tem o código USB da Allwinner
  (`sunxi_usb`): o comando `mass_test` ("do a usb mass test"), o modo `efex` (gravação do
  PhoenixSuit) e um "Android Fastboot". Os nomes `ums_*` e `mass_storage` da área são de um
  kernel Linux de recuperação, não do U-Boot. Se o `mass_test` expõe o cartão ao PC e como
  chegar a ele sem a serial (env em 139264, tecla no boot) ficou como P-49.
