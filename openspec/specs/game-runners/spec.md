# game-runners Specification

## Purpose
Define como o launcher abre e encerra jogos: emuladores descritos por configuração, o supervisor que roda o jogo e volta à interface, e a combinação Fn+Start que encerra qualquer programa aberto pelo launcher.

## Requirements

### Requirement: Runners declarativos
Cada forma de abrir um jogo MUST ser um runner descrito num arquivo de dados com o comando (lista de argumentos com marcadores como a ROM e o core) e a política de encerramento. Adicionar um emulador MUST exigir só um arquivo de runner e uma entrada no catálogo, sem recompilar o launcher.

#### Scenario: Emulador novo pelo cartão
- **WHEN** o usuário coloca um arquivo de runner em `ROMS/system/lume/runners.d/` e o cita num sistema
- **THEN** depois de "Atualizar listas de jogos" o emulador aparece no menu do jogo desse sistema e abre o jogo

#### Scenario: Nome de arquivo com espaço
- **WHEN** a ROM se chama `Meu Jogo (Rev 1).zip`
- **THEN** o emulador recebe o caminho inteiro como um único argumento

### Requirement: Runner inválido não derruba o launcher
Um arquivo de runner inválido ou que cite um executável ausente MUST ser ignorado com uma linha no log, e os demais runners MUST continuar funcionando.

#### Scenario: Runner com erro
- **WHEN** um arquivo de runner do cartão não tem o campo do comando
- **THEN** o launcher abre normalmente, o runner não aparece e o log diz qual arquivo foi recusado

### Requirement: Runners incluídos
A distro MUST trazer runners para os cores do RetroArch, para o LÖVE e para scripts de Ports nativos (`roms/ports/*.sh`, rodados pelo shell do sistema).

#### Scenario: Script de Ports
- **WHEN** o usuário abre um `.sh` de `roms/ports/`
- **THEN** o script roda como o usuário `game` e, ao terminar, o launcher reaparece

### Requirement: Abrir pelo RetroArch com as opções do jogo
O runner do RetroArch MUST abrir o jogo direto no core efetivo, com o aspecto e o shader efetivos, e no slot de save state escolhido quando houver. Essas opções MUST valer só para essa execução, sem mudar a configuração salva do usuário.

#### Scenario: Shader de um jogo
- **WHEN** um jogo de GBA tem um shader próprio e é aberto
- **THEN** o jogo abre com esse shader, e um jogo de GBA sem exceção abre sem ele

### Requirement: RetroArch faz só o que o launcher pede
Aberto pelo launcher, o RetroArch MUST carregar só o core e o conteúdo pedidos, com o aspecto, o shader e o slot pedidos, que MUST valer mesmo que outro valor tenha sido salvo no RetroArch (overrides de core ou de jogo, presets automáticos de shader). Ele MUST NOT gravar histórico nem registro de tempo de jogo, e MUST ler só as informações dos cores instalados.

#### Scenario: Escolha do launcher vence a do RetroArch
- **WHEN** um override do RetroArch para o core guarda outro aspecto e o launcher abre o jogo com o aspecto do core
- **THEN** o jogo abre com o aspecto do launcher, e o override do usuário continua salvo

#### Scenario: Nada gravado à toa
- **WHEN** o usuário joga e sai pelo Fn+Start
- **THEN** nenhum histórico ou registro de tempo do RetroArch é gravado no cartão

### Requirement: Interface fora da memória durante o jogo
Antes de abrir um jogo, a interface MUST encerrar e liberar a tela, o áudio e a memória. Durante o jogo, além do jogo, MUST ficar só o supervisor e o daemon de entrada.

#### Scenario: Processos durante o jogo
- **WHEN** um jogo está aberto
- **THEN** não existe processo da interface, e o supervisor tem menos de 2 MB de memória residente

### Requirement: Volta à interface quando o jogo termina
Quando o jogo termina, por saída normal, erro, falha ou Fn+Start, o supervisor MUST reabrir a interface. Uma falha do jogo MUST NOT contar como falha do frontend.

#### Scenario: Emulador que cai
- **WHEN** o emulador termina com segfault
- **THEN** o launcher reaparece, o `events.log` registra o fim do jogo com o código, e o contador de falhas do frontend não muda

### Requirement: Fn+Start encerra qualquer jogo
Fn+Start MUST encerrar o que o launcher abriu, seja RetroArch, LÖVE, emulador standalone ou script de Ports, e voltar ao launcher, mesmo que o programa tenha capturado o controle só para ele ou esteja travado.

#### Scenario: Programa travado
- **WHEN** um jogo para de responder e o usuário aperta Fn+Start
- **THEN** em até 5 segundos o jogo e todos os processos que ele abriu terminam e o launcher reaparece

#### Scenario: Programa que capturou o controle
- **WHEN** um programa abre o controle com acesso exclusivo e o usuário aperta Fn+Start
- **THEN** a combinação ainda encerra o programa

### Requirement: Encerramento educado antes do forçado
Fn+Start MUST primeiro pedir a saída pela política do runner (no RetroArch, o comando de saída, que grava a SRAM; nos demais, o sinal de término) e só forçar o fim de todos os processos do jogo quando o prazo do runner acabar.

#### Scenario: Save interno do RetroArch
- **WHEN** o usuário aperta Fn+Start num jogo do RetroArch com save interno alterado
- **THEN** o save é gravado no cartão antes de o RetroArch fechar

### Requirement: Fn sozinho continua abrindo o menu
O Fn apertado e solto sem outra tecla MUST continuar abrindo o menu do RetroArch dentro do jogo. A combinação Fn+Start MUST NOT abrir esse menu.

#### Scenario: Fn sozinho
- **WHEN** o usuário aperta e solta o Fn durante um jogo do RetroArch
- **THEN** o menu do RetroArch abre

#### Scenario: Fn+Start
- **WHEN** o usuário segura Fn e aperta Start
- **THEN** o jogo encerra sem o menu do RetroArch aparecer

### Requirement: Fn+Start sem jogo não faz nada
Fn+Start fora de um jogo, com o launcher na tela, MUST ser ignorado.

#### Scenario: Na grade
- **WHEN** o usuário aperta Fn+Start na grade de jogos
- **THEN** o launcher continua na mesma tela

### Requirement: Volume pelo sistema
Os botões de volume MUST ajustar o volume do sistema em qualquer tela e em qualquer jogo, sem depender do programa aberto.

#### Scenario: Volume num jogo LÖVE
- **WHEN** o usuário aperta volume + durante um jogo LÖVE
- **THEN** o volume de saída sobe

### Requirement: Registro dos jogos
Cada início e fim de jogo MUST virar uma linha do `events.log`, em inglês, com o sistema, o runner, o core, o código de saída e se o fim veio do Fn+Start. O nome do jogo e o caminho da ROM MUST NOT ser registrados.

#### Scenario: Linha de fim
- **WHEN** um jogo de SNES aberto no core `snes9x` é encerrado por Fn+Start
- **THEN** o `events.log` tem uma linha com `snes`, `retroarch`, `snes9x` e `quit-combo`, sem o nome do jogo
