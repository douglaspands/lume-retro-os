# Spec Delta

## Purpose

Define a barra de status que o usuário liga e desliga durante o jogo, à moda do Steam Deck:
uso de CPU, GPU, memória e bateria, com potência e tempo restante, sem custo quando escondida.

## ADDED Requirements

### Requirement: Barra ligada e desligada pelo Fn+X
A ação `hud` (Fn+X) MUST alternar a barra de status entre visível e escondida durante um jogo do RetroArch. A barra MUST começar escondida a cada boot e MUST continuar no estado escolhido de um jogo para o seguinte no mesmo boot. Fora de um jogo, Fn+X MUST NOT mudar a tela do launcher.

#### Scenario: Ligar e desligar
- **WHEN** o usuário aperta Fn+X durante um jogo e depois aperta Fn+X de novo
- **THEN** a barra aparece no topo da tela e, no segundo acorde, some

#### Scenario: Próximo jogo
- **WHEN** o usuário liga a barra, sai do jogo e abre outro jogo
- **THEN** a barra aparece no novo jogo sem apertar Fn+X

### Requirement: Barra só no topo, sobre o jogo
A barra MUST ocupar uma única faixa no topo da tela, por cima da imagem do jogo, sem mudar o tamanho nem a posição da imagem, e MUST ser legível a 640x480 nos dois consoles.

#### Scenario: Imagem do jogo intacta
- **WHEN** a barra está visível num jogo
- **THEN** o jogo continua com o mesmo tamanho e aspecto, e só a faixa do topo fica coberta

### Requirement: O que a barra mostra
A barra MUST mostrar, nesta ordem: CPU (ocupação média dos núcleos em % e clock atual), GPU (ocupação em %), memória como `usada/total/swap` em MB (o swap é o ZRAM em uso) e bateria (%, potência atual em W e tempo restante). Um valor que o aparelho não fornece MUST aparecer como `--`, sem esconder os outros.

#### Scenario: Formato da memória
- **WHEN** o sistema usa 124 MB de 1006 MB de RAM e 200 MB do swap
- **THEN** a barra mostra `MEM 124/1006/200`

#### Scenario: GPU sem leitura
- **WHEN** o driver da GPU não informa a ocupação
- **THEN** a barra mostra `GPU --` e os demais campos normalmente

### Requirement: Atualização da barra
Com a barra visível, os valores MUST ser atualizados a cada segundo.

#### Scenario: Valor muda com o jogo
- **WHEN** a barra está visível e a carga do jogo muda
- **THEN** a CPU mostrada acompanha a mudança em até 2 segundos

### Requirement: Tempo de bateria estimado
O tempo restante MUST vir do consumo médio recente (cerca do último minuto) aplicado à carga que resta, e MUST aparecer como `--:--` enquanto não houver medição suficiente, no máximo 30 segundos depois do início do jogo. Carregando, a barra MUST indicar que está carregando e mostrar o tempo até encher quando ele puder ser estimado.

#### Scenario: Logo depois de ligar
- **WHEN** a barra é ligada no começo de um jogo
- **THEN** o tempo restante aparece como `--:--` e, em até 30 segundos, vira uma estimativa em horas e minutos

#### Scenario: Carregando
- **WHEN** o carregador é ligado com a barra visível
- **THEN** a barra indica carga em até 5 segundos

### Requirement: Barra sem custo quando escondida
A barra MUST NOT acrescentar processo durante o jogo. Com a barra escondida, nenhuma leitura periódica para ela MUST rodar. Com a barra visível, a coleta e o envio MUST custar menos de 2% de um núcleo no GA36.

#### Scenario: Escondida
- **WHEN** a barra está escondida durante um jogo
- **THEN** o supervisor do jogo não acorda periodicamente e o uso de CPU dele fica igual ao de antes desta versão

#### Scenario: Custo visível
- **WHEN** a barra fica visível por 5 minutos num jogo no GA36
- **THEN** o supervisor usa menos de 2% de um núcleo nesse intervalo e nenhum processo novo aparece
