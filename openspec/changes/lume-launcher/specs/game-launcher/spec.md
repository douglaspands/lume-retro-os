# Spec Delta

## Purpose

Define a interface do lume-launcher: como o usuário encontra e abre jogos só com o gamepad, o que cada tela mostra, as configurações do aparelho e as metas de consumo que o launcher precisa cumprir nos consoles fracos.

## ADDED Requirements

### Requirement: Dock de consoles
A tela inicial MUST mostrar um Dock horizontal, de rotação infinita, com um item por sistema que tenha ao menos um jogo, mais Favoritos (primeiro item), Recentes e Configurações (último item). O D-pad gira o Dock e A entra no item.

#### Scenario: Rotação infinita
- **WHEN** o foco está em Configurações e o usuário aperta direita
- **THEN** o foco vai para Favoritos

#### Scenario: Sistema sem jogos
- **WHEN** `roms/psx/` não tem nenhum jogo listado
- **THEN** o PlayStation não aparece no Dock

### Requirement: Ícones de console próprios
Os itens do Dock MUST ser desenhados pelo tema a partir do nome e da sigla do sistema. A imagem MUST NOT vir de um logotipo de fabricante trazido pela distro. Um tema instalado pelo usuário no cartão MAY trazer imagens próprias para os ícones.

#### Scenario: Imagem padrão
- **WHEN** o launcher abre com o tema padrão
- **THEN** cada console aparece como um tile com a sigla (por exemplo "SNES") e nenhum arquivo de logotipo de fabricante é lido

### Requirement: Grade de jogos com capas
Ao entrar num sistema, o launcher MUST mostrar os jogos numa grade com a capa (`<image>` do `gamelist.xml`) e o nome. Um jogo sem capa válida MUST aparecer com uma caixa gerada com o nome. B volta ao Dock.

#### Scenario: Capa inválida
- **WHEN** o `<image>` de um jogo aponta para um arquivo que não é PNG, JPEG nem WebP
- **THEN** o jogo aparece com a caixa gerada e o launcher não falha

#### Scenario: Voltar ao Dock
- **WHEN** o usuário aperta B na grade
- **THEN** o Dock reaparece com o foco no mesmo sistema

### Requirement: Navegação rápida em listas grandes
Na grade, L1 e R1 MUST saltar uma fração proporcional ao tamanho da lista, nunca menos de uma página, e o salto MUST acelerar quando o botão é repetido em sequência.

#### Scenario: Salto numa lista grande
- **WHEN** o usuário aperta R1 uma vez numa lista de 1000 jogos
- **THEN** o foco avança mais de uma página de uma só vez

### Requirement: Busca por nome
Na grade, X MUST abrir a busca como num launcher de TV: a barra de busca no lugar do cabeçalho, com o texto digitado e o número de jogos, o teclado na tela embaixo, e a lista entre os dois, filtrada a cada letra. B MUST fechar o teclado e a barra e manter o filtro na lista. O filtro MUST ignorar maiúsculas e acentos e exigir todas as palavras digitadas. B na lista limpa o filtro antes de sair dela.

#### Scenario: Filtrar enquanto digita
- **WHEN** o usuário abre a busca e digita "su"
- **THEN** a lista entre a barra e o teclado já mostra só os jogos com "su", e a barra mostra quantos são

#### Scenario: B abaixa o teclado
- **WHEN** o usuário aperta B com o teclado aberto
- **THEN** o teclado e a barra somem, a lista continua filtrada e o filtro aparece no cabeçalho

#### Scenario: Filtro por duas palavras
- **WHEN** o usuário digita "super bros"
- **THEN** só aparecem os jogos cujo nome contém as duas palavras, sem diferença de maiúsculas ou acentos

### Requirement: Menu do jogo
A num jogo MUST abrir o menu do jogo com: Iniciar jogo, Save states, Configurações e Favoritos. Configurações MUST abrir Emulador, Aspecto e Shader do jogo; Aspecto e Shader MUST aparecer só quando o emulador efetivo é um core do RetroArch. B nas Configurações MUST voltar ao menu do jogo.

#### Scenario: Emulador standalone
- **WHEN** o emulador efetivo de um jogo não é um core do RetroArch
- **THEN** as Configurações do jogo não mostram Aspecto nem Shader

#### Scenario: Core fora do menu principal
- **WHEN** o usuário abre o menu de um jogo
- **THEN** vê Iniciar jogo, Save states, Configurações e Favoritos, e o Emulador só aparece dentro de Configurações

