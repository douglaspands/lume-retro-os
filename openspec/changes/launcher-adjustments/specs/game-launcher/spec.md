# Spec Delta

## ADDED Requirements

### Requirement: Menu do sistema pelo toque no Fn
Em qualquer tela do launcher, o toque no Fn (apertado e solto sozinho) MUST abrir o menu do sistema por cima da tela atual, com Desligar, Reiniciar e Configurações. Outro toque no Fn ou B MUST fechar o menu e voltar exatamente ao ponto de onde ele foi aberto. Um acorde com o Fn MUST NOT abrir o menu.

#### Scenario: Abrir no Dock
- **WHEN** o usuário toca o Fn na tela de consoles
- **THEN** o menu do sistema aparece com Desligar, Reiniciar e Configurações

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
O item Reiniciar do menu do sistema MUST pedir confirmação, com Cancelar como opção inicial. Confirmado, o aparelho MUST gravar o pendente e reiniciar, voltando ao launcher.

#### Scenario: Reiniciar confirmado
- **WHEN** o usuário escolhe Reiniciar e confirma
- **THEN** o aparelho grava o pendente, reinicia e o launcher reaparece, com o boot seguinte registrando o desligamento anterior como limpo

#### Scenario: Cancelar é o padrão
- **WHEN** o usuário escolhe Reiniciar e aperta A sem mover o foco
- **THEN** nada acontece e o launcher continua na tela

### Requirement: Cores por console no tema
Um tema MUST poder declarar, por sistema, as cores do item do Dock (fundo e conteúdo, normal e em foco), herdadas como os outros tokens. O logo usado como máscara e a sigla MUST ser pintados nessas cores. Um sistema sem cores declaradas MUST usar as cores gerais do ícone. O tema Lume da imagem MUST trazer as cores oficiais dos logos dos consoles.

#### Scenario: Tema Lume com cores
- **WHEN** o launcher abre com o tema Lume e o Dock mostra SNES e Mega Drive
- **THEN** cada item aparece nas cores oficiais do seu console, com e sem foco

#### Scenario: Tema sem cores por console
- **WHEN** o usuário escolhe o tema Material escuro
- **THEN** todos os itens do Dock aparecem nas cores gerais do ícone, como antes

#### Scenario: Cor inválida
- **WHEN** um tema do cartão declara uma cor inválida para um sistema
- **THEN** o launcher usa a cor herdada para esse token e registra o erro no log

### Requirement: Logo colorido de um tema do cartão
Um tema do cartão MUST poder trazer um logo colorido por sistema, mostrado como imagem com as cores dele, no lugar da máscara pintada. Os temas da imagem MUST NOT trazer logos coloridos.

#### Scenario: Logo colorido no cartão
- **WHEN** o tema do cartão traz um logo colorido do SNES
- **THEN** o item do SNES no Dock mostra o logo com as cores do arquivo, com e sem foco

#### Scenario: Máscara e colorido no mesmo tema
- **WHEN** o tema do cartão traz o logo colorido do SNES e só a máscara do NES
- **THEN** o SNES aparece com o logo colorido e o NES com a máscara pintada na cor do tema

## MODIFIED Requirements

### Requirement: Ícones de console próprios
Os itens do Dock MUST ser desenhados pelo tema a partir do nome e da sigla do sistema, nas cores que o tema declara para o sistema. A imagem MUST NOT vir de um logotipo de fabricante trazido pela distro; as cores sozinhas não são logotipo. Um tema instalado pelo usuário no cartão MAY trazer imagens próprias para os ícones, em máscara ou coloridas.

#### Scenario: Imagem padrão
- **WHEN** o launcher abre com o tema padrão
- **THEN** cada console aparece como um tile com a sigla (por exemplo "SNES"), nas cores do console, e nenhum arquivo de logotipo de fabricante é lido

### Requirement: Configurações do aparelho
O item Configurações MUST oferecer Idioma, Tema, Tela (por enquanto, mostrar ou não o percentual da bateria; ligado de fábrica), Volume, Brilho, Sistema, Games (com Atualizar listas, uma ação do painel que A executa) e RetroArch, numa lista à esquerda, com o painel do item em foco à direita (pouco mais da metade da tela) mostrando o valor, o nível ou o que o item faz, e onde os valores são mudados. A lista MUST dar a volta: para baixo no último item vai ao primeiro, para cima no primeiro vai ao último. Wi-Fi e Bluetooth MUST aparecer só quando houver adaptador presente. As escolhas MUST sobreviver ao reboot.

#### Scenario: Lista que dá a volta
- **WHEN** o foco está em RetroArch, o último item, e o usuário aperta para baixo
- **THEN** o foco vai para o primeiro item

#### Scenario: Sem dongle
- **WHEN** nenhum adaptador Wi-Fi está conectado
- **THEN** o item Wi-Fi não aparece

#### Scenario: Menu do RetroArch
- **WHEN** o usuário escolhe o item RetroArch
- **THEN** o menu completo do RetroArch abre sem jogo e, ao sair dele, o launcher reaparece nas Configurações

#### Scenario: Desligar não está nas Configurações
- **WHEN** o usuário percorre a lista das Configurações
- **THEN** não há item Desligar; desligar é pelo menu do sistema (toque no Fn)

### Requirement: Desligar com confirmação
O item Desligar do menu do sistema MUST pedir confirmação, com Cancelar como opção inicial. Confirmado, o aparelho MUST gravar o pendente e desligar.

#### Scenario: Cancelar é o padrão
- **WHEN** o usuário abre Desligar no menu do sistema e aperta A sem mover o foco
- **THEN** nada acontece e o aparelho continua ligado

### Requirement: Navegação só com o gamepad
Toda ação do launcher MUST ser possível só com o controle integrado: D-pad, A, B, X, Y, L1, R1, Start, Select e Fn.

#### Scenario: Sem teclado
- **WHEN** o console não tem teclado conectado
- **THEN** o usuário consegue buscar, abrir, favoritar, configurar, desligar e reiniciar
