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

## MODIFIED Requirements

### Requirement: Ícones de console próprios
Os itens do Dock MUST ser desenhados pelo tema a partir do nome e da sigla do sistema, nas cores que o tema declara para o sistema. A imagem MUST NOT vir de um logotipo de fabricante trazido pela distro; as cores sozinhas não são logotipo. Um tema instalado pelo usuário no cartão MAY trazer imagens próprias para os ícones, em máscara ou coloridas.

#### Scenario: Imagem padrão
- **WHEN** o launcher abre com o tema padrão
- **THEN** cada console aparece como um tile com a sigla (por exemplo "SNES"), nas cores do console, e nenhum arquivo de logotipo de fabricante é lido
