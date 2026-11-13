# Spec Delta

## ADDED Requirements

### Requirement: Menu sem relógio por padrão
Num cartão novo, o menu do RetroArch MUST NOT mostrar data e hora, porque os consoles não têm relógio de tempo real com bateria nem rede. O relógio MUST poder ser religado pelo usuário no menu, e essa escolha MUST persistir no cartão.

#### Scenario: Cartão novo
- **WHEN** um cartão gravado com `flash --full` abre o menu pela primeira vez
- **THEN** o topo do menu não mostra data nem hora

#### Scenario: Usuário religa o relógio
- **WHEN** o usuário liga "Mostrar data e hora" no menu e reinicia o console
- **THEN** o relógio continua aparecendo no menu
