# Spec Delta

## Purpose

Atualizar um console pelo cabo mandando só os pedaços que mudaram, de forma atômica, e iterar sem
reiniciar quando o pedaço permite, para o ciclo de uma mudança até o aparelho levar segundos.

## ADDED Requirements

### Requirement: Sistema em slots com manifesto
O sistema de cada console MUST ser um conjunto de slots squashfs na `BOOT` (base, runtime, projeto,
módulos e um por core), descrito por um manifesto do conjunto, e um slot MUST mudar só quando os
fragmentos dele mudam.

#### Scenario: Só o launcher mudou
- **WHEN** só o `lume-launcher` muda e o build roda
- **THEN** só o slot do projeto daquele console muda de conteúdo, e os slots base, runtime, módulos e cores saem iguais byte a byte

#### Scenario: Só um core mudou
- **WHEN** só um core muda
- **THEN** só o slot daquele core muda

### Requirement: Troca atômica do conjunto
O `push` MUST trocar o conjunto de slots de uma vez, de modo que um corte de energia em qualquer
momento deixe o console iniciando com o conjunto antigo inteiro ou com o novo inteiro.

#### Scenario: Corte antes da troca do manifesto
- **WHEN** a energia cai depois de copiados os slots novos e antes da troca do manifesto
- **THEN** o console inicia com o conjunto antigo inteiro

#### Scenario: Manifesto ausente ou citando arquivo que falta
- **WHEN** o console inicia e o manifesto falta ou cita um slot ausente
- **THEN** o boot usa o manifesto anterior e registra uma linha `ERROR` no log de boot

### Requirement: Cores fora do caminho do boot
Os slots dos cores MUST ser montados depois do frontend, fora do caminho crítico do boot, e um jogo
aberto antes disso MUST esperar o core ficar disponível.

#### Scenario: Jogo logo após o boot
- **WHEN** o usuário abre um jogo antes de os cores terem sido montados
- **THEN** o jogo abre assim que o core do sistema fica disponível, sem erro

### Requirement: Push pontual sem descompactar
O `r36os push` MUST mandar ao console só os arquivos e slots cujo SHA256 difere do que está no
cartão, lidos do arquivo do build, de qualquer build arquivado, e MUST NOT descompactar a imagem do
cartão para isso.

#### Scenario: Atualização só do launcher
- **WHEN** só o slot do projeto mudou e o usuário roda `r36os push`
- **THEN** só esse slot, o manifesto e o `VERSION` são enviados, não há etapa de descompactar, e o resumo mostra os bytes enviados e o tempo

#### Scenario: Nada mudou
- **WHEN** o cartão já tem os arquivos do build, salvo o `VERSION`
- **THEN** o `push` termina sem enviar nada e sem reiniciar, dizendo que o console já está no build

#### Scenario: Cartão único nos dois consoles
- **WHEN** o `push` é feito pelo GA36 e o cartão depois é passado ao R36S
- **THEN** o R36S inicia com o conjunto novo dele, sem outro `push`

### Requirement: Reinício como padrão
Toda troca de slot do boot ou do kernel MUST terminar com o reinício do console; a troca de um
slot de core MUST acontecer sem reinício.

#### Scenario: Troca de um core
- **WHEN** o `push` troca só o slot de um core que não está em uso
- **THEN** o console não reinicia e o próximo jogo daquele sistema usa o core novo

#### Scenario: Core em uso
- **WHEN** o `push` troca o slot de um core que está rodando um jogo
- **THEN** o jogo continua com o core antigo e a troca acontece quando o jogo fecha

### Requirement: Push em RAM para iterar
O `r36os push --hot <fragmento>` MUST instalar os arquivos do fragmento na camada gravável em RAM,
reiniciar só os serviços do fragmento e registrar isso no log, sem gravar no cartão nem reiniciar
o console; kernel, módulos e base MUST NOT aceitar `--hot`.

#### Scenario: Script alterado
- **WHEN** o usuário roda `r36os push --hot lume-usb` depois de mudar um script dele
- **THEN** o serviço `r36os-usb` reinicia com o script novo, o `events.log` tem a linha `push hot lume-usb <versão>`, e depois de um reboot o console volta ao conjunto do cartão

#### Scenario: Kernel recusado
- **WHEN** o usuário roda `r36os push --hot lume-kernel`
- **THEN** o comando recusa e diz para usar o `push` normal

### Requirement: Migração de cartões antigos
Um cartão com o `SYSTEM` único MUST continuar iniciando com o initramfs novo, e o `push` e o `flash
--update` MUST migrá-lo para slots sem deixar o `SYSTEM` antigo ocupando espaço depois do push
seguinte.

#### Scenario: Primeiro push num cartão antigo
- **WHEN** o `push` atualiza um cartão que só tem `<console>/SYSTEM`
- **THEN** o console reinicia com os slots, e o push seguinte apaga o `SYSTEM` antigo
