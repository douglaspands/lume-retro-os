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
