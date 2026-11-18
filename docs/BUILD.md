# Build: proteção de calor do PC

O `r36os build` e o `r36os pkg` rodam por horas com o processador no limite. A proteção de
calor (design D15 da change `build-speed`) vigia a temperatura durante todo o build e
**pausa os containers** quando o PC esquenta demais, em vez de deixar o PC desligar.

## Como funciona

- Uma thread lê a temperatura a cada 2 s: a do processador e a do disco onde fica o cache do
  build (achado pelo `/proc/self/mountinfo`): `nvme` Composite num NVMe, `drivetemp` num SSD
  ou HD SATA. Outros discos do PC não contam.
- Todo container do build e do `r36os pkg` leva o rótulo `r36os.build=1`; é por ele que a
  proteção encontra o que pausar (`podman ps --filter label=r36os.build=1`).
- Quando a CPU chega ao limite, ou o disco do build chega a 5 graus do seu próprio máximo, os
  containers são pausados (`podman pause`).
- A CPU precisa esfriar **10 graus abaixo do limite** para o build continuar
  (`podman unpause`).
- Se a CPU continuar acima de **92 C por 60 s com o build pausado**, os containers são
  encerrados e o build aborta com a leitura e o sensor. Nada fica pausado depois que o build
  termina, falha ou aborta.

Só o sensor do próprio processador é confiável (`k10temp` Tctl, `zenpower`, `coretemp`
Package). As entradas auxiliares da placa-mãe (`nct6798` AUXTIN*) leem lixo quando nada está
ligado e nunca são usadas.

**Disco SATA:** o Linux só expõe a temperatura de um disco SATA com o módulo `drivetemp`. Sem
ele, a linha do começo do build diz `no sensor for the build disk (SATA: load the drivetemp
module)` e a proteção segue só com a CPU. Para carregar agora e em todo boot:

```
sudo modprobe drivetemp
echo drivetemp | sudo tee /etc/modules-load.d/drivetemp.conf
```

## Limites

| Medida | Valor |
| :--- | :--- |
| Limite da CPU (pausa) | 85 C (`R36OS_TEMP_MAX`) |
| Retomada | limite - 10 C (75 C por padrão) |
| Disco do build | pausa a 5 C abaixo do seu `crit`/`max` (70 C - 5 se o disco não informa) |
| Aborto | CPU acima de 92 C por 60 s pausado |
| Intervalo de leitura | 2 s |

## Variáveis

| Variável | Efeito |
| :--- | :--- |
| `R36OS_TEMP_MAX` | limite da CPU em graus C (padrão 85) |
| `R36OS_TEMP_SENSOR` | escolhe o sensor: `chip:label` (ex. `k10temp:Tctl`) ou o caminho de um `tempN_input` |
| `R36OS_TEMP_GUARD` | `pause` (padrão) ou `log`; com `log` a proteção só mede e relata, nunca pausa |

Sem sensor de CPU encontrado, o build nem começa e a mensagem lista as entradas disponíveis.

## O que aparece no resumo

No fim do build (também em caso de erro) o resumo de etapas traz duas linhas:

```
heat: max CPU 83.5 C (k10temp Tctl (...)), max disk 41.0 C
heat: above limit 0 s, paused 0 s (0 pauses)
```

Durante o build, cada pausa e cada retomada também aparecem como linhas `heat guard: ...`.

## Cache do kernel: uma árvore, uma pasta de build por arquitetura

Depois do primeiro build, o `.cache/` guarda só:

- `src/linux-<versão>/` (a árvore com os patches aplicados) e `src/linux-<versão>.git` (o
  repositório git dela, ao lado);
- `kbuild/armv7/` e `kbuild/aarch64/` (uma pasta de build fixa por arquitetura, reaproveitada
  entre os builds, então só o que mudou recompila).

No início da etapa do kernel o build apaga sozinho as gerações antigas: as árvores
`src/linux-<versão>-<hash>/` (uma por conjunto de patches, 1,5 a 2 GB cada), as pastas
`kbuild/<console>-<hash>/` e as árvores de outra versão do kernel quando `KERNEL_VERSION`
muda. Ele diz numa linha quanto liberou:

```
cache: removed 3 old kernel generations, freed 14.2 GiB
```

Nunca são apagados: a árvore e as pastas de build atuais, `ccache`, `cargo`, `distfiles`,
`upstream`, `abuild` e qualquer pasta `*.antes-1.2` (linhas de base que o usuário renomeou:
o build só avisa que as deixou). O `r36os clean` (simulação por padrão, `--yes` para apagar)
usa as mesmas regras e lista as mesmas gerações antigas.

### Só o kernel de um console (`r36os build --console ga36 kernel`)

Para mudar um driver, um patch de `kernel/patches/` ou um device tree sem refazer a imagem:
`r36os build --console ga36 kernel` (ou `--console r36s`; sem `--console`, os dois). É um build
de fragmento só da etapa 1 daquele console: o kernel recompila apenas o que mudou na árvore, a
imagem dos módulos e os DTBs são refeitos, os pacotes `lume-kernel`, `lume-modules` e
`lume-dtbs` são publicados só quando o conteúdo mudou, e nenhum pacote do sistema é compilado.
Depois, `r36os push` manda só os arquivos de boot que mudaram (o `zImage`/`Image`, o slot
`modules`, os DTBs). `lume-kernel`, `lume-modules` e `lume-dtbs` valem como apelidos de `kernel`
e podem vir junto de outros fragmentos (`r36os build --console ga36 kernel lume-launcher`).

