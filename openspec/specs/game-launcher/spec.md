# game-launcher Specification

## Purpose
Define a interface do lume-launcher: como o usuário encontra e abre jogos só com o gamepad, o que cada tela mostra, as configurações do aparelho e as metas de consumo que o launcher precisa cumprir nos consoles fracos.

## Requirements

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
O item Configurações MUST oferecer Idioma, Tema, Tela (por enquanto, mostrar ou não o percentual da bateria; ligado de fábrica), Volume, Brilho, Sistema, Cartão e Games (com Atualizar listas, uma ação do painel que A executa), numa lista à esquerda, com o painel do item em foco à direita (pouco mais da metade da tela) mostrando o valor, o nível ou o que o item faz, e onde os valores são mudados. Desligar, Suspender e Reiniciar MUST ficar só no menu do sistema, e o menu completo do RetroArch MUST NOT ser oferecido nas Configurações (o acesso a ele volta pela opção de liberar, P-101). A lista MUST dar a volta: para baixo no último item vai ao primeiro, para cima no primeiro vai ao último. Wi-Fi e Bluetooth MUST aparecer só quando houver adaptador presente. As escolhas MUST sobreviver ao reboot.

#### Scenario: Lista que dá a volta
- **WHEN** o foco está em Games, o último item sem adaptador, e o usuário aperta para baixo
- **THEN** o foco vai para o primeiro item

#### Scenario: Sem dongle
- **WHEN** nenhum adaptador Wi-Fi está conectado
- **THEN** o item Wi-Fi não aparece

#### Scenario: Menu do RetroArch
- **WHEN** o usuário procura o menu completo do RetroArch nas Configurações
- **THEN** não há item RetroArch; o acesso volta só pela opção de liberar (P-101)

#### Scenario: Sem Desligar nem RetroArch
- **WHEN** o usuário percorre a lista das Configurações
- **THEN** não há item Desligar, Suspender nem RetroArch; desligar, suspender e reiniciar são pelo menu do sistema (toque no Fn)

#### Scenario: Painel do Cartão
- **WHEN** o usuário põe o foco no item Cartão e entra no painel
- **THEN** vê o espaço livre, a última otimização e a última verificação pelo número do boot, e as ações "Otimizar agora" e "Verificar no próximo boot", que A executa

### Requirement: Foco no painel das Configurações
Nas Configurações, A ou ▶ num item da lista MUST levar o foco para o painel desse item. No painel, ▲▼ MUST escolher a linha, ◀▶ MUST mudar o valor da linha em foco e A MUST executar a ação dela; B MUST devolver o foco à lista no mesmo item. Na lista, ◀▶ MUST NOT mudar valores. O item cujo painel tem o foco MUST continuar marcado na lista.

#### Scenario: Mudar o volume pelo painel
- **WHEN** o usuário está no item Volume, aperta A, e depois ▶ duas vezes
- **THEN** o volume sobe dois passos e o foco continua no painel

#### Scenario: Voltar à lista
- **WHEN** o foco está numa linha do painel do Tema e o usuário aperta B
- **THEN** o foco volta para o item Tema da lista e as Configurações continuam abertas

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
O item Desligar do menu do sistema MUST pedir confirmação vertical, com Desligar em cima e Cancelar embaixo com o foco inicial. Confirmado, o aparelho MUST gravar o pendente e desligar.

#### Scenario: Cancelar é o padrão
- **WHEN** o usuário abre Desligar no menu do sistema e aperta A sem mover o foco
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
Toda ação do launcher MUST ser possível só com o controle integrado: D-pad, A, B, X, Y, L1, R1, Start, Select e Fn. Numa lista vertical ou numa confirmação com as opções uma embaixo da outra, só cima e baixo MUST trocar o item em foco; esquerda e direita MUST NOT trocar de item, e só servem para mudar o valor de uma linha com seletor ou passar para a coluna ao lado, quando houver uma.

#### Scenario: Sem teclado
- **WHEN** o console não tem teclado conectado
- **THEN** o usuário consegue buscar, abrir, favoritar, configurar, suspender, desligar e reiniciar

#### Scenario: Esquerda não troca a escolha numa confirmação
- **WHEN** a confirmação de Desligar está aberta com o foco em Cancelar e o usuário aperta para a esquerda ou para a direita
- **THEN** o foco continua em Cancelar

#### Scenario: Cima escolhe na confirmação
- **WHEN** a confirmação de Desligar está aberta com o foco em Cancelar e o usuário aperta para cima
- **THEN** o foco vai para Desligar, a opção de cima

#### Scenario: Seletor continua mudando o valor
- **WHEN** o foco está na linha do Tema, no painel, e o usuário aperta para a direita
- **THEN** o tema muda para o próximo e o foco continua na mesma linha

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

