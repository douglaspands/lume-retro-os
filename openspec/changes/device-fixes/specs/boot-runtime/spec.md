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

## ADDED Requirements

### Requirement: Hora que só anda para a frente
Sem fonte de hora garantida, a hora do sistema MUST nunca voltar entre um desligamento e o
boot seguinte. Ela MUST ser gravada no cartão ao desligar e ao suspender, e restaurada no
boot como a maior entre a gravada, a data do build e o relógio do hardware. Uma fonte real,
quando houver, MUST corrigi-la. Nada disso MUST atrasar o boot até o frontend.

#### Scenario: Save depois de um reboot
- **WHEN** o usuário grava um save, desliga, liga e grava outro save
- **THEN** o segundo save tem data mais nova que o primeiro

#### Scenario: Cartão novo
- **WHEN** o console sobe sem hora gravada no cartão
- **THEN** a hora do sistema não é anterior à data do build

### Requirement: Nós de entrada só leitura para os jogos
Os dispositivos de entrada do controle integrado, do controle virtual e dos botões de energia
e de volume MUST ser só leitura para o usuário dos jogos. Só o serviço de entrada do sistema
MUST poder escrever neles. Controles USB MUST continuar graváveis pelo grupo de entrada, para
a vibração e os LEDs.

#### Scenario: Jogo tenta injetar um botão
- **WHEN** um processo do usuário dos jogos tenta escrever um evento no controle virtual
- **THEN** a escrita é recusada por permissão

#### Scenario: Vibração num controle USB
- **WHEN** um controle USB com vibração é ligado e um jogo a usa
- **THEN** a vibração funciona