## lume-launcher sem emulação

No armv7 e no aarch64 o `cargo` do `lume-launcher` roda no PC (container x86_64, com o Rust
do Alpine e a std do alvo tirada do pacote `rust` da arquitetura), e o container emulado só
empacota os binários (design D7 da change `build-speed`). Ficam no `.cache/`:
`lume-cross/<arch>/` (sysroot do alvo, std e cache do `apk`) e `cargo/<arch>-cross/` (o
`target/` do cargo). Para voltar ao build antigo, com o cargo sob qemu:

```
R36OS_LUME_CROSS=0 .venv/bin/r36os pkg ga36 lume-launcher
```

## Teste com limite baixo

Para ver a pausa e a retomada sem esquentar o PC, baixe o limite (ele precisa ficar acima
da temperatura ociosa mais 10 graus para a retomada acontecer):

```
R36OS_TEMP_MAX=55 .venv/bin/r36os build console
```

## Ajuste manual opcional para um PC mais frio

O `r36os` **nunca** muda a configuração do PC. Se quiser o build mais frio, ao custo de
alguns por cento de velocidade, estes ajustes são por sua conta e exigem root:

- Desligar o boost da CPU (AMD, driver `amd-pstate`/`acpi-cpufreq`):
  `echo 0 | sudo tee /sys/devices/system/cpu/cpufreq/boost`
  (Intel: `echo 1 | sudo tee /sys/devices/system/cpu/intel_pstate/no_turbo`).
- Ou trocar a preferência de energia (EPP) para economizar:
  `echo balance_power | sudo tee /sys/devices/system/cpu/cpu*/cpufreq/energy_performance_preference`.

Ambos voltam ao normal ao reiniciar (ou com o valor anterior no mesmo arquivo).

# Build: tarefas, prioridade, resumo e etapas puladas

## Tarefas em paralelo e prioridade (`--jobs`, `R36OS_JOBS`)

O número de tarefas em paralelo vem de um só lugar (`src/r36os/jobs.py`):

1. a opção `--jobs N` (aceita por `build`, `pkg` e `push`), que vence tudo;
2. a variável de ambiente `R36OS_JOBS`;
3. o padrão: **metade dos núcleos** (mínimo 1).

```
uv run r36os build console --jobs 4
R36OS_JOBS=4 uv run r36os build console
uv run r36os pkg r36s retroarch --jobs 2
```

No começo do build sai uma linha com o valor em uso:

```
jobs: 8 (16 cores), priority: nice 19, ionice idle
```

O mesmo N vai para o `make -j`, o `JOBS` do `abuild`, o `-processors` do `mksquashfs` e as
threads do zstd. Todo comando `podman` do build roda sob `nice -n 19 ionice -c 3`, então o
container e os compiladores herdam prioridade mínima de CPU e de disco e o PC continua
responsivo. A prioridade deixa o PC fluido, mas o calor só cai com menos tarefas: se o PC
esquenta, baixe o `--jobs` (a proteção de calor acima pausa o build em último caso).

## Resumo do build

No fim do `r36os build` (também em caso de erro) sai um bloco com uma linha por etapa, o
total e, depois dele, as linhas `heat:` da proteção de calor:

```
build summary:
  <etapa>  4m05s
  <etapa>  skipped (inputs unchanged (3fa9c1d20b7e))
  total    4m31s
heat: max CPU 83.5 C (k10temp Tctl (...)), max disk 41.0 C
heat: above limit 0 s, paused 0 s (0 pauses)
```

Tempos abaixo de 1 minuto saem em segundos (`6.2s`), os maiores como `4m05s` ou `1h02m03s`.
Uma etapa que falhou aparece com `(failed)` e o resumo sai mesmo assim.

## Etapas puladas (`<saída>.inputs`, `--clean`)

Cada etapa que pode ser pulada guarda, ao lado da sua saída, um arquivo `<saída>.inputs` com
o hash de tudo o que a alimenta (`src/r36os/stage_inputs.py`). No build seguinte, se o hash é
o mesmo e a saída existe, a etapa não roda e o resumo mostra `skipped (inputs unchanged ...)`.
O arquivo é apagado antes da etapa rodar, então uma falha nunca deixa um hash velho.

Etapas puladas desse modo:

| Etapa | Roda de novo quando muda |
| :--- | :--- |
| DTBs | só os patches que tocam device tree ou bindings (e os DTS de origem) |
| initramfs | o rootfs e o que entra no initramfs |
| imagem de módulos | o conteúdo dos módulos e o script que a gera |
| rootfs | o script, a lista de pacotes, o idioma e o índice do espelho do Alpine |
| SYSTEM (squashfs) | o conteúdo do rootfs e as opções do `mksquashfs` |

O `BOOT/VERSION` e seu id de build nunca entram: mudam a cada build. Para forçar todas as
etapas, mesmo com as entradas iguais:

```
uv run r36os build console --clean
```

(`r36os clean` é outra coisa: libera o espaço das sobras de build.)

## Ganhos medidos

Medido no PC do projeto (Ryzen 7 5700G, 16 threads); os valores "antes" estão na tabela
"Medições" do `design.md` da change `build-speed`:

| Caso | Antes | Depois |
| :--- | :--- | :--- |
| build sem mudança | 12 min 04 s | 1 min 25 s |
| patch num driver do GA36 | 13 min 45 s | 1 min 30 s |

O que sobra no build sem mudança é o que não é pulado (preparo, conferências e a gravação da
imagem).

# Testar no console pelo cabo: `r36os dev`, `push` e capturas

