# game-library Specification

## Purpose

Define o contrato estável entre o usuário, a distro e qualquer frontend: onde ficam jogos, BIOS, saves e estados, quais sistemas e cores existem e como a lista de jogos é montada.

## Requirements

### Requirement: Estrutura de pastas da partição de jogos
A partição `ROMS` MUST ter a pasta `roms/` com uma subpasta por sistema (`nes`, `snes`, `mastersystem`, `megadrive`, `segacd`, `sega32x`, `gb`, `gbc`, `gba`, `arcade`, `cps1`, `cps2`, `neogeo`, `psx`, `love`, `ports`) e as pastas `bios/`, `saves/`, `states/`, `screenshots/` e `system/`. Pastas faltando MUST ser recriadas no boot sem apagar nada.

#### Scenario: Pasta apagada pelo usuário
- **WHEN** o usuário apaga `roms/gba/` pelo PC e liga o console
- **THEN** `roms/gba/` volta a existir vazia, e as demais pastas mantêm seu conteúdo

#### Scenario: Cartão antigo ganha as pastas novas
- **WHEN** um cartão gravado antes desta versão, com jogos em `roms/megadrive/` e `roms/arcade/`, inicia com a versão nova
- **THEN** `roms/neogeo/`, `roms/cps1/`, `roms/cps2/`, `roms/segacd/`, `roms/sega32x/`, `roms/love/` e `roms/ports/` passam a existir vazias e os jogos das pastas antigas continuam lá

### Requirement: Arquivo de leitura para o usuário
A partição `ROMS` MUST trazer um `LEIA-ME.txt` que explica, por sistema, a pasta, as extensões aceitas e quais BIOS são necessárias e onde colocá-las. Para cada pasta de arcade, o `LEIA-ME.txt` MUST dizer qual romset o core padrão aceita.

#### Scenario: Orientação de BIOS do PS1
- **WHEN** o usuário abre o `LEIA-ME.txt` no PC
- **THEN** encontra que o PS1 precisa de BIOS em `bios/` e os nomes de arquivo aceitos

#### Scenario: Romset de cada pasta de arcade
- **WHEN** o usuário procura no `LEIA-ME.txt` como montar a pasta `roms/cps2/`
- **THEN** encontra o romset do core padrão dessa pasta (FB Alpha 2012) e que o alternativo (`fbneo`) usa outro romset

### Requirement: Catálogo de sistemas declarativo
A distro MUST manter um catálogo de sistemas em formato de dados, com nome de exibição, pasta, extensões aceitas, core padrão, cores alternativos e a lista ordenada de emuladores (runner e core) de cada sistema, cujo primeiro item é o padrão. Ele MUST ser a única fonte para gerar as listas de jogos e MUST ser legível por qualquer frontend futuro.

#### Scenario: Extensão fora do catálogo
- **WHEN** um arquivo com extensão não listada para o sistema está em `roms/snes/`
- **THEN** ele não aparece na lista de jogos do SNES

#### Scenario: Emulador citado sem runner
- **WHEN** o catálogo da imagem cita um runner que não está instalado
- **THEN** a validação do catálogo falha e o build não gera a imagem

### Requirement: Sistemas e cores incluídos
A distro MUST incluir pelo menos um core funcional para cada sistema: NES, SNES, Master System, Mega Drive, Sega CD, 32X, Game Boy, Game Boy Color, Game Boy Advance, arcade (anos 80 e 90), CPS-1, CPS-2, Neo Geo e PlayStation. Os mesmos cores MUST estar presentes nos três alvos.

#### Scenario: Core para cada sistema
- **WHEN** o conjunto de cores instalados de qualquer imagem é listado
- **THEN** cada sistema do catálogo tem seu core padrão instalado, e a lista é igual nos três alvos

#### Scenario: Alternativo das pastas CPS e Neo Geo
- **WHEN** o usuário troca, no menu do RetroArch, o core de um jogo de `roms/cps1/`, `roms/cps2/` ou `roms/neogeo/`
- **THEN** o `fbneo` está instalado e pode ser escolhido