### Requirement: Iniciar de um save state
"Save states" MUST listar só os slots do core efetivo do jogo, com a imagem do slot em foco quando o RetroArch a salvou junto do estado. Quando o jogo tem save states só de outro core, a linha MUST ficar indisponível e dizer quantos estão em outro core. Escolher um slot MUST abrir o jogo já nesse estado.

#### Scenario: Imagem do save state
- **WHEN** o usuário põe o foco num slot que tem `<estado>.png` ao lado
- **THEN** a imagem aparece ao lado da lista; num slot sem imagem aparece "Sem imagem"

#### Scenario: Saves em outro core
- **WHEN** um jogo tem 2 save states do Snes9x e o core efetivo é o Snes9x 2010
- **THEN** a linha fica indisponível e mostra "2 em outro core"

#### Scenario: Abrir num slot
- **WHEN** o usuário escolhe o slot 3 de um jogo do RetroArch
- **THEN** o jogo abre já no estado do slot 3

### Requirement: Opções em três camadas
Emulador, aspecto e shader MUST ser resolvidos na ordem: escolha do jogo, padrão do console, padrão do catálogo. O jogo MUST guardar só o que difere. Y na grade abre as opções do console, com "Limpar opções dos jogos". Jogos com opção própria MUST ter um selo na grade.

#### Scenario: Padrão do console vale para todos sem exceção
- **WHEN** o usuário troca o emulador padrão do SNES e um jogo do SNES tem emulador próprio
- **THEN** os outros jogos do SNES abrem com o novo padrão e aquele jogo continua com o dele

#### Scenario: Voltar ao padrão
- **WHEN** o usuário escolhe "Padrão" no Emulador de um jogo
- **THEN** a exceção do jogo é apagada e o selo some da grade

### Requirement: Favoritos e Recentes
O usuário MUST poder marcar e desmarcar um jogo como favorito no menu do jogo. Favoritos MUST reunir os favoritos de todos os sistemas, e Recentes os últimos jogos abertos, do mais novo ao mais antigo. As duas listas MUST sobreviver ao reboot.

#### Scenario: Favorito persiste
- **WHEN** o usuário favorita um jogo e reinicia o console
- **THEN** o jogo aparece em Favoritos

#### Scenario: Recentes em ordem
- **WHEN** o usuário joga A e depois B
- **THEN** Recentes mostra B antes de A

### Requirement: Voltar ao mesmo lugar depois do jogo
Quando um jogo termina, por qualquer motivo, o launcher MUST reaparecer no mesmo sistema, com o foco no jogo que foi aberto e o filtro de busca que estava ativo.

#### Scenario: Saída do jogo
- **WHEN** o usuário sai de um jogo da posição 240 da lista do NES
- **THEN** o launcher reaparece na grade do NES com o foco nesse jogo

### Requirement: Configurações do aparelho
O item Configurações MUST oferecer Idioma, Tema, Volume, Brilho, Sistema, Atualizar listas, RetroArch e Desligar, numa lista à esquerda, com o painel do item em foco à direita (pouco mais da metade da tela) mostrando o valor, o nível ou o que o item faz. A lista MUST dar a volta: para baixo no último item vai ao primeiro, para cima no primeiro vai ao último. Wi-Fi e Bluetooth MUST aparecer só quando houver adaptador presente. As escolhas MUST sobreviver ao reboot.

#### Scenario: Lista que dá a volta
- **WHEN** o foco está em Desligar, o último item, e o usuário aperta para baixo
- **THEN** o foco vai para o primeiro item

#### Scenario: Sem dongle
- **WHEN** nenhum adaptador Wi-Fi está conectado
- **THEN** o item Wi-Fi não aparece

#### Scenario: Menu do RetroArch
- **WHEN** o usuário escolhe o item RetroArch
- **THEN** o menu completo do RetroArch abre sem jogo e, ao sair dele, o launcher reaparece nas Configurações

### Requirement: Volume na tela
Com o launcher na tela, cada aperto dos botões de volume MUST aparecer na hora: nas Configurações, como o percentual do item Volume; nas outras telas, como uma linha fina em toda a borda direita da tela, nas cores do tema, preenchida de baixo para cima até o nível (100% é a borda inteira), sem número, que some sozinha pouco depois do último aperto. Enquanto a linha aparece, nada da tela pode encostar nela. O aperto no limite (0% ou 100%) MUST mostrar a linha também.

