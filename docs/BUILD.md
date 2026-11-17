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
da ação, ex. `r36os dev --host 10.55.0.1 wait`) troca o endereço.

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

Todas as ações menos `wait` aceitam `--console ga36|r36s` (seção acima).

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

`r36os push [--build CARIMBO] [--yes] [--no-wait] [--console ga36|r36s]` atualiza o `BOOT` do console pelo cabo (ver
o `README.md`). Depois do reboot ele **espera e confere** o boot novo, a menos que se passe
`--no-wait`, que só reinicia e volta:

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
   nela (`df /rw/upper`);
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
   `push FAIL hot <fragmento> <versão> restart <serviços>` e sai com código 1.

Recusados, com a indicação do `push` normal: `lume-kernel`, `lume-modules`, `lume-dtbs`, os
pacotes do slot `base` (`rootfs/slots.toml`), todo pacote que não seja `lume-*` ou `r36os-*`
e todo fragmento com arquivos em `/boot` ou `/lib/modules`. Também recusa um console cuja raiz
não é o overlay em RAM (escreveria no cartão), um fragmento fora do `out/repo/<arch>` e falta
de espaço na camada em RAM (o reboot a esvazia). Um arquivo que a versão nova deixou de trazer
continua lá até o reboot.
