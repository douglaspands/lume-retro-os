# Spec Delta

## MODIFIED Requirements

### Requirement: Estrutura de pastas da partição de jogos
A partição `ROMS` MUST ter a pasta `roms/` com uma subpasta por sistema (`nes`, `snes`, `mastersystem`, `megadrive`, `segacd`, `sega32x`, `gb`, `gbc`, `gba`, `arcade`, `cps1`, `cps2`, `neogeo`, `psx`) e as pastas `bios/`, `saves/`, `states/`, `screenshots/` e `system/`. Pastas faltando MUST ser recriadas no boot sem apagar nada.

#### Scenario: Pasta apagada pelo usuário
- **WHEN** o usuário apaga `roms/gba/` pelo PC e liga o console
- **THEN** `roms/gba/` volta a existir vazia, e as demais pastas mantêm seu conteúdo

#### Scenario: Cartão antigo ganha as pastas novas
- **WHEN** um cartão gravado antes desta versão, com jogos em `roms/megadrive/` e `roms/arcade/`, inicia com a versão nova
- **THEN** `roms/neogeo/`, `roms/cps1/`, `roms/cps2/`, `roms/segacd/` e `roms/sega32x/` passam a existir vazias e os jogos das pastas antigas continuam lá

### Requirement: Arquivo de leitura para o usuário
A partição `ROMS` MUST trazer um `LEIA-ME.txt` que explica, por sistema, a pasta, as extensões aceitas e quais BIOS são necessárias e onde colocá-las. Para cada pasta de arcade, o `LEIA-ME.txt` MUST dizer qual romset o core padrão aceita.

#### Scenario: Orientação de BIOS do PS1
- **WHEN** o usuário abre o `LEIA-ME.txt` no PC
- **THEN** encontra que o PS1 precisa de BIOS em `bios/` e os nomes de arquivo aceitos

#### Scenario: Romset de cada pasta de arcade
- **WHEN** o usuário procura no `LEIA-ME.txt` como montar a pasta `roms/cps2/`
- **THEN** encontra o romset do core padrão dessa pasta (FB Alpha 2012) e que o alternativo (`fbneo`) usa outro romset

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