#### Scenario: Linha fora das Configurações
- **WHEN** o usuário aperta volume - na grade de jogos
- **THEN** a linha da borda direita mostra o novo nível e some cerca de 1,5 s depois

#### Scenario: Dock afastado da linha
- **WHEN** a linha do volume aparece com o Dock na tela
- **THEN** o ícone mais à direita termina antes dela, com o espaço entre ícones

#### Scenario: Percentual nas Configurações
- **WHEN** o usuário aperta volume + com as Configurações abertas no item Volume
- **THEN** o percentual do painel do Volume muda na hora, sem a barra

### Requirement: Desligar com confirmação
O item Desligar MUST pedir confirmação, com Cancelar como opção inicial. Confirmado, o aparelho MUST gravar o pendente e desligar.

#### Scenario: Cancelar é o padrão
- **WHEN** o usuário abre Desligar e aperta A sem mover o foco
- **THEN** nada acontece e o aparelho continua ligado

### Requirement: Painel Sistema sob demanda
O painel Sistema MUST mostrar modelo, CPU, memória, cartão, bateria e a memória residente do próprio launcher. Os valores MUST ser lidos só enquanto o item estiver selecionado, cerca de uma vez por segundo, e a leitura MUST parar ao sair dele.

#### Scenario: Leitura para ao sair
- **WHEN** o foco sai do item Sistema
- **THEN** o launcher para de ler `/proc` e `/sys` e volta a ficar parado sem input

### Requirement: Idioma do launcher
O launcher MUST ter textos em inglês, português e espanhol, com as mesmas chaves nos três. O idioma escolhido MUST valer também para o RetroArch e para as mensagens do sistema.

#### Scenario: Troca de idioma
- **WHEN** o usuário escolhe Español
- **THEN** o launcher passa a mostrar os textos em espanhol na hora, e o próximo jogo aberto no RetroArch mostra o menu em espanhol

### Requirement: Tema declarativo
A aparência MUST vir de um tema em arquivo de dados, sem código, com herança entre temas. A distro MUST trazer o tema Lume, que é o padrão, e os temas Material escuro e claro. Animação e transparência MUST ser só tokens do tema (`anim_ms` 0 desliga a animação); não há Modo lite (removido a pedido do usuário em 2026-11-14).

#### Scenario: Tema inválido
- **WHEN** um tema do cartão tem um valor inválido
- **THEN** o launcher registra o erro no log e usa o tema padrão

### Requirement: Layout independente da resolução
O layout MUST usar unidades relativas à tela e ficar legível a 640x480, 854x480 e 720x720, sem texto cortado nas Configurações em nenhum dos três idiomas.

#### Scenario: Tela quadrada
- **WHEN** o launcher roda numa tela de 720x720
- **THEN** a grade ganha linhas e o Dock e as Configurações cabem sem corte

### Requirement: Navegação só com o gamepad
Toda ação do launcher MUST ser possível só com o controle integrado: D-pad, A, B, X, Y, L1, R1, Start e Select.

#### Scenario: Sem teclado
- **WHEN** o console não tem teclado conectado
- **THEN** o usuário consegue buscar, abrir, favoritar, configurar e desligar

### Requirement: Parado não consome CPU
Sem input e sem animação em curso, o launcher MUST ficar bloqueado esperando eventos, sem redesenhar a tela.

#### Scenario: Launcher parado
- **WHEN** o launcher fica 60 segundos sem input na grade
- **THEN** o uso de CPU do processo nesse intervalo fica abaixo de 1% de um núcleo

### Requirement: Memória com teto fixo
O cache de capas MUST ter um teto fixo em bytes, independente do número de jogos. O launcher MUST manter na memória só as capas visíveis e as vizinhas.

#### Scenario: Coleção grande
- **WHEN** o usuário percorre um sistema de 5000 jogos de ponta a ponta
- **THEN** a memória residente do launcher não ultrapassa a do início em mais que o teto do cache

### Requirement: Primeira tela rápida
O launcher MUST mostrar a primeira tela a partir do índice já gerado, sem esperar o scan dos jogos. Num jogo que termina, a lista MUST reaparecer em até 1 segundo no GA36.

#### Scenario: Boot com índice pronto
- **WHEN** o console liga com o índice de um boot anterior
- **THEN** o Dock aparece antes do fim do scan, e jogos novos entram quando o scan termina

#### Scenario: Volta do jogo no GA36
- **WHEN** o usuário encerra um jogo no GA36
- **THEN** a grade aparece em até 1 segundo depois que o jogo fecha
