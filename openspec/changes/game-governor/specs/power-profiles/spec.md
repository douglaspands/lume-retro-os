# Spec Delta

## Purpose

Define como o console escolhe sozinho o perfil de energia de cada cenário de uso (boot, menu,
launcher parado, jogo) para durar mais na bateria sem perder qualidade de jogo, e o que ele faz
quando a bateria está acabando.

## ADDED Requirements

### Requirement: Perfil escolhido pelo cenário
O console MUST aplicar sozinho, sem escolha do usuário, o perfil de energia do cenário em curso: boot, menu do launcher, launcher parado e jogo. A troca de perfil MUST acontecer só na mudança de cenário, nunca no meio de um jogo.

#### Scenario: Do menu ao jogo e de volta
- **WHEN** o usuário abre um jogo pelo launcher e depois volta ao launcher
- **THEN** o perfil do jogo vale enquanto o jogo roda, o do menu volta ao reaparecer o launcher, e o `events.log` registra cada troca com o cenário e o perfil

#### Scenario: Jogo longo
- **WHEN** um jogo fica aberto por 30 minutos
- **THEN** o perfil não muda durante o jogo, a menos que a proteção térmica do kernel reduza o clock

### Requirement: Perfil do jogo por classe de sistema
O perfil de um jogo MUST vir da classe do sistema do jogo, com exceção possível por core. Um sistema sem classe MUST usar o perfil de jogo padrão.

#### Scenario: Sistemas leves e pesados
- **WHEN** o usuário abre um jogo de NES e depois um de PlayStation
- **THEN** cada um roda com o perfil da sua classe, registrado no `events.log`

#### Scenario: Sistema novo
- **WHEN** um sistema sem classe declarada é aberto
- **THEN** o jogo roda com o perfil de jogo padrão

### Requirement: Perfis dentro dos limites do hardware
Todo perfil MUST ficar dentro da tabela de frequências e tensões do device tree mainline e MUST NOT desligar ou mudar as proteções térmicas do kernel. Um valor fora da tabela MUST ser recusado com uma linha no log, ficando o perfil padrão do kernel.

#### Scenario: Valor inválido
- **WHEN** o arquivo de perfis pede um clock que não existe na tabela do console
- **THEN** o perfil é recusado, o log diz qual valor e qual console, e a CPU fica com o governor padrão do kernel

### Requirement: Jogo sem perder quadros
O perfil de cada classe de jogo MUST rodar os jogos de teste sem mais eventos `game FAIL slow` do que o governor padrão do kernel nas mesmas sessões, nos dois consoles.

#### Scenario: Comparação com o padrão
- **WHEN** a mesma sessão de teste de um sistema é jogada com o governor padrão e com o perfil da classe
- **THEN** o perfil não tem mais eventos `game FAIL slow` que o padrão e consome igual ou menos corrente média da bateria

### Requirement: Launcher parado gasta menos
Com o launcher na tela e nenhum botão apertado por alguns minutos, o console MUST passar ao perfil de launcher parado e escurecer a tela; o primeiro botão MUST devolver o brilho e o perfil do menu, sem executar a ação desse botão.

#### Scenario: Voltar do escuro
- **WHEN** o launcher fica parado até a tela escurecer e o usuário aperta A
- **THEN** a tela volta ao brilho escolhido e nada é aberto pelo A

### Requirement: Aviso de bateria fraca
Descarregando e num nível baixo de bateria, o console MUST avisar o usuário uma vez, no launcher ou por cima do jogo, nos idiomas do sistema.

#### Scenario: Aviso no jogo
- **WHEN** a bateria cai ao nível de aviso durante um jogo do RetroArch
- **THEN** uma mensagem aparece por cima do jogo e o jogo continua

#### Scenario: Carregando
- **WHEN** a bateria está no nível de aviso com o carregador ligado
- **THEN** nenhum aviso aparece

### Requirement: Desligamento limpo com bateria crítica
Descarregando e no nível crítico, o console MUST desligar sozinho pelo caminho normal: o jogo aberto recebe o pedido de saída (o RetroArch grava a SRAM), os dados e os logs são gravados e o cartão fica limpo. O desligamento MUST ser registrado no `events.log`.

#### Scenario: Bateria acabando no jogo
- **WHEN** a bateria chega ao nível crítico durante um jogo do RetroArch com save interno alterado
- **THEN** o save é gravado, o console desliga, e o boot seguinte registra o desligamento anterior como limpo e o motivo `battery critical`