Change `build-speed` (D12, D19). Tudo isto fala com o console pelo cabo USB da porta OTG, como
root por ssh, sem senha e sem gravar nada no `known_hosts` do PC. Nada disso roda sem o
console ligado e com o cabo.

## Endereços

Um só cartão SD vai de um console para o outro (GA36 e R36S), e **nunca os dois ficam ligados
no PC ao mesmo tempo**. Os dois respondem no mesmo endereço pelo cabo: **`10.55.0.1`** (o PC
recebe `10.55.0.2`). O `r36os dev` e o `r36os push` usam esse endereço; `--host ADDR` (antes
da ação, ex. `r36os dev --host 10.55.0.1 wait`) troca o endereço. O endereço aceita uma porta,
`--host HOST:PORTA` (o `ssh` recebe `-p PORTA`), que é a forma de falar com a vm (abaixo). No
`r36os dev` o `--host` vale antes ou depois da ação (`r36os dev sh --host 127.0.0.1:2222
uname -m`).

### A vm no lugar do console (`r36os vm --ssh`)

Change `virtual-gamepad` (3.3). Sem console no cabo, a imagem `vm` pode receber os mesmos
comandos:

```
.venv/bin/r36os vm --ssh            # porta 2222; ou --ssh 2300
.venv/bin/r36os dev --host 127.0.0.1:2222 wait --timeout 180
.venv/bin/r36os dev sh --host 127.0.0.1:2222 uname -m       # x86_64
```

- `--ssh [PORTA]` liga a rede de usuário da QEMU (`-nic user,model=virtio-net-pci,
  restrict=on,hostfwd=tcp:127.0.0.1:PORTA-:22`), com o container na rede do PC
  (`--network=host`), de modo que a porta só existe em `127.0.0.1:PORTA` do PC: nada da rede
  local chega ao `ssh` da vm, e o `restrict=on` deixa a vm **sem rota para fora** (nem para o
  PC, só a conexão redirecionada entra; conferido em 2026-11-17: `wget` para fora dá
  "Network unreachable").
- Por que não `podman -p`: a conexão publicada pelo podman chega à QEMU vinda do endereço do
  container, e a slirp só troca pelo gateway `10.0.2.2` uma origem de loopback. A vm, que não
  tem rota padrão, nunca respondia, e o `ssh` travava na troca de banners.
- Na vm, e só nela (`r36os-vmnet` entra no runlevel apenas com o board `vm`, em
  `rootfs/configure.sh`), o serviço pega um endereço por DHCP na interface virtio (só o
  endereço: sem rota padrão e sem DNS) e roda o `dropbear` nesse endereço, root sem senha e sem
  encaminhamento, como no cabo. Ele sobe **depois do frontend**, fora do caminho do boot, e
  sem a interface (o `r36os vm` sem `--ssh` e o `test-vm`) não faz nada.
- O `test-vm` continua sem rede (`-nic none`).
- O `--host 127.0.0.1:PORTA` vale também para o `r36os push` e o `push --hot`.
- O que for provado assim vale **só para a vm**; a prova no console continua pendente.

### Qual console está no cabo (`--console`)

Como os dois respondem no mesmo endereço, cada comando diz qual console respondeu, pelo que o
próprio console informa (`/etc/r36os/board`; sem ele, o `uname -m`: `armv7l` = GA36,
`aarch64` = R36S):

- `r36os push` e `r36os push --hot` já mostram `console: ga36, ...` na primeira linha;
- toda ação do `r36os dev`, menos `wait` (o console pode estar desligado), escreve antes
  `console: GA36 (10.55.0.1)` na saída de erro (a saída normal do `sh`, `shot` e `log` fica
  limpa).

Para não mexer no console errado, `push`, `push --hot` e as ações `sh`, `shot`, `keys`, `log`
e `check` do `dev` aceitam `--console ga36|r36s` (depois da ação: `r36os dev check --console
r36s`, `r36os dev sh --console r36s uname -a`). Se o console no cabo for o outro, o comando
recusa **antes de enviar ou rodar qualquer coisa**, com código de saída 1:

```
error: the console on the cable is the GA36, not the R36S: nothing was sent   (push)
error: the console on the cable is the GA36, not the R36S                    (dev)
```

Um console que não diga qual é (sem `/etc/r36os/board` e com outra arquitetura) também é
recusado quando `--console` foi dado.

O `r36os flash` **não tem `--console`**: ele grava o cartão num leitor do PC, onde não há
console para perguntar, e a imagem é a mesma para os dois consoles (o cartão escolhe a árvore
do aparelho no boot). Quem confere o console é o primeiro `push` ou `dev` depois que o cartão
volta a um console.

### Canal ssh compartilhado (`dev`, `push`, `dev run`)

Todas as chamadas `ssh` do `r36os` ao console passam por um canal mestre do OpenSSH do PC
(`ControlMaster=auto`, `ControlPersist=60`): a primeira abre a conexão e as seguintes a
reaproveitam, sem custo de um `dropbear` novo por comando e sem nada novo no console. O
socket fica em `cache/ssh/<hash de host:porta>` (um por console; ao lado, `<hash>.id` guarda
`<console> <boot_id>`). A identidade é conferida a cada comando `r36os dev` (uma leitura de
`/proc/sys/kernel/random/boot_id` pelo próprio canal): boot novo ou outro console no cabo
fecha o canal e reconecta. O `push` (antes de começar, depois do `reboot` e quando o console
volta) e o `dev wait` também o descartam. As sondagens "o console responde?" nunca usam o canal.

