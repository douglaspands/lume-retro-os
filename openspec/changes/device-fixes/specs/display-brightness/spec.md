# Spec Delta

## Purpose

Brilho da tela sem trava fixa: um limite seguro aprendido por aparelho, mostrado ao usuário e
registrado, para os painéis que falham com brilho alto.

## ADDED Requirements

### Requirement: Brilho sem trava fixa
O brilho MUST ir do mínimo que não apaga a tela até o máximo do hardware em todos os
consoles. Nenhum console MUST ter um teto fixo de brilho.

#### Scenario: Brilho máximo no GA36
- **WHEN** o usuário sobe o brilho do GA36 até o fim
- **THEN** o brilho chega ao nível máximo do hardware

### Requirement: Limite seguro visível
Quando o aparelho tiver um limite seguro, a linha de brilho da borda da tela e a barra do
Brilho nas Configurações MUST marcar esse nível com um pontinho vermelho. Sem limite, nenhuma
marca aparece.

#### Scenario: Pontinho no GA36
- **WHEN** o usuário aperta Fn+Volume num GA36 com o limite no nível 7
- **THEN** a linha de brilho mostra um pontinho vermelho no nível 7

#### Scenario: Sem limite no R36S
- **WHEN** o usuário aperta Fn+Volume no R36S
- **THEN** a linha de brilho não mostra nenhum pontinho

### Requirement: Limite por aparelho
O limite MUST pertencer ao aparelho, não ao cartão: cada console identificado pelo número de
série MUST ter o próprio limite, guardado no cartão e preservado entre os boots e entre os
consoles que dividem o cartão. O primeiro limite de um GA36 MUST ser o nível 7.

#### Scenario: Cartão passado ao outro console
- **WHEN** o cartão vai de um GA36 com o limite no nível 6 para o R36S e volta
- **THEN** o GA36 continua com o limite no nível 6 e o R36S continua sem limite

### Requirement: Relato da falha pelo usuário
Um atalho (Fn+Select) MUST permitir ao usuário relatar "a tela falhou agora" a qualquer
momento. O relato MUST gravar no log o nível do brilho, a tensão e a corrente da bateria, a
temperatura, o carregador ligado e o tempo de tela acesa. MUST também baixar o limite para um
nível abaixo do atual e confirmar na tela.

#### Scenario: Falha relatada no nível 8
- **WHEN** a tela falha no nível 8 e o usuário aperta Fn+Select
- **THEN** o `events.log` registra o relato com as medidas, o limite passa a 7 e uma linha curta confirma na tela

### Requirement: Limite que aprende
Uma hora acumulada de uso acima do limite, sem nenhum relato, MUST subir o limite em um nível.
Cada mudança do limite MUST ser registrada no `events.log` com o valor antigo, o novo e o
motivo.

#### Scenario: Uso longo sem falha
- **WHEN** o usuário joga uma hora acumulada no nível 8 com o limite em 7, sem relato
- **THEN** o limite passa a 8 e o `events.log` registra `display OK limit 7 -> 8`

### Requirement: Recomeçar o aprendizado
O painel Brilho das Configurações MUST ter a ação "Recomeçar o aprendizado", com confirmação
(Sim em cima, Cancelar com o foco). Confirmada, ela MUST apagar o limite aprendido deste
aparelho e deixá-lo **sem limite**: o brilho vai até o máximo, sem pontinho, até o primeiro
relato (Fn+Select), que cria o limite de novo. Esse estado MUST ser guardado como "sem
limite", diferente de um aparelho sem arquivo (que usa o padrão do console). A mudança MUST
ser registrada no `events.log`. Os outros aparelhos que usam o mesmo cartão não mudam.

#### Scenario: Recomeçar no GA36
- **WHEN** o limite do GA36 está em 7 e o usuário confirma "Recomeçar o aprendizado"
- **THEN** o pontinho some, o brilho vai até 10, e o `events.log` registra `display OK limit 7 -> none (reset)`

#### Scenario: Relato depois de recomeçar
- **WHEN** o aprendizado foi recomeçado e a tela falha no nível 9 com o relato Fn+Select
- **THEN** o limite passa a 8, o pontinho volta no 8 e o `events.log` registra o relato e `display OK limit none -> 8 (report)`
