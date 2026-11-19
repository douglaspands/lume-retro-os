# Spec Delta

## ADDED Requirements

### Requirement: Idioma do sistema no ambiente do jogo
Todo jogo aberto pelo launcher, em qualquer runner, MUST receber `LANG` e `LANGUAGE` do idioma
escolhido no launcher (inglês `en_US.UTF-8`, português `pt_BR.UTF-8`, espanhol `es_ES.UTF-8`),
lido a cada jogo, e MUST NOT receber `LC_ALL`. Os logs do sistema MUST continuar em inglês.

#### Scenario: Jogo de LÖVE em português
- **WHEN** o idioma do launcher é português e o usuário abre um jogo de LÖVE que escolhe o idioma pelo `LANG`
- **THEN** o jogo recebe `LANG=pt_BR.UTF-8` e mostra os textos em português

#### Scenario: Troca de idioma sem reiniciar
- **WHEN** o usuário troca o idioma do launcher para espanhol e abre um jogo
- **THEN** esse jogo já recebe `LANG=es_ES.UTF-8`

#### Scenario: Idioma não definido
- **WHEN** o cartão não tem idioma salvo no launcher
- **THEN** o jogo recebe `LANG=en_US.UTF-8`

### Requirement: Variáveis de ambiente do runner
O arquivo de um runner MUST poder declarar variáveis de ambiente que todo jogo daquele runner
recebe. Elas MUST ser aplicadas depois do idioma e do fuso, e uma variável com nome inválido
MUST tornar o runner inválido, com uma linha no log.

#### Scenario: Variável do LÖVE
- **WHEN** o runner do LÖVE declara uma variável do driver de vídeo
- **THEN** todo jogo de LÖVE aberto pelo launcher a recebe, e os jogos de outros runners não

#### Scenario: Nome inválido
- **WHEN** um runner do cartão declara uma variável com `=` no nome
- **THEN** o runner é ignorado com uma linha no log, e os outros continuam

### Requirement: Fuso do sistema no ambiente do jogo
Todo jogo aberto pelo launcher, em qualquer runner, MUST receber em `TZ` o fuso configurado no
sistema, para mostrar a hora local.

#### Scenario: Hora local num jogo
- **WHEN** o fuso do sistema é `America/Sao_Paulo` e um jogo de LÖVE mostra a hora
- **THEN** a hora mostrada é a de São Paulo, igual à do relógio do launcher