- Desligar: `R36OS_SSH_MUX=0` (o argv do `ssh` volta a ser o de antes, byte a byte).
- Soltar à mão: `ssh -O exit -o ControlPath=cache/ssh/<hash> root@10.55.0.1`
  (ou apague a pasta `cache/ssh/` com o canal já fechado).
- Se o caminho do socket passar do limite de 104 bytes, o `r36os` segue sem o canal.

## `r36os dev`

Rode no PC, na raiz do repositório (`.venv/bin/r36os dev <ação>`):

| Ação | O que faz |
| :--- | :--- |
| `wait [--timeout S]` | espera o console responder pelo cabo (padrão 120 s); código 1 se não responder |
| `sh <comando...>` | roda o comando no console como root, mostra a saída e devolve o código de saída dele |
| `shot <arquivo.png>` | grava um PNG da tela (`r36os-shot` no console, lido pelo ssh) |
| `shot --compare <tela>` / `--update <tela>` | captura de referência (seção abaixo) |
| `keys <sequência> [--hold MS] [--gap MS]` | aperta botões (sintaxe abaixo) |
| `log` | imprime o log do boot atual e os eventos desse boot do `events.log` |
| `check` | roda o autoteste do aparelho; código 0 só se tudo passar |
| `replay record\|stop\|play <slot>` | replay do próprio RetroArch (gravar, parar, repetir o slot) pelo comando de rede (`RECORD_REPLAY`, `HALT_REPLAY`, `PLAY_REPLAY_SLOT`); sem jogo rodando é erro. O UDP não tem confirmação: o `dev` só confere, antes e depois, que o jogo segue em `PLAYING`; confirme o replay pela tela ou captura. Imprime só o core, nunca o nome do jogo |
| `record` / `record --stop` | liga e para o gravador `r36os-evrec` no console (botões físicos, formato `.evrec`). `--stop` traz a gravação para `cache/recordings/<console>-<AAAAMMDD-HHMMSS>.evrec` (fora do git), apaga a cópia remota e imprime o caminho e o número de eventos; gravação vazia é erro e não é salva; gravar de novo com uma em andamento é erro |
| `play <arquivo.evrec>` | envia a gravação ao console e a toca com `r36os-evrec play`, imprimindo o atraso medido (`delay max=<ms> mean=<ms> events=<n>`); gravação de outro console é recusada antes de enviar; falha do player vira código de saída 1 |
| `watch <fragmento>` | a cada arquivo salvo do fragmento: build do fragmento e `push --hot` (seção abaixo); Ctrl-C encerra |

`sh`, `shot`, `keys`, `log` e `check` aceitam `--console ga36|r36s` (seção acima); `wait` e
`watch` não têm essa opção (o `watch` confere o console como o `push --hot`, sem poder
escolher).

Exemplos:

```
.venv/bin/r36os dev wait --timeout 180
.venv/bin/r36os dev sh uname -a
.venv/bin/r36os dev shot cache/tmp/tela.png
.venv/bin/r36os dev keys 'a,down*3,start+select,wait:500'
.venv/bin/r36os dev log
.venv/bin/r36os dev check --console ga36
```

### Sintaxe de `keys`

Fichas separadas por vírgula (espaços são ignorados), tocadas em ordem:

- um nome de botão: `a b x y l1 r1 l2 r2 l3 r3 up down left right select start fn`
  (`mode` é o mesmo que `fn`); o botão fica apertado 80 ms (`--hold`) e há 120 ms de pausa
  depois (`--gap`);
