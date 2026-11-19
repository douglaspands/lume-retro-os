# Spec Delta

## MODIFIED Requirements

### Requirement: Frequência da CPU e proteção térmica
Cada console MUST variar a frequência da CPU conforme a carga e o cenário de uso, pelos perfis de energia (ver `power-profiles`), sempre dentro da tabela de frequências e tensões e com as temperaturas-limite do device tree mainline do SoC, sem valores próprios de frequência, tensão ou temperatura. Sem perfil válido, MUST valer o governor padrão do kernel. Acima do limite térmico, o clock MUST ser reduzido.

#### Scenario: Frequência acompanha a carga
- **WHEN** um jogo está rodando e depois o console volta ao menu parado
- **THEN** a frequência da CPU sobe durante o jogo e desce no menu, dentro da tabela do device tree

#### Scenario: Proteção térmica ativa
- **WHEN** as zonas térmicas são consultadas no console
- **THEN** existe uma zona da CPU com limite passivo ligado à CPU como dispositivo de resfriamento e um limite crítico

#### Scenario: Sem perfil válido
- **WHEN** o arquivo de perfis do console falta ou é recusado
- **THEN** a CPU usa o governor padrão do kernel, como antes dos perfis
