# Spec Delta

## ADDED Requirements

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

## MODIFIED Requirements

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

### Requirement: Desligar com confirmação
O item Desligar do menu do sistema MUST pedir confirmação vertical, com Desligar em cima e Cancelar embaixo com o foco inicial. Confirmado, o aparelho MUST gravar o pendente e desligar.

#### Scenario: Cancelar é o padrão
- **WHEN** o usuário abre Desligar no menu do sistema e aperta A sem mover o foco
- **THEN** nada acontece e o aparelho continua ligado

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
