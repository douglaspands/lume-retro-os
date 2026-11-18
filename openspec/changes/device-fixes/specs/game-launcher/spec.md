# Spec Delta

## MODIFIED Requirements

### Requirement: Configurações do aparelho
O item Configurações MUST oferecer Idioma, Tema, Tela (por enquanto, mostrar ou não o percentual da bateria; ligado de fábrica), Volume, Brilho, Sistema, Cartão, Games (com Atualizar listas, uma ação do painel que A executa), RetroArch, Suspender e Desligar, numa lista à esquerda, com o painel do item em foco à direita (pouco mais da metade da tela) mostrando o valor, o nível ou o que o item faz, e onde os valores são mudados. A lista MUST dar a volta: para baixo no último item vai ao primeiro, para cima no primeiro vai ao último. Wi-Fi e Bluetooth MUST aparecer só quando houver adaptador presente. As escolhas MUST sobreviver ao reboot.

#### Scenario: Lista que dá a volta
- **WHEN** o foco está em Desligar, o último item, e o usuário aperta para baixo
- **THEN** o foco vai para o primeiro item

#### Scenario: Sem dongle
- **WHEN** nenhum adaptador Wi-Fi está conectado
- **THEN** o item Wi-Fi não aparece

#### Scenario: Menu do RetroArch
- **WHEN** o usuário escolhe o item RetroArch
- **THEN** o menu completo do RetroArch abre sem jogo e, ao sair dele, o launcher reaparece nas Configurações

#### Scenario: Painel do Cartão
- **WHEN** o usuário põe o foco no item Cartão e entra no painel
- **THEN** vê o espaço livre, a última otimização e a última verificação pelo número do boot, e as ações "Otimizar agora" e "Verificar no próximo boot", que A executa

#### Scenario: Suspender pelas Configurações
- **WHEN** o usuário escolhe Suspender e aperta A
- **THEN** o console suspende como pelo toque no botão de energia, e ao acordar volta às Configurações

### Requirement: Navegação só com o gamepad
Toda ação do launcher MUST ser possível só com o controle integrado: D-pad, A, B, X, Y, L1, R1, Start e Select. Numa lista vertical ou numa confirmação com as opções uma embaixo da outra, só cima e baixo MUST trocar o item em foco; esquerda e direita MUST NOT trocar de item, e só servem para mudar o valor de uma linha com seletor ou passar para a coluna ao lado, quando houver uma.

#### Scenario: Sem teclado
- **WHEN** o console não tem teclado conectado
- **THEN** o usuário consegue buscar, abrir, favoritar, configurar e desligar

#### Scenario: Esquerda não troca a escolha numa confirmação
- **WHEN** a confirmação de Desligar está aberta com o foco em Cancelar e o usuário aperta para a esquerda ou para a direita
- **THEN** o foco continua em Cancelar

#### Scenario: Cima escolhe na confirmação
- **WHEN** a confirmação de Desligar está aberta com o foco em Cancelar e o usuário aperta para cima
- **THEN** o foco vai para Desligar, a opção de cima

#### Scenario: Seletor continua mudando o valor
- **WHEN** o foco está na linha do Tema, no painel, e o usuário aperta para a direita
- **THEN** o tema muda para o próximo e o foco continua na mesma linha
