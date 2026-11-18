# Spec Delta

## ADDED Requirements

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

### Requirement: Relógio na tela
O launcher MUST poder mostrar a hora no mesmo lugar em todas as telas, como a bateria, na posição e no formato aprovados no protótipo. Uma opção das Configurações MUST ligar e desligar o relógio. Enquanto a hora do aparelho nunca tiver sido acertada (nenhuma fonte real desde a imagem), o relógio MUST NOT aparecer, para não mostrar uma hora errada.

#### Scenario: Mesmo lugar em todas as telas
- **WHEN** o relógio está ligado e o usuário passa do Dock para a grade, a busca e as Configurações
- **THEN** a hora aparece no mesmo lugar e no mesmo tamanho em todas elas

#### Scenario: Relógio desligado
- **WHEN** o usuário desliga "Mostrar relógio" nas Configurações
- **THEN** a hora some de todas as telas e a escolha sobrevive ao reboot

#### Scenario: Hora nunca acertada
- **WHEN** o aparelho nunca teve a hora acertada pelo cabo, pela rede ou à mão
- **THEN** o relógio não aparece, mesmo ligado

### Requirement: Acertar a hora nas Configurações
As Configurações MUST oferecer o acerto da data e da hora à mão, só com o controle. Confirmado, o acerto MUST valer para o sistema, para o relógio do aparelho e para a hora guardada no cartão, e MUST poder voltar a hora para trás (é uma fonte real, como o cabo e a rede).

#### Scenario: Acerto à mão
- **WHEN** o usuário ajusta a data e a hora com o direcional e confirma
- **THEN** o relógio da tela passa a mostrar a hora nova e ela continua certa depois de desligar e ligar

### Requirement: Telas de carregamento com barra de progresso
O sistema MUST mostrar uma tela própria do Lume, no tema ativo e com barra de progresso, em cada espera: a inicialização do sistema, o carregamento do jogo, a finalização do jogo, o encerramento ou reinício do sistema e as tarefas demoradas. A barra MUST seguir o tipo aprovado para cada tela (por etapas, por bytes ou indeterminada). A tela de inicialização MUST NOT deixar o boot mais lento: ela só usa as etapas que o boot já registra.

#### Scenario: Carregamento do jogo
- **WHEN** o usuário abre um jogo no launcher
- **THEN** a tela de carregamento aparece com a barra avançando pelas etapas até o primeiro quadro do jogo, sem tela preta entre elas

#### Scenario: Tarefa demorada
- **WHEN** uma tarefa demorada do sistema roda com a tela acesa (verificação do cartão, indexação)
- **THEN** a tela mostra o nome da tarefa e a barra de progresso até o fim

#### Scenario: Boot sem atraso
- **WHEN** o console liga com a tela de inicialização
- **THEN** o tempo de boot até o launcher não aumenta em relação ao boot sem ela

### Requirement: Wi-Fi nas Configurações
As Configurações MUST permitir ligar e desligar o Wi-Fi, procurar redes, conectar com senha pelo teclado da tela e esquecer redes salvas, só com o controle. A senha MUST NOT aparecer em argumento de processo nem em log.

#### Scenario: Conectar a uma rede nova
- **WHEN** o usuário escolhe uma rede com cadeado, digita a senha e confirma
- **THEN** o console conecta, a rede fica salva e reconecta sozinha depois do reboot

### Requirement: Bluetooth nas Configurações
As Configurações MUST permitir ligar e desligar o Bluetooth, procurar a pedido, parear, conectar, desconectar e esquecer aparelhos. Com um fone conectado, o som MUST ir para ele e voltar ao alto-falante quando ele desconecta, sem reiniciar o jogo.

#### Scenario: Fone Bluetooth
- **WHEN** o usuário pareia um fone pelo painel e abre um jogo
- **THEN** o som do jogo sai no fone, as teclas de volume mexem nele, e ao desligar o fone o som volta ao alto-falante

### Requirement: Modo avançado
As Configurações MUST oferecer um "Modo avançado", desligado de fábrica, que, ligado com confirmação, libera o menu completo do RetroArch durante o jogo; desligado, o menu do RetroArch MUST ficar preso ao Quick Menu.

#### Scenario: Liberar o RetroArch
- **WHEN** o usuário liga o Modo avançado e abre o menu do RetroArch num jogo
- **THEN** ele consegue sair do Quick Menu para a tela principal do RetroArch, e com o modo desligado não consegue

## MODIFIED Requirements

### Requirement: Ícones de console próprios
Os itens do Dock MUST ser desenhados pelo tema a partir do nome e da sigla do sistema, nas cores que o tema declara para o sistema. A imagem MUST NOT vir de um logotipo de fabricante trazido pela distro; as cores sozinhas não são logotipo. Um tema instalado pelo usuário no cartão MAY trazer imagens próprias para os ícones, em máscara ou coloridas.

#### Scenario: Imagem padrão
- **WHEN** o launcher abre com o tema padrão
- **THEN** cada console aparece como um tile com a sigla (por exemplo "SNES"), nas cores do console, e nenhum arquivo de logotipo de fabricante é lido
