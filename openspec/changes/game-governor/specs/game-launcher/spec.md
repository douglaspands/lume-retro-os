# Spec Delta

## ADDED Requirements

### Requirement: Bateria carregando na barra de status
A bateria da barra de status do launcher MUST mostrar quando o console está carregando, com uma marca desenhada como no protótipo, e MUST refletir a ligação ou o desligamento do carregador em até 5 segundos.

#### Scenario: Ligar o carregador
- **WHEN** o usuário liga o carregador com o launcher na tela
- **THEN** em até 5 segundos a bateria da barra mostra a marca de carga, e a porcentagem acompanha a carga do kernel

#### Scenario: Desligar o carregador
- **WHEN** o carregador é desligado
- **THEN** em até 5 segundos a marca de carga some

### Requirement: Tela escurecida com o launcher parado
Com o launcher na tela e nenhum botão apertado por alguns minutos, a tela MUST escurecer até um brilho baixo sem apagar. O primeiro botão MUST só devolver o brilho escolhido pelo usuário, sem agir na tela. O brilho escolhido pelo usuário MUST NOT mudar por isso.

#### Scenario: Escurecer e voltar
- **WHEN** o launcher fica parado até escurecer e o usuário aperta B
- **THEN** a tela volta ao brilho de antes, o launcher continua na mesma tela, e o brilho salvo nas Configurações não muda
