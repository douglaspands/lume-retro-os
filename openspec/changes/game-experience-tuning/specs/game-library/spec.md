# Spec Delta

## MODIFIED Requirements

### Requirement: Estrutura de pastas da partição de jogos
A partição `ROMS` MUST ter a pasta `roms/` com uma subpasta por sistema (`nes`, `snes`, `mastersystem`, `megadrive`, `segacd`, `sega32x`, `gb`, `gbc`, `gba`, `pcengine`, `pcenginecd`, `arcade`, `cps1`, `cps2`, `cps3`, `neogeo`, `psx`, `love`, `ports`) e as pastas `bios/`, `saves/`, `states/`, `screenshots/` e `system/`. Pastas faltando MUST ser recriadas no boot sem apagar nada.

#### Scenario: Pasta apagada pelo usuário
- **WHEN** o usuário apaga `roms/gba/` pelo PC e liga o console
- **THEN** `roms/gba/` volta a existir vazia, e as demais pastas mantêm seu conteúdo

#### Scenario: Cartão antigo ganha as pastas novas
- **WHEN** um cartão gravado antes desta versão, com jogos em `roms/megadrive/` e `roms/arcade/`, inicia com a versão nova
- **THEN** `roms/neogeo/`, `roms/cps1/`, `roms/cps2/`, `roms/cps3/`, `roms/segacd/`, `roms/sega32x/`, `roms/pcengine/`, `roms/pcenginecd/`, `roms/love/` e `roms/ports/` passam a existir vazias e os jogos das pastas antigas continuam lá

### Requirement: Sistemas e cores incluídos
A distro MUST incluir pelo menos um core funcional para cada sistema: NES, SNES, Master System, Mega Drive, Sega CD, 32X, Game Boy, Game Boy Color, Game Boy Advance, TurboGrafx-16 (PC Engine), TurboGrafx-CD (PC Engine CD), arcade (anos 80 e 90), CPS-1, CPS-2, CPS-3, Neo Geo e PlayStation. Os mesmos cores MUST estar presentes nos três alvos.

#### Scenario: Core para cada sistema
- **WHEN** o conjunto de cores instalados de qualquer imagem é listado
- **THEN** cada sistema do catálogo tem seu core padrão instalado, e a lista é igual nos três alvos

#### Scenario: Alternativo das pastas CPS e Neo Geo
- **WHEN** o usuário troca, no menu do RetroArch, o core de um jogo de `roms/cps1/`, `roms/cps2/` ou `roms/neogeo/`
- **THEN** o `fbneo` está instalado e pode ser escolhido

#### Scenario: TurboGrafx-16 e TurboGrafx-CD
- **WHEN** o usuário põe um HuCard em `roms/pcengine/` e um jogo de CD (`cue` ou `chd`) em `roms/pcenginecd/`, com a BIOS do CD em `bios/`
- **THEN** os dois aparecem no launcher e abrem no `mednafen_pce_fast`

#### Scenario: CD sem a BIOS
- **WHEN** o usuário abre um jogo de `roms/pcenginecd/` sem a BIOS do CD em `bios/`
- **THEN** o jogo não abre, e o `LEIA-ME.txt` diz o nome do arquivo de BIOS esperado e onde colocá-lo

#### Scenario: CPS-3 no FBNeo
- **WHEN** o usuário põe um romset de CPS-3 da versão do FBNeo da imagem em `roms/cps3/`
- **THEN** o jogo aparece no launcher e abre no `fbneo`, e o `LEIA-ME.txt` diz que essa pasta usa o romset do FBNeo
