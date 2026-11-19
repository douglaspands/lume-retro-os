# Spec Delta

## Purpose

Suspender e acordar o console pelo botão de energia, guardando o jogo, o som e o cartão, e
desligar pelo mesmo botão segurado.

## ADDED Requirements

### Requirement: Toque curto no botão de energia suspende
Um toque curto no botão de energia (solto antes de 1 s) MUST suspender o console, com o
launcher ou com um jogo na tela. Durante a suspensão, a tela, a luz de fundo e o som MUST
ficar desligados.

#### Scenario: Suspender no meio de um jogo
- **WHEN** o usuário toca o botão de energia durante um jogo
- **THEN** o jogo é pausado, a tela e o som se apagam e o console entra em suspensão

#### Scenario: Suspender no launcher
- **WHEN** o usuário toca o botão de energia com o launcher na tela
- **THEN** a tela e o som se apagam e o console entra em suspensão

### Requirement: Acordar no mesmo ponto
Outro toque no botão de energia MUST acordar o console e devolver a tela, o brilho, o volume
e o jogo como estavam antes da suspensão. O jogo MUST continuar sozinho. Os outros botões
MUST NOT acordar o console.

#### Scenario: Volta ao jogo
- **WHEN** o console está suspenso no meio de um jogo e o usuário toca o botão de energia
- **THEN** a tela volta com o mesmo brilho, o som com o mesmo volume, e o jogo continua do ponto em que parou

#### Scenario: Botão do jogo não acorda
- **WHEN** o console está suspenso e o usuário aperta A
- **THEN** o console continua suspenso

### Requirement: Botão segurado desliga
Segurar o botão de energia por 2 s MUST desligar o console pelo mesmo caminho do item
Desligar, gravando o pendente antes. Segurar por mais tempo MUST continuar desligando à força
pelo hardware, como reserva.

#### Scenario: Desligar pelo botão
- **WHEN** o usuário segura o botão de energia por 2 s durante um jogo
- **THEN** os saves e a configuração são gravados, e o console desliga com o volume `ROMS` limpo

### Requirement: Cartão seguro na suspensão
Antes de suspender, tudo o que estava pendente de gravação no cartão MUST ser gravado, para
que uma perda de energia durante a suspensão não perca saves nem deixe o cartão inconsistente.

#### Scenario: Bateria acaba suspenso
- **WHEN** a bateria acaba com o console suspenso
- **THEN** o save gravado antes da suspensão está no cartão no boot seguinte

### Requirement: Falha na suspensão não deixa o console apagado
Se a suspensão falhar, o console MUST voltar ao estado de antes, com a tela acesa, e MUST
registrar o motivo no log.

#### Scenario: Kernel recusa a suspensão
- **WHEN** o kernel recusa entrar em suspensão
- **THEN** a tela volta acesa no mesmo ponto e o `events.log` registra `sleep FAIL` com o motivo

### Requirement: Registro da suspensão
Cada suspensão e cada retorno MUST ser registrados no `events.log`, com o modo usado e o
tempo suspenso.

#### Scenario: Suspensão registrada
- **WHEN** o console suspende e acorda depois de 10 minutos
- **THEN** o `events.log` tem `sleep OK suspend <modo>` e `sleep OK resume after` com cerca de 600 s