### Requirement: Menu do sistema pelo toque no Fn
Em qualquer tela do launcher, o toque no Fn (apertado e solto sozinho) MUST abrir o menu do sistema por cima da tela atual, com Configurações, Suspender, Reiniciar e Desligar, nessa ordem, com o foco inicial em Configurações. Outro toque no Fn ou B MUST fechar o menu e voltar exatamente ao ponto de onde ele foi aberto. Um acorde com o Fn MUST NOT abrir o menu.

#### Scenario: Abrir no Dock
- **WHEN** o usuário toca o Fn na tela de consoles
- **THEN** o menu do sistema aparece com Configurações, Suspender, Reiniciar e Desligar

#### Scenario: Abrir na grade e voltar
- **WHEN** o usuário está na grade do SNES com o foco no décimo jogo, toca o Fn e depois aperta B
- **THEN** o menu some e a grade do SNES volta com o foco no mesmo jogo

#### Scenario: Fechar com outro toque
- **WHEN** o menu do sistema está aberto e o usuário toca o Fn
- **THEN** o menu some

#### Scenario: Brilho não abre o menu
- **WHEN** o usuário segura o Fn e aperta volume para mudar o brilho
- **THEN** o brilho muda e o menu do sistema não abre

### Requirement: Configurações pelo menu do sistema
O item Configurações do menu do sistema MUST abrir as Configurações do launcher; B nas Configurações MUST voltar à tela onde o menu foi aberto.

#### Scenario: Configurações a partir da grade
- **WHEN** o usuário, na grade do NES, toca o Fn, escolhe Configurações e depois aperta B
- **THEN** as Configurações abrem e, com o B, a grade do NES volta

### Requirement: Suspender pelo menu do sistema
O item Suspender do menu do sistema MUST suspender o console sem confirmação, como o toque curto no botão de energia; ao acordar, o launcher MUST voltar à tela de onde o menu foi aberto, com o menu fechado.

#### Scenario: Suspender pelo menu
- **WHEN** o usuário toca o Fn na grade, escolhe Suspender e aperta A
- **THEN** o console suspende e, ao acordar, a grade volta como estava

### Requirement: Dica do Fn no rodapé
O rodapé da tela de consoles MUST mostrar a dica do Fn (o glifo do Fn e "Menu"), como as outras dicas de botão, nos três idiomas.

#### Scenario: Dica visível
- **WHEN** o launcher mostra a tela de consoles
- **THEN** o rodapé tem a dica do Fn ao lado das dicas de A e do direcional

### Requirement: Dica dos atalhos ao segurar o Fn
Segurar o Fn sozinho no launcher MUST mostrar, por cima da tela, os atalhos com o Fn que valem no launcher (no mínimo o toque para o menu e Fn+Vol para o brilho), no idioma do usuário. Soltar o Fn MUST esconder a dica sem abrir o menu; um acorde MUST esconder a dica e agir.

#### Scenario: Ver os atalhos
- **WHEN** o usuário segura o Fn por 1 segundo na grade de jogos
- **THEN** aparece a dica com "Menu do sistema" e "Brilho"

#### Scenario: Soltar sem escolher
- **WHEN** a dica está na tela e o usuário solta o Fn
- **THEN** a dica some e o menu do sistema não abre

### Requirement: Reiniciar com confirmação
O item Reiniciar do menu do sistema MUST pedir confirmação vertical, com Reiniciar em cima e Cancelar embaixo com o foco inicial. Confirmado, o aparelho MUST gravar o pendente e reiniciar, voltando ao launcher.

#### Scenario: Reiniciar confirmado
- **WHEN** o usuário escolhe Reiniciar e confirma
- **THEN** o aparelho grava o pendente, reinicia e o launcher reaparece, com o boot seguinte registrando o desligamento anterior como limpo

#### Scenario: Cancelar é o padrão
- **WHEN** o usuário escolhe Reiniciar e aperta A sem mover o foco
- **THEN** nada acontece e o launcher continua na tela

### Requirement: Bateria carregando na barra de status
A bateria da barra de status do launcher MUST mostrar quando o console está carregando, com uma marca desenhada como no protótipo, e MUST refletir a ligação ou o desligamento do carregador em até 5 segundos.

#### Scenario: Ligar o carregador
- **WHEN** o usuário liga o carregador com o launcher na tela
- **THEN** em até 5 segundos a bateria da barra mostra a marca de carga, e a porcentagem acompanha a carga do kernel

#### Scenario: Desligar o carregador
- **WHEN** o carregador é desligado
- **THEN** em até 5 segundos a marca de carga some

### Requirement: Tela escurecida com o launcher parado
Com o launcher na tela e nenhum botão apertado por alguns minutos, a tela MUST escurecer até um brilho baixo sem apagar. O primeiro botão MUST só devolver o brilho escolhido pelo usuário, sem agir na tela. O brilho escolhido pelo usuário MUST NOT mudar por isso.

#### Scenario: Escurecer e voltar
- **WHEN** o launcher fica parado até escurecer e o usuário aperta B
- **THEN** a tela volta ao brilho de antes, o launcher continua na mesma tela, e o brilho salvo nas Configurações não muda
