# Spec Delta

## RENAMED Requirements

- FROM: `### Requirement: Verificação da partição de jogos a cada boot`
- TO: `### Requirement: Verificação da partição de jogos quando precisa`

## MODIFIED Requirements

### Requirement: Verificação da partição de jogos quando precisa
Antes de montar a partição `ROMS`, o boot MUST ler as marcas de volume sujo e de falha de mídia do exFAT e rodar a verificação e o reparo automático só quando uma delas estiver ligada ou quando houver um pedido de verificação do usuário. Num volume limpo, sem pedido, a verificação MUST NOT rodar. A partição MUST ser montada em `/storage`, com dono no usuário do frontend.

#### Scenario: Partição marcada como suja
- **WHEN** o sistema sobe depois de um desligamento abrupto que deixou a `ROMS` marcada como suja
- **THEN** a verificação roda, o resultado aparece na tela e no log, e a `ROMS` é montada em `/storage`

#### Scenario: Boot depois de um desligamento normal
- **WHEN** o sistema sobe depois de um desligamento pelo menu ou pelo botão
- **THEN** nenhuma verificação roda, o log registra `roms OK clean: check skipped`, e a `ROMS` é montada em `/storage`

#### Scenario: Pedido do usuário
- **WHEN** o volume está limpo e existe o pedido "Verificar no próximo boot"
- **THEN** a verificação roda, o pedido é apagado e o resultado aparece na tela e no log
