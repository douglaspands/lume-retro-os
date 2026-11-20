# Spec Delta

## Purpose

Define como a distro afina cada core do RetroArch e o runner do LÖVE só por configuração, por
console, a partir de uma linha de base medida, e como os padrões novos chegam a cartões que já
existem sem apagar o que o usuário mudou.

## ADDED Requirements

### Requirement: Linha de base medida antes de afinar
Antes de qualquer ajuste, a distro MUST registrar, para cada core do catálogo e para o runner do
LÖVE, em cada console (GA36 e R36S), as métricas de um jogo com a configuração padrão. O registro
MUST ser agregado por core e por console, sem nome de jogo, caminho de ROM nem resultado por jogo.

#### Scenario: Base de um core
- **WHEN** a linha de base do `gpsp` no GA36 é medida
- **THEN** o relatório traz quadros mostrados por segundo, velocidade do core, falhas de áudio, clock médio escolhido pelo governor e temperatura desse core nesse console, sem citar o jogo usado

#### Scenario: Ajuste sem base
- **WHEN** um ajuste de um core é proposto sem a linha de base desse core naquele console
- **THEN** o ajuste não entra na imagem

### Requirement: Ajuste aceito só com ganho medido
Uma chave ou opção ajustada MUST entrar na imagem só quando a medição A/B no console mostrar que
ela mantém a velocidade cheia do core e o som contínuo e melhora pelo menos uma métrica (mais
quadros mostrados, clock médio menor ou temperatura menor) sem piorar as outras além da variação
medida entre duas execuções iguais.

#### Scenario: Clock menor com a mesma velocidade
- **WHEN** uma opção do core mantém 100% da velocidade e o governor passa a escolher um clock médio menor
- **THEN** a opção entra como padrão daquele core naquele console

#### Scenario: Ganho de um lado, perda do outro
- **WHEN** uma chave aumenta os quadros mostrados mas causa falhas de áudio
- **THEN** a chave não entra na imagem

### Requirement: Chaves do RetroArch por core e por console
A distro MUST poder fixar chaves do RetroArch para um core em todos os consoles ou só num console.
Essas chaves MUST valer só durante a execução daquele core, MUST vencer o valor do usuário nessa
execução e MUST devolver o valor do usuário quando o jogo terminar. A chave de um console MUST
vencer a chave do mesmo core para todos.

#### Scenario: Chave só do GA36
- **WHEN** o `pcsx_rearmed` tem uma chave para todos os consoles e outra, com a mesma chave, só para o GA36
- **THEN** no GA36 vale a do GA36, no R36S vale a de todos, e o valor salvo do usuário volta ao fim de cada jogo

#### Scenario: Core sem chave própria
- **WHEN** um core sem nenhuma chave fixada abre um jogo
- **THEN** o RetroArch roda só com as chaves comuns e as do console

### Requirement: Opções de core de fábrica
Cada core ajustado MUST ter um arquivo de opções de fábrica com os valores escolhidos. Os valores
de fábrica MUST valer enquanto o usuário não mudar a opção no menu do core, e a mudança do usuário
MUST ser salva no cartão e mantida em imagens novas.

#### Scenario: Primeiro jogo do core
- **WHEN** um jogo do `genesis_plus_gx` abre num cartão sem opções salvas desse core
- **THEN** o core roda com as opções de fábrica

#### Scenario: Usuário muda uma opção
- **WHEN** o usuário muda uma opção do core no Quick Menu e o cartão recebe uma imagem nova
- **THEN** a opção continua com o valor do usuário

### Requirement: Padrões novos em cartões existentes
Um padrão de fábrica novo (chave do RetroArch ou opção de core) MUST ser aplicado uma única vez a
cada cartão, mesmo que o arquivo do cartão já traga essa chave ou opção com o valor padrão do
RetroArch ou do core (o RetroArch grava todas as chaves e opções ao sair). O cartão MUST guardar
quais padrões já foram aplicados; depois da primeira aplicação, o valor do cartão MUST NOT ser
mudado pela distro. Um padrão que muda de valor numa imagem seguinte conta como padrão novo.

#### Scenario: Cartão de antes da mudança
- **WHEN** um cartão cujo `retroarch.cfg` traz `input_player1_analog_dpad_mode = "0"` (gravado pelo RetroArch) inicia a imagem nova pela primeira vez
- **THEN** a chave passa ao valor de fábrica, o cartão registra que esse padrão foi aplicado, e as outras chaves do usuário ficam como estavam

#### Scenario: Padrão aplicado não volta
- **WHEN** o padrão já foi aplicado num cartão e o RetroArch volta a gravar o arquivo com todas as chaves
- **THEN** a distro não aplica o padrão de novo

#### Scenario: Usuário já escolheu
- **WHEN** o usuário desligou o analógico como direcional no menu e o cartão recebe outra imagem
- **THEN** o analógico continua desligado

### Requirement: Analógico replica o direcional
De fábrica, o analógico esquerdo MUST mover como o direcional nos jogos das portas 1 a 4, em todos
os cores. O direcional MUST continuar funcionando junto. No PS1 com o controle DualShock escolhido,
o analógico MUST chegar ao jogo como analógico, sem replicar o direcional.

#### Scenario: Jogo de NES pelo analógico
- **WHEN** o usuário move o analógico esquerdo para a direita num jogo de NES
- **THEN** o personagem anda para a direita, como pelo direcional

#### Scenario: Controle USB do jogador 2
- **WHEN** um controle USB com analógico é o jogador 2 num jogo de Mega Drive
- **THEN** o analógico dele também move como o direcional

#### Scenario: PS1 com DualShock
- **WHEN** o usuário escolhe o DualShock no core do PS1 e abre um jogo com suporte a analógico
- **THEN** o jogo recebe o analógico, e o direcional segue separado

### Requirement: LÖVE nos testes de desempenho
O runner do LÖVE MUST passar pela mesma linha de base e pela mesma medição A/B dos cores, com o
ambiente do runner (variáveis do SDL e do driver de vídeo) como o que é ajustado. Um ajuste aceito
MUST valer para todos os jogos de LÖVE pelo arquivo do runner.

#### Scenario: Variável aceita
- **WHEN** uma variável do driver de vídeo diminui o clock médio dos jogos de LÖVE medidos sem perder quadros
- **THEN** o runner do LÖVE passa a abrir todo jogo com ela

### Requirement: Relatório de afinação
A distro MUST manter um relatório por core e por console com a linha de base, cada ajuste testado,
o resultado agregado e a decisão (aceito ou recusado), sem nome de jogo, caminho de ROM nem
resultado por jogo, para a otimização por compilação comparar contra o estado afinado.

#### Scenario: Comparação da otimização por compilação
- **WHEN** a otimização por compilação de um core é medida
- **THEN** o relatório de afinação traz a base afinada desse core em cada console para a comparação
