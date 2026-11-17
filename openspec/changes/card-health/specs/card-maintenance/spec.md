# Spec Delta

## Purpose

Define a manutenção do cartão de memória que o usuário pede pelo launcher (TRIM e verificação no
próximo boot), o registro de quando cada uma rodou, sem depender de relógio, e o read-ahead do
cartão.

## ADDED Requirements

### Requirement: Otimizar o cartão a pedido
"Otimizar agora" MUST rodar o TRIM da partição `ROMS` montada, sem reiniciar, mostrando que está em andamento e, ao fim, o resultado (quanto foi liberado ou o erro). Um segundo pedido com o primeiro em andamento MUST ser ignorado. O resultado MUST ir para o `events.log`.

#### Scenario: Otimização concluída
- **WHEN** o usuário escolhe "Otimizar agora" no item Cartão
- **THEN** o painel mostra que está otimizando e depois o resultado, e o `events.log` ganha uma linha `card OK trim` com o tamanho liberado

#### Scenario: Cartão sem suporte
- **WHEN** o cartão ou o leitor recusa o TRIM
- **THEN** o painel mostra que o cartão não aceita a otimização, o `events.log` registra `card FAIL trim` com o motivo, e nada mais muda

### Requirement: Verificação no próximo boot
"Verificar no próximo boot" MUST deixar um pedido que o boot seguinte consome: ele roda a verificação e o reparo da `ROMS` antes de montá-la e apaga o pedido. O pedido MUST valer uma vez só e MUST sobreviver a um desligamento pelo botão.

#### Scenario: Pedido consumido
- **WHEN** o usuário pede a verificação e reinicia o console
- **THEN** o boot seguinte verifica a `ROMS`, mostra o resultado na tela e no log, e o boot depois dele não verifica de novo

### Requirement: Quando foi a última manutenção
O item Cartão MUST mostrar o espaço livre da `ROMS` e em que boot (número do contador de boots) foram a última otimização e a última verificação, ou "nunca". Nenhuma data MUST ser usada.

#### Scenario: Depois de uma otimização
- **WHEN** o usuário otimiza o cartão no boot 150 e abre o item Cartão no boot 152
- **THEN** o painel mostra a última otimização no boot 150

### Requirement: Manutenção sem custo parada
O serviço que executa a manutenção MUST NOT consumir CPU nem acordar periodicamente enquanto nenhum pedido existe, e MUST executar só os dois pedidos do item Cartão.

#### Scenario: Sem pedido
- **WHEN** o console fica no launcher por 5 minutos sem pedido de manutenção
- **THEN** o serviço de manutenção não usa CPU nesse intervalo

#### Scenario: Pedido desconhecido
- **WHEN** um pedido com outro verbo aparece na pasta de pedidos
- **THEN** ele é recusado com uma linha no log e nada é executado

### Requirement: Read-ahead do cartão
O cartão MUST usar o read-ahead escolhido pela medição desta versão, aplicado no boot a todo cartão de memória do console.

#### Scenario: Valor aplicado
- **WHEN** o console termina o boot
- **THEN** o `read_ahead_kb` do cartão é o valor escolhido, nos dois consoles
