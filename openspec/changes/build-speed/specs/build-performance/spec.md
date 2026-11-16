# Spec Delta

## Purpose

Manter o build do PC rápido e leve: recompilar só o que mudou, pular etapas cujas entradas não
mudaram, rodar em prioridade baixa e mostrar quanto cada etapa custou.

## ADDED Requirements

### Requirement: Kernel recompilado só no que mudou
Quando um patch do kernel muda, o build MUST recompilar só os arquivos cujo conteúdo mudou e o que
depende deles, sem extrair de novo o código-fonte do kernel nem começar com a pasta de build vazia.

#### Scenario: Patch que toca um driver
- **WHEN** um patch muda só um arquivo de driver e o build roda de novo
- **THEN** o kernel do console que compila esse driver recompila esse arquivo e refaz o link, sem recompilar o resto

#### Scenario: Patch que não toca o kernel de um console
- **WHEN** um patch muda só um arquivo que o kernel de um dos consoles não compila
- **THEN** o kernel desse console não é recompilado e a imagem dele fica igual byte a byte

### Requirement: Etapas puladas sem mudança de entrada
O build MUST pular uma etapa (rootfs e `SYSTEM`, DTBs e validação, initramfs, imagem de módulos,
kernel) quando nada do que entra nela mudou desde o build anterior, e MUST dizer numa linha que
etapa pulou.

#### Scenario: Build repetido sem mudança
- **WHEN** `r36os build console` roda duas vezes seguidas sem mudança no repositório
- **THEN** o segundo build pula todas as etapas de compilação e montagem, e a `BOOT` e o `SYSTEM` saem iguais byte a byte aos do primeiro

#### Scenario: Só um pacote do rootfs mudou
- **WHEN** um pacote do rootfs ganha versão nova e o kernel não mudou
- **THEN** o build refaz o rootfs e o `SYSTEM` desse console e pula o kernel e os DTBs

### Requirement: Build em prioridade baixa
Todos os containers do build e do `r36os pkg` MUST rodar em prioridade baixa de CPU e de disco,
para o PC continuar usável durante o build.

#### Scenario: Usuário usa o PC durante o build
- **WHEN** um build está rodando
- **THEN** os processos do build aparecem com prioridade baixa (`nice` máximo e E/S ociosa) e o resto do sistema tem preferência

### Requirement: Número de tarefas limitado e ajustável
O build MUST limitar o número de tarefas paralelas a um padrão que deixa núcleos livres, e MUST
aceitar outro valor por opção da linha de comando e por variável de ambiente.

#### Scenario: Padrão
- **WHEN** um build roda sem opção nem variável
- **THEN** ele usa menos tarefas que o número de núcleos da máquina e diz quantas no começo

#### Scenario: Valor escolhido
- **WHEN** um build roda com o número de tarefas definido pelo usuário
- **THEN** a compilação do kernel, dos pacotes e a compressão do `SYSTEM` usam esse número

### Requirement: Tempo de cada etapa
No fim, o build MUST mostrar o tempo de cada etapa (inclusive as puladas) e o tempo total.

#### Scenario: Resumo no fim do build
- **WHEN** um build termina, com sucesso ou com erro
- **THEN** a saída traz uma linha por etapa com o tempo dela, ou `skipped`, e o total

### Requirement: Verificações do build mantidas
O build incremental MUST manter as verificações do build completo: falhar quando uma opção do
fragmento de kernel não pega, quando há warning nos drivers do projeto e quando um DTB não passa
no `dt-validate`.

#### Scenario: Opção do fragmento que não pega num build incremental
- **WHEN** o fragmento de kernel ganha uma opção cuja dependência falta e o build é incremental
- **THEN** o build falha com a mesma mensagem do build completo