### Requirement: Core padrão por arquitetura
O catálogo MUST permitir que um sistema troque o core padrão em uma arquitetura específica, para usar um core mais leve no GA36. O core trocado MUST estar instalado em todos os alvos, para a VM poder testá-lo. Um sistema de arcade (arcade, CPS-1, CPS-2, Neo Geo) MUST usar o mesmo core padrão em todas as arquiteturas, porque o cartão único leva a mesma pasta de romsets aos dois consoles e um romset de arcade só funciona no core da versão dele.

#### Scenario: Core mais leve no GA36
- **WHEN** o catálogo define um core padrão diferente para armv7 no Game Boy Advance
- **THEN** no GA36 os jogos de GBA abrem com esse core, e na VM ele também está instalado e pode ser testado

#### Scenario: Pasta de arcade no cartão único
- **WHEN** um jogo de `roms/cps2/` abre no GA36 e o cartão vai para o R36S
- **THEN** o R36S abre o mesmo jogo com o mesmo core padrão do GA36

#### Scenario: Catálogo com core de arcade por arquitetura
- **WHEN** o catálogo define um core padrão diferente para armv7 num sistema de arcade
- **THEN** a validação do catálogo falha e o build não gera a imagem

### Requirement: Listas de jogos geradas automaticamente
A cada boot, quando o cabo USB é desligado e quando o frontend pedir, a distro MUST atualizar a lista de jogos de cada sistema a partir de `roms/` e do catálogo, no formato `gamelist.xml` do EmulationStation em `roms/<id>/gamelist.xml`. Sistemas sem jogos MUST NOT aparecer.

#### Scenario: Novo jogo copiado pelo PC
- **WHEN** o usuário copia um jogo de NES para `roms/nes/` e liga o console
- **THEN** o jogo aparece na lista do NES com o nome do arquivo, sem extensão, e ganha uma entrada no `roms/nes/gamelist.xml`

#### Scenario: Sistema vazio
- **WHEN** `roms/psx/` não tem nenhum arquivo aceito
- **THEN** o PlayStation não aparece no frontend

#### Scenario: Atualização pedida pelo usuário
- **WHEN** o usuário copia jogos por MTP com o console ligado e escolhe "Atualizar listas de jogos"
- **THEN** os jogos novos aparecem sem reiniciar o console

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

### Requirement: Diff incremental com o gamelist existente
Quando `roms/<id>/gamelist.xml` já existe, a atualização MUST só acrescentar os jogos novos e MUST manter, sem mudar, os metadados das entradas existentes (nome, capa, descrição, favorito e os demais campos), inclusive os gerados por scrapers do EmulationStation.

#### Scenario: Gamelist de um scraper
- **WHEN** o cartão traz um `gamelist.xml` com nome e capa de 300 jogos e o usuário copia mais 2 jogos
- **THEN** depois da atualização os 300 mantêm nome e capa e os 2 novos entram com o nome do arquivo

### Requirement: Jogo removido sai da lista e mantém os metadados
Um jogo cuja ROM não existe mais MUST sumir da lista mostrada pelo frontend, mas a entrada dele MUST continuar no `gamelist.xml` com todos os metadados, e as imagens dele MUST NOT ser apagadas. Se a ROM voltar, o jogo MUST reaparecer com os mesmos metadados.

#### Scenario: ROM apagada e devolvida
- **WHEN** o usuário apaga uma ROM com capa, atualiza as listas, copia a mesma ROM de volta e atualiza de novo
- **THEN** o jogo some da lista na primeira atualização e volta com a mesma capa na segunda

### Requirement: Gamelist gravado só quando muda e de forma atômica
A atualização MUST NOT reescrever um `gamelist.xml` que não mudou. Quando muda, MUST gravá-lo de forma que um corte de energia deixe o arquivo antigo ou o novo inteiro, nunca um arquivo parcial.

#### Scenario: Nada mudou
- **WHEN** o console liga sem nenhuma mudança em `roms/snes/`
- **THEN** o `roms/snes/gamelist.xml` não é gravado

#### Scenario: Corte de energia durante a gravação
- **WHEN** a energia cai enquanto o `gamelist.xml` é gravado
- **THEN** no boot seguinte o arquivo é o anterior ou o novo, e o XML é válido
