# Spec Delta

## ADDED Requirements

### Requirement: Aviso de início e fim do jogo ao sistema
O supervisor MUST avisar o sistema antes de iniciar cada jogo, com o sistema e o core, e depois que todos os processos do jogo terminarem, qualquer que seja o motivo do fim. O aviso MUST NOT atrasar a abertura do jogo esperando resposta, e um aviso que falhe MUST NOT impedir o jogo.

#### Scenario: Aviso no início e no fim
- **WHEN** um jogo de Game Boy é aberto no core `gambatte` e depois encerrado por Fn+Start
- **THEN** o sistema recebe o início com `gb` e `gambatte` antes do jogo aparecer, e o fim depois que o último processo do jogo saiu

#### Scenario: Ninguém escutando
- **WHEN** o serviço que recebe os avisos não está rodando e um jogo é aberto
- **THEN** o jogo abre no mesmo tempo de antes

### Requirement: Prioridade do jogo
Durante o jogo, os processos do jogo MUST ter prioridade de CPU e de disco acima dos serviços em segundo plano do sistema (índice de jogos, playlists, sincronização de saves, logs), sem passar à prioridade de tempo real. O daemon de entrada MUST ter prioridade acima do jogo, para o Fn+Start continuar encerrando um jogo travado.

#### Scenario: Serviço de fundo com o jogo aberto
- **WHEN** o índice de jogos roda enquanto um jogo está aberto
- **THEN** os processos do jogo têm prioridade maior que o índice, e nenhum deles roda em tempo real

#### Scenario: Jogo travado
- **WHEN** um jogo trava ocupando a CPU inteira e o usuário aperta Fn+Start
- **THEN** o jogo é encerrado e o launcher volta