- `nome*N` repete o aperto N vezes (`down*3`);
- `a+b` é uma combinação: todos descem juntos e sobem juntos (`start+select`);
- `wait:MS` (ou `w:MS`) pausa MS milissegundos;
- os botões comuns vão ao controle virtual do `r36os-input` ("GA36-MB Gamepad" ou "R36S
  Gamepad"), o que o launcher e o RetroArch leem. Uma combinação com `fn` (`fn+start`) vai ao
  controle do kernel, porque o daemon monta os atalhos a partir dos botões físicos. `k:<ficha>`
  força o controle do kernel e `v:<ficha>` o virtual.

Os números dos `event` são lidos em `/proc/bus/input/devices` de cada console: nada é fixo
por aparelho.

### `log`

Imprime o `boot-<n>.log` do boot atual (a cópia na RAM, senão a do cartão, senão o `dmesg`),
uma linha em branco, `== events (boot <n>)` e as linhas desse boot no `events.log`. É o único
lugar onde aparece a linha `boot OK completed: ...`, que não vai para o log de boot.

### `check`

Roda `/usr/libexec/r36os/selftest device` no console (sem disco de teste, sem reboot, sem
botões) e imprime `GA36: self-test PASS (<n> checks)` ou `... FAIL (<k> of <n> checks failed)`
seguido de uma linha `  FAIL <nome>: <detalhe>` por verificação. As verificações: partição
`ROMS` montada, overlay da raiz, zram, resumo de hardware do boot sem falha, os serviços do
nível padrão, `lume-index-scan`, frontend rodando como `game` e sem desistir, o controle
virtual do `r36os-input`, o log de boot escrito, `boot-completed`, as pastas de log e o cgroup
dos jogos entregue ao usuário `game`.

O `lume-index-scan` olha o resultado do scan do launcher neste boot, não o estado do serviço:
o `lume-index` é um scan em segundo plano que sai ao terminar (o OpenRC o mostra como
`crashed`), então passa se ainda está rodando ou se a linha `lume-index: scan ... failed=0`
está no syslog.

### Gravações (`.evrec`) e roteiros de prova (change `virtual-gamepad`)

Dois formatos congelados; o leitor e o escritor Python estão em `src/r36os/evrec.py` e a
validação dos roteiros em `src/r36os/scripts.py`.

**Gravação** (`cache/recordings/<console>-<data>.evrec`, texto ASCII):

```
# r36os-evrec 1 <ga36|r36s>
<ms> <tipo> <código> <valor>
...
# end <ms>
```

- uma linha por evento, quatro inteiros decimais separados por um espaço: `ms` desde o início
  da gravação (nunca diminui), `tipo` e `código` do `input_event` (não negativos) e `valor`
  (pode ser negativo); um `SYN_REPORT` (`0 0 0`) fecha cada grupo;
- a última linha `# end <ms>` marca o fim (`ms` não menor que o do último evento); sem ela, a
  gravação é recusada. Linha em branco, linha a mais depois do fim ou linha mal formada é erro
  com o número da linha. O leitor recusa uma gravação de outro console;
- só botões, nunca nome de jogo. **Fica em `cache/`: um `.evrec` no repositório faz um teste
  falhar.**

**`r36os-evrec`** (pacote `r36os-input`, `aports/r36os-input/evrec.c`), o que o `dev record` e
o `dev play` rodam no console:

- `r36os-evrec record <saída>`: lê o controle virtual (nome e barramento virtual, sem
  `EVIOCGRAB`), grava cada evento com o tempo do próprio evento (`CLOCK_MONOTONIC`), linha a
  linha, inclusive o `SYN_REPORT` (o `SYN_DROPPED` é pulado e avisado); no `SIGTERM`/`SIGINT`
  escreve o `# end <ms>` e sai com 0. O `SIGHUP` fica como herdado (o `nohup` do `dev record`);
- `r36os-evrec play <arquivo> [--pad virtual|kernel]`: confere o arquivo inteiro, recusa
  (código 3) gravação de outro console e nó sem permissão de escrita (só o root escreve), antes
  de mandar qualquer botão; manda cada grupo de mesmo `ms` numa escrita no tempo absoluto
  (`clock_nanosleep` com `TIMER_ABSTIME`), com um `SYN_REPORT` por grupo; espera até o
  `# end`; solta todo botão apertado no fim, no `SIGTERM`/`SIGINT`/`SIGHUP` (sai com 128+sinal)
  e num erro de escrita (sai com 1); imprime `delay max=<ms> mean=<ms> events=<n>` (atraso de
  cada evento que não é `SYN` em relação ao tempo gravado). `--pad kernel` só no GA36 (no
  R36S o `gpio-keys` usa outros códigos);
- testes no PC (`tests/unit/test_r36os_evrec.py`): `R36OS_EVREC_DEVICES` e
  `R36OS_EVREC_INPUT_DIR` trocam o `/proc/bus/input/devices` e o `/dev/input`, e
  `R36OS_EVREC_CLOCK=fake[:<atraso_us>]` usa um relógio que salta em vez de dormir.

**Roteiro** (`tests/device/scripts/<nome>.toml`):

```toml
description = "texto opcional"
consoles = ["ga36", "r36s"]        # não vazio; o roteiro recusa o console que não listar

[[step]]
name = "abrir o menu"              # rótulo do passo, nunca um jogo
type = "keys"
timeout = 30                       # segundos (> 0); sem ele vale o padrão do tipo
sequence = "fn+start,wait:500"
```

| `type` | Campos | Padrão do `timeout` |
|---|---|---|
| `keys` | `sequence` (sintaxe do `dev keys`) | 60 s |
| `play` | `recording` (caminho `cache/...evrec`) | 120 s |
| `wait_event` | `pattern` (regex), `category` (opcional) | 30 s |
| `wait_process` | `process`, `state` = `"present"` ou `"absent"` | 30 s |
| `shot` | `screen` (de `tests/device/shots/screens.toml`) | 30 s |
| `sh` | `command` | 30 s |
| `open_game` | `system`, `position` (inteiro >= 1) | 60 s |
| `close_game` | nenhum | 30 s |

Tipo ou campo desconhecido é erro. **Privacidade:** os campos `game`, `rom`, `path`, `content` e
`title` são recusados em qualquer lugar do roteiro, e o `name` de um passo não pode terminar
numa extensão de ROM (`.gba`, `.zip`, `.nes`...). Um jogo é sempre `system` + `position`. Um
teste de unidade valida todo roteiro rastreado em `tests/device/scripts/` e falha se houver
`.evrec` no repositório.

**Executar um roteiro:** `r36os dev run <nome-ou-caminho> [--console ga36|r36s]`. Um nome sem
`/` vira `tests/device/scripts/<nome>.toml`. O comando identifica o console do cabo e recusa,
antes do primeiro botão, um console que o roteiro não lista em `consoles`. Os passos rodam em
ordem, cada um com o seu `timeout`, e cada um imprime uma linha:

```
passo 1 abrir o menu: ok
passo 2 esperar o jogo: FALHOU (timeout after 30s waiting for an event (pattern game.*start))
```

A execução **para no primeiro passo que falha** (os seguintes dependem dele); o código de saída
é 0 só se todos passaram. Por tipo: `keys` usa o `dev keys`; `wait_event` consulta o
`/storage/logs/events.log` **e** o `/run/r36os/logs/events.pending` (RAM, ainda não drenado
para o cartão) a cada ~1 s, e só vê as linhas escritas depois do início do roteiro (o PC
deduplica pela linha cortada inteira, que tem hora e boot; o que já estava em qualquer dos dois
arquivos no início nunca casa) (`category` é o 3o campo da linha, `pattern` é uma regex); `wait_process` usa `pidof`;
`shot` faz o `dev shot --compare`; `sh` passa com saída 0 (a saída não é impressa); `play`
usa o `dev play`; `open_game`/`close_game` estão descritos abaixo. **Privacidade:** o filtro que corta cada linha do `events.log` em
` content=` roda no próprio console e de novo no PC, e nenhuma linha do log é impressa; o nome
do jogo nunca sai do console. Código em `src/r36os/dev_run.py`.

**Abrir e fechar um jogo (`open_game`, `close_game`):** o roteiro diz `system` e `position`
(1 = o primeiro da grade, ordenada por nome). Código em `src/r36os/dev_game.py`.

1. Um comando de shell no console lê o índice do launcher e imprime só números:
   `dock_index=<n> dock_count=<n> games=<n> focus=<n>` (`dock_index` é a posição do ladrilho
   do sistema no Dock, 0 = Favoritos; `dock_count` são todos os ladrilhos; `games` vem do campo
   `count` do cabeçalho de `/storage/system/lume/cache/index/<sistema>.bin`; `focus` é o
   ladrilho que o launcher terá em foco, lido só da linha `dock=` de
   `/run/user/<uid do usuário game>/lume/state`, nunca de `game_path`: `favorites` = 0,
   `sys:<id>` = o índice do sistema, `recent` = `dock_count`-2, `settings` = `dock_count`-1;
   sem arquivo ou valor desconhecido = 0). A ordem do Dock é a do
   catálogo `/usr/share/r36os/systems.json`, só com sistemas que têm jogos. Sistema sem jogos
   (ou `position` maior que `games`) falha **antes de qualquer botão**.
2. O PC monta a sequência a partir do código do `lume-ui` (`app.rs`: `dock_input`,
   `grid_input`, `overlay_input`): `b*4` (volta ao Dock de qualquer tela), Esquerda/Direita
   pelo caminho mais curto até o ladrilho (o Dock dá a volta), `a` (entra na grade, foco no
   primeiro jogo), `down*L,right*C` até a posição (grade de 4 colunas), `a` (abre o menu do
   jogo, "Iniciar" é a primeira linha) e `a` (inicia).
3. O passo espera a linha do `lume-run` (o `timeout` do passo): abrir espera
   `game OK <sistema> <runner> <core> start` e falha logo com
   `game FAIL <sistema> ... start-failed`. `close_game` manda `fn+start` e espera
   `game OK|FAIL <sistema> ... end=` (OK ou FAIL, o jogo terminou de qualquer jeito). Corrigido
   em 2026-11-17: os padrões antigos (`game OK opened`/`closed`) eram do frontend RetroArch e
   nunca casavam com o launcher lume.

Premissas a confirmar no aparelho: o foco do Dock vem do arquivo de estado do launcher
(corrigido em 2026-11-17: antes o driver supunha Favoritos e lembrava o último sistema, e na
vm o launcher voltou de um jogo em `sys:snes`). O arquivo é escrito quando o launcher sai
para um jogo e lido quando ele volta; `/run` é tmpfs, então depois de um boot novo não há
arquivo (Favoritos). Limite: se alguém mexer no Dock à mão depois de um jogo, sem abrir outro,
o arquivo fica velho e a sequência parte do ladrilho errado. A grade tem 4 colunas (todos os
temas entregues); o Dock não lista sistemas só do cartão (`systems.d`), que ficam fora da
conta.

Roteiros prontos em `tests/device/scripts/`: `open-close-<sistema>.toml` (nes, snes, gb, gbc,
gba, megadrive, psx; o primeiro jogo de cada um) e `launcher-screens.toml` (as telas de
referência do `dev shot`). Ex.: `r36os dev run open-close-gba`.

## Relatório de energia: `r36os power report`

Change `game-governor` (D14). Lê pelo cabo as métricas (`metrics/boot-<n>.csv`) e o `events.log`
(com os rotacionados) de `ROMS/logs/` e resume por cenário, sistema e perfil de energia:

```
.venv/bin/r36os power report [--since <boot>] [--console ga36|r36s] [--from-dir <pasta>]
```

- `--since <boot>`: só os boots de número igual ou maior.
- `--console`: recusa, antes de ler, se o console no cabo for o outro (como o `dev`).
- `--from-dir <pasta>`: lê uma cópia local de `ROMS/logs/` (ou o cartão montado) em vez do cabo,
  para analisar sessões antigas sem o console. `--host ADDR` (antes de `report`) troca o endereço.

O cenário vem da coluna `frontend` (`menu`, `game`, `other`; `idle` quando o evento
`power OK profile: idle -> <perfil>` está em vigor) e o perfil, do último evento
`power OK profile: <cenário> -> <perfil>` antes da amostra (`-` sem o serviço: governor padrão
do kernel; é o "antes" do antes e depois). Colunas, impressas e gravadas em
`cache/power-report-<data>.csv`:

| Coluna | Conteúdo |
|---|---|
| `scenario`, `system`, `profile` | o grupo (`system` só em jogo: a coluna `core` das métricas) |
| `samples` | amostras do grupo |
| `bat_ma` | corrente média (valor absoluto; amostras `Charging` ficam fora) |
| `fps_pct` | média de `fps` / `fps_nominal`, em % |
| `slow` | eventos `game FAIL slow` do grupo (o sistema vem da amostra de jogo mais próxima) |
| `cpu_cores_pct` | ocupação média de cada núcleo, `cpu0/cpu1/...` |
| `busiest_mean_pct`, `busiest_p90_pct` | média e p90 do núcleo mais ocupado |
| `clock_mhz` | clock médio (colunas `freq_*_mhz`) |
| `temp_max_c` | temperatura máxima |
| `logd_cpu_pct`, `sugov_cpu_pct` | custo médio do `logd` e do `sugov` (colunas `logd*_cpu_pct` e `sugov*_cpu_pct`, quando as métricas as têm) |

Coluna ausente em amostras antigas aparece como `-` (vazia no CSV). O relatório nunca lê a
coluna `content` nem o detalhe dos eventos, e só deixa passar nomes curtos de sistema e perfil:
nome de jogo e caminho de ROM não chegam à saída.

## Capturas de referência (`shot --compare` / `--update`)

- As telas estão em `tests/device/shots/screens.toml`: cada uma tem `keys`, a sequência (a
  mesma sintaxe do `dev keys`) que leva a ela **a partir da home do launcher**; vazio é a
  própria home. Volte à home antes de comparar a tela seguinte.
- A referência de cada console fica em `tests/device/shots/<ga36|r36s>/<tela>.png`. O console
  é descoberto pelo `uname -m` (`armv7l` = ga36, `aarch64` = r36s), então o mesmo comando
  serve para os dois.
- `shot --update <tela>` aperta as teclas, captura e grava a referência; `shot --compare
  <tela>` captura e compara pixel a pixel. Um pixel conta como diferente quando algum canal
  difere em mais de 16 (de 255); a tela falha quando **mais de 0,2%** dos pixels diferem
  (ou o tamanho é outro).
- Ao falhar, a imagem de diferença vai para `cache/shots/<console>-<tela>-diff.png`
  (pixels iguais escurecidos, diferentes em vermelho) e o comando sai com código 1:
  `ga36/home: FAILED (<n> of <total> pixels differ, <x>%); diff image: ...`.
- Sem referência: `no reference at ... (record it with --update)`.
- **Privacidade:** referência nunca mostra nome de jogo nem caminho de ROM. Só telas do
  sistema e do launcher entram no `screens.toml`; telas com lista de jogos só depois de um
  cartão de demonstração com nomes inventados.

```
.venv/bin/r36os dev shot --update home
.venv/bin/r36os dev shot --compare home
```

## `r36os push` e a verificação depois do reboot

`r36os push [--build CARIMBO] [--yes] [--no-wait] [--dry-run] [--console ga36|r36s] [--hot FRAGMENTO] [--jobs N]` atualiza o `BOOT` do console pelo cabo (ver
o `README.md`).

### Ver antes o que vai mudar (`--dry-run`)

`r36os push --dry-run` consulta o console como o push normal e só lista, sem enviar nada, sem
gravar no `BOOT` e sem reiniciar:

```
dry run: nothing is sent and the console does not reboot
packages: ga36/lume: lume-core 1.0-r5 -> 1.0-r6
packages: r36s/lume: lume-core 1.0-r5 -> 1.0-r6
send:     ga36/slot/lume-ed256572b9e7 (2.5 MiB)
send:     ga36/SLOTS (0.0 MiB)
...
total:    5.1 MiB in 5 file(s)
delete:   ga36/slot/lume-cf00b3e4a070, r36s/slot/lume-c9f5f4ee8881
room:     enough free space on BOOT
```

- `packages:` compara, slot por slot, os pacotes do conjunto que está no cartão (`SLOTS`) com
  os do build (`-` = ausente de um lado). Num cartão antigo, sem conjunto de slots, diz que
  todos os pacotes são novos.
- `send:` são exatamente os arquivos que o push mandaria, com o tamanho; `delete:` o que ele
  apagaria depois da troca; `room:` se o `BOOT` tem espaço.
- A peça mínima do envio é o slot: um pacote mudado manda o slot inteiro dele (o `lume` tem
  poucos MiB, o `runtime` centenas). Slots menores para os cores são o P-80.
- Não vale com `--hot`.

### Verificação depois do reboot

Depois do reboot o push **espera e confere** o boot novo, a menos que se passe `--no-wait`, que
só reinicia e volta:

1. o console deixa de responder pelo cabo (até 60 s) e volta a responder (até 180 s). Cada
   sondagem de 10 s tem limite próprio, e o ssh usa `ServerAliveInterval` para uma conexão
   cortada pelo reboot cair em cerca de 6 s em vez de travar;
2. o número do boot (`/run/r36os/logs/boot-n`) é outro que o de antes do reboot (o relógio do
   console não é confiável, então horas não são comparadas);
3. o `/boot/VERSION` tem o build enviado;
4. o `events.log` tem a linha `boot OK completed` desse boot (até 120 s).

Sucesso (código 0):

```
ok: boot 47 completed with build 20261117-101500 (frontend in 33.1s from kernel); send 1m12s, boot 52s
```

O "send" é do início do envio até o reboot, o "boot" é do reboot até o `boot OK completed`.
Cada falha (código 1) nomeia o último passo confirmado, por exemplo `the console did not come
back over the cable within 180s (last step confirmed: the console went away for the
reboot)`, `the console is back but still runs boot N, the one before the reboot`,
`boot N runs build X from /boot/VERSION, not the pushed build Y` ou `boot N did not reach
boot OK completed within 120s ... see r36os dev log`. Depois de um `push`, `r36os dev
check` confirma a saúde do sistema.

### `r36os push --hot <fragmento>`: sem reboot, só na RAM

`r36os push --hot lume-core` põe um fragmento no console em execução sem reiniciar (design
D11). A raiz do console é um overlay das camadas só de leitura do cartão com uma camada
gravável de 32 MiB em RAM (`/rw/upper`): os arquivos vão para essa camada e **somem no
reboot**, quando o console volta ao conjunto do cartão. Nada é gravado no cartão, a não ser a
linha do `events.log`.

1. pergunta ao console a arquitetura (`uname -m`: `armv7l` → `armv7`, `aarch64`; o mesmo
   cartão roda no GA36 e no R36S), se `/` é o overlay com a camada em RAM e o espaço livre
   nela, lido com `df /` (o `/rw`, o tmpfs, fica dentro do overlay: `df /rw/upper` não acha
   o ponto de montagem);
2. pega a versão mais nova do fragmento em `out/repo/<arch>/hashes.json` (os noarch estão em
   todas as arquiteturas);
3. monta no PC um tar só com os arquivos de dados do `.apk` (sem `.PKGINFO`, assinaturas,
   `.lume-content` nem scripts de instalação; o `apk add` não roda no console, P-14), confere
   que cabe na camada em RAM (mais 1 MiB de folga) e o extrai com `tar -xf - -C /`;
4. grava `push OK hot <fragmento> <versão>` no `events.log` pelo `event` do próprio console
   (`logs.sh`) e descarrega no cartão;
5. reinicia os serviços do fragmento que estão rodando: os de `_lume_restart="a b"` no
   `APKBUILD`, quando ele tem a variável (vazia: nenhum), senão os `init.d` que ele traz.
   Reiniciar o `frontend` reinicia a sessão do launcher (a saída avisa). Uma falha grava
   `push FAIL hot <fragmento> <versão> restart <serviços>` e sai com código 1. Um serviço
   que não estava rodando fica parado (`restart: <nome> not running, left stopped`).

A saída mostra, em ordem: `console: ...` (placa, arquitetura, KiB livres na camada), `hot: ...`
(pacote, versão, arquivos, tamanho), `sent: ...`, `event: push OK hot ...`, uma linha
`restart: <serviço>` por serviço e `ok: <pacote> <versão> is live until the next reboot`.

Recusados, com a indicação do `push` normal: `lume-kernel`, `lume-modules`, `lume-dtbs`, os
pacotes do slot `base` (`rootfs/slots.toml`), todo pacote que não seja `lume-*` ou `r36os-*`
e todo fragmento com arquivos em `/boot` ou `/lib/modules`. Também recusa um console cuja raiz
não é o overlay em RAM (escreveria no cartão), um fragmento fora do `out/repo/<arch>` e falta
de espaço na camada em RAM (o reboot a esvazia). Um arquivo que a versão nova deixou de trazer
continua lá até o reboot.

### Quais serviços cada fragmento reinicia (`_lume_restart`)

Cada `aports/lume-*/APKBUILD` declara `_lume_restart="<serviços>"`, os serviços do OpenRC que o
`push --hot` reinicia (só os que estão rodando). Vazio (`""`) é "nenhum". Sem a variável, valem
os `init.d` que o próprio pacote traz (ex.: `r36os-input`).

| Fragmento | Reinicia |
| :--- | :--- |
| `lume-audio` | `r36os-mixer`, `r36os-jack` |
| `lume-games` | `lume-index`, `r36os-playlists` |
| `lume-net` | `bluetooth`, `r36os-hostshare`; o NetworkManager **não** é reiniciado, então um ajuste dele só vale no reboot |
| `lume-saves` | `r36os-persist`, `r36os-savesync` |
| `lume-usb` | nenhum: reiniciar o gadget cortaria o próprio cabo do `push` |
| `lume-diag`, `lume-launcher-data`, `lume-retroarch-cfg`, `lume-shaders`, `lume-power` | nenhum (`""`) |

Um fragmento novo com serviço declara a variável no `APKBUILD`; o `frontend` na lista reinicia
a sessão do launcher.

### `r36os dev watch <fragmento>`: build e `push --hot` a cada arquivo salvo

Change `build-speed` (D19). `r36os dev watch lume-core` (rode na raiz do repositório, com o
console no cabo) fica olhando os arquivos de entrada do fragmento (o `aports/<fragmento>/` e,
no `lume-launcher`, a árvore `lume/`, sem `target`, `vendor` e `.git`) e, a cada mudança, faz o
build do fragmento e o `push --hot` dele.

- **Sondagem e agrupamento:** olha mtime e tamanho a cada 0,5 s (sem dependência extra); o
  ciclo começa quando passa 1 s sem mudança nova. Uma mudança durante um ciclo inicia outro
  depois dele.
- **Uma linha por ciclo**, por exemplo `watch lume-core: changed 2 files, build 14s, hot push ok
  (restart r36os-input)` ou `..., build failed: <motivo> (log: ...)` e `..., hot push failed:
  <motivo>`. Uma falha não encerra o `watch`: ele espera a próxima mudança.
- **Saída do build** (podman incluso) em `out/dev-watch/<fragmento>.log`, reescrito a cada
  ciclo.
- **Recusas**, antes de entrar no laço, com as mesmas regras do `push --hot` (kernel, módulos,
  dtbs, pacotes do slot `base`, o que não é `lume-*` ou `r36os-*`) e para nome de fragmento
  desconhecido.
- Ctrl-C imprime `watch stopped` e sai com código 0. O que foi enviado continua na RAM do
  console até o reboot.
