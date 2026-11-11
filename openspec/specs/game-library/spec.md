# game-library Specification

## Purpose

Define o contrato estável entre o usuário, a distro e qualquer frontend: onde ficam jogos, BIOS, saves e estados, quais sistemas e cores existem e como a lista de jogos é montada.

## Requirements

### Requirement: Estrutura de pastas da partição de jogos
A partição `ROMS` MUST ter a pasta `roms/` com uma subpasta por sistema (`nes`, `snes`, `mastersystem`, `megadrive`, `gb`, `gbc`, `gba`, `arcade`, `psx`) e as pastas `bios/`, `saves/`, `states/`, `screenshots/` e `system/`. Pastas faltando MUST ser recriadas no boot sem apagar nada.

#### Scenario: Pasta apagada pelo usuário
- **WHEN** o usuário apaga `roms/gba/` pelo PC e liga o console
- **THEN** `roms/gba/` volta a existir vazia, e as demais pastas mantêm seu conteúdo

### Requirement: Arquivo de leitura para o usuário
A partição `ROMS` MUST trazer um `LEIA-ME.txt` que explica, por sistema, a pasta, as extensões aceitas e quais BIOS são necessárias e onde colocá-las.

#### Scenario: Orientação de BIOS do PS1
- **WHEN** o usuário abre o `LEIA-ME.txt` no PC
- **THEN** encontra que o PS1 precisa de BIOS em `bios/` e os nomes de arquivo aceitos

### Requirement: Catálogo de sistemas declarativo
A distro MUST manter um catálogo de sistemas em formato de dados, com nome de exibição, pasta, extensões aceitas, core padrão e cores alternativos de cada sistema. Ele MUST ser a única fonte para gerar as listas de jogos e MUST ser legível por qualquer frontend futuro.

#### Scenario: Extensão fora do catálogo
- **WHEN** um arquivo com extensão não listada para o sistema está em `roms/snes/`
- **THEN** ele não aparece na lista de jogos do SNES

### Requirement: Sistemas e cores incluídos
A distro MUST incluir pelo menos um core funcional para cada sistema: NES, SNES, Master System, Mega Drive, Game Boy, Game Boy Color, Game Boy Advance, arcade (anos 80 e 90) e PlayStation. Os mesmos cores MUST estar presentes nos três alvos.

#### Scenario: Core para cada sistema
- **WHEN** o conjunto de cores instalados de qualquer imagem é listado
- **THEN** cada sistema do catálogo tem seu core padrão instalado, e a lista é igual nos três alvos

### Requirement: Core padrão por arquitetura
O catálogo MUST permitir que um sistema troque o core padrão em uma arquitetura específica, para usar um core mais leve no GA36. O core trocado MUST estar instalado em todos os alvos, para a VM poder testá-lo.

#### Scenario: Core mais leve no GA36
- **WHEN** o catálogo define um core padrão diferente para armv7 no Game Boy Advance
- **THEN** no GA36 os jogos de GBA abrem com esse core, e na VM ele também está instalado e pode ser testado

### Requirement: Listas de jogos geradas automaticamente
A cada boot, e quando o frontend pedir, a distro MUST gerar uma lista de jogos por sistema a partir de `roms/` e do catálogo. Sistemas sem jogos MUST NOT aparecer.

#### Scenario: Novo jogo copiado pelo PC
- **WHEN** o usuário copia um jogo de NES para `roms/nes/` e liga o console
- **THEN** o jogo aparece na lista do NES com o nome do arquivo, sem extensão

#### Scenario: Sistema vazio
- **WHEN** `roms/psx/` não tem nenhum arquivo aceito
- **THEN** o PlayStation não aparece no frontend

### Requirement: Saves e estados fora da configuração do frontend
Saves internos dos jogos MUST ficar em `saves/` e save states em `states/` da partição `ROMS`, em pastas por sistema. Isso garante que trocar ou restaurar o frontend não apague jogo salvo.

#### Scenario: Restaurar fábrica preserva saves
- **WHEN** o usuário apaga `system/` para restaurar a fábrica
- **THEN** os arquivos de `saves/` e `states/` continuam lá e são carregados ao abrir os jogos

### Requirement: Saves gravados com segurança
Depois de gravar um save interno ou um save state, o sistema MUST garantir que os dados foram escritos no cartão antes de seguir.

#### Scenario: Desligamento logo após salvar
- **WHEN** o usuário cria um save state e, 5 segundos depois, a energia é cortada
- **THEN** no boot seguinte o save state existe e carrega normalmente
