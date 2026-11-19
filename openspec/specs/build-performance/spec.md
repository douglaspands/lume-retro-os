# build-performance Specification

## Purpose

Manter o build do PC rápido e leve: recompilar só o que mudou, pular etapas cujas entradas não
mudaram, compilar sem emulação onde ela mais pesa, rodar em prioridade baixa e mostrar quanto cada
etapa custou.

## Requirements

### Requirement: Kernel recompilado só no que mudou
Quando um patch do kernel muda, o build MUST recompilar só os arquivos cujo conteúdo mudou e o que
depende deles, sem extrair de novo o código-fonte do kernel nem começar com a pasta de build vazia.

#### Scenario: Patch que toca um driver
- **WHEN** um patch muda só um arquivo de driver e o build roda de novo
- **THEN** o kernel de cada arquitetura que compila esse driver recompila esse arquivo e refaz o link, sem recompilar o resto

#### Scenario: Patch que não muda o kernel de uma arquitetura
- **WHEN** um patch muda só um arquivo que o kernel de uma arquitetura não compila
- **THEN** o kernel dessa arquitetura sai igual byte a byte ao anterior, inclusive depois de o patch ser commitado

### Requirement: Etapas puladas sem mudança de entrada
O build MUST pular uma etapa (kernel, DTBs e validação, initramfs, módulos, fragmentos, rootfs e
slots) quando nada do que entra nela mudou desde o build anterior, e MUST dizer numa linha que
etapa pulou.

#### Scenario: Build repetido sem mudança
- **WHEN** `lume build console` roda duas vezes seguidas sem mudança no repositório
- **THEN** o segundo build não chama compilador nem `mksquashfs`, e todos os arquivos da `BOOT`, exceto o `VERSION`, saem iguais byte a byte aos do primeiro

#### Scenario: Patch de driver não revalida os DTBs
- **WHEN** um patch que não toca device tree nem bindings muda
- **THEN** a etapa dos DTBs e da validação é pulada

#### Scenario: Forçar tudo
- **WHEN** o build roda com `--clean`
- **THEN** nenhuma etapa é pulada

### Requirement: Build pontual de um fragmento
O build MUST aceitar um ou mais fragmentos como alvo e MUST compilar só esses fragmentos e remontar
só os slots que os contêm, sem gerar a imagem do cartão.

#### Scenario: Só o launcher
- **WHEN** o usuário roda `lume build lume-launcher`
- **THEN** só o `lume-launcher` é compilado (nas arquiteturas pedidas), só o slot que o contém é remontado, e o build termina com um conjunto novo pronto para o `push`, sem `.img`

### Requirement: Compilação sem emulação para o launcher
O `lume-launcher` MUST compilar sem emular o compilador sob qemu, ou reaproveitando a compilação
anterior, e MUST gerar pacotes que rodam no aparelho como os de antes. Os cores e o RetroArch ficam
para uma change própria (P-36, P-80).

#### Scenario: Uma linha do launcher
- **WHEN** uma linha do código do `lume-ui` muda e o build do `lume-launcher` roda para armv7
- **THEN** o build leva perto de 1 minuto, e o launcher novo abre no GA36

### Requirement: Build em prioridade baixa
Todos os containers do build e do `lume pkg` MUST rodar em prioridade baixa de CPU e de disco,
para o PC continuar usável durante o build.

#### Scenario: Usuário usa o PC durante o build
- **WHEN** um build está rodando
- **THEN** os processos do build aparecem com `nice` 19 e E/S ociosa, e o resto do sistema tem preferência

### Requirement: Número de tarefas limitado e ajustável
O build MUST limitar o número de tarefas paralelas a um padrão que deixa núcleos livres, e MUST
aceitar outro valor por opção da linha de comando e por variável de ambiente.

#### Scenario: Padrão
- **WHEN** um build roda sem opção nem variável
- **THEN** ele usa metade dos núcleos (mínimo 1) e diz quantas tarefas no começo

#### Scenario: Valor escolhido
- **WHEN** um build roda com `--jobs N` ou `LUME_JOBS=N`
- **THEN** a compilação do kernel, dos pacotes, a compressão dos slots e a da imagem usam N tarefas

### Requirement: Proteção de calor do PC
Durante todo build, o `lume` MUST ler a temperatura do processador (pelo sensor do próprio
processador, nunca por entradas auxiliares da placa-mãe) e a do disco onde o build grava, MUST pausar os containers do
build acima de um limite ajustável e retomá-los abaixo de outro, e MUST abortar o build se a
temperatura continuar subindo com os containers pausados.

#### Scenario: Limite atingido
- **WHEN** a CPU chega ao limite (padrão 85 °C) durante um build
- **THEN** os containers do build são pausados com uma linha na saída, e retomados quando a CPU cai 10 °C abaixo do limite

#### Scenario: Refrigeração com problema
- **WHEN** a CPU passa de 92 °C mesmo com os containers pausados por 60 s
- **THEN** o build aborta com a temperatura lida e o sensor usado

#### Scenario: Sensor do processador ausente
- **WHEN** o build não acha o sensor do processador e nenhum foi escolhido pela variável de ambiente
- **THEN** o build falha antes de começar, dizendo como escolher o sensor

#### Scenario: Resumo do calor
- **WHEN** um build termina
- **THEN** o resumo traz a temperatura máxima da CPU e do disco do build e o tempo pausado

### Requirement: Compressão rápida no build pontual
O build pontual de um fragmento MUST montar os slots com compressão rápida, e o build completo da
imagem MUST usar a compressão máxima; um slot de uma compressão MUST NOT ser reaproveitado no lugar
do outro.

#### Scenario: Slot de desenvolvimento
- **WHEN** o usuário roda `lume build lume-core` e depois `lume build console`
- **THEN** o primeiro monta o slot do projeto com compressão rápida e o segundo o remonta com compressão máxima

### Requirement: Arquiteturas em paralelo
O build completo MUST processar as duas arquiteturas ao mesmo tempo, dividindo entre elas o limite
de tarefas, sob a mesma proteção de calor.

#### Scenario: Build completo
- **WHEN** `lume build console` roda com `--jobs 8`
- **THEN** as esteiras do armv7 e do aarch64 rodam juntas, com 4 tarefas cada, e a saída de cada uma tem o prefixo da arquitetura

### Requirement: Tempo de cada etapa
No fim, o build MUST mostrar o tempo de cada etapa (inclusive as puladas) e o tempo total.

#### Scenario: Resumo no fim do build
- **WHEN** um build termina, com sucesso ou com erro
- **THEN** a saída traz uma linha por etapa com o tempo dela, ou `skipped`, e o total

### Requirement: Verificações do build mantidas
O build incremental e o pontual MUST manter as verificações do build completo: falhar quando uma
opção do fragmento de kernel não pega, quando há warning nos drivers do projeto e quando um DTB não
passa no `dt-validate`.

#### Scenario: Opção do fragmento que não pega num build incremental
- **WHEN** o fragmento de kernel ganha uma opção cuja dependência falta e o build é incremental
- **THEN** o build falha com a mesma mensagem do build completo
