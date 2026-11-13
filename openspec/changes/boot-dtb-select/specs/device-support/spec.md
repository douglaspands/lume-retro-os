# Spec Delta

## MODIFIED Requirements

### Requirement: Consoles e variantes suportados
Esta versão MUST suportar o GA36-MB V1.2 (Allwinner A33) com as duas variantes de painel JD9366 (1 e 2) e o R36S "V5" (Rockchip RK3326) com o painel da família Sitronix ST7703 desta revisão. Outras revisões do R36S e clones RK3326 sem eMMC, com DTB do dArkOS, do dArkOSRE, do arkos4clone ou o de fábrica, MUST ser anunciados como "compatíveis por conversão, sem garantia" (ver `vendor-dtb-compat`); outros consoles MUST NOT ser anunciados como suportados (pendência P-16).

#### Scenario: Clone com DTB do (d)ArkOS
- **WHEN** a documentação de aparelhos do projeto é lida
- **THEN** o GA36-MB V1.2 e o R36S V5 aparecem como suportados, e os clones RK3326 sem eMMC com DTB do dArkOS, do dArkOSRE, do arkos4clone ou o de fábrica como compatíveis por conversão, sem garantia

#### Scenario: Variantes na imagem
- **WHEN** a imagem `console` é inspecionada
- **THEN** a imagem de boot do painel 1 do GA36 está no setor 172032 (a variante padrão), as imagens de boot dos dois painéis do GA36 estão arquivadas com o build (`out/images/console/<build>/`), os DTBs dos dois painéis do GA36 estão em `BOOT/dtbs/a33/` (o do painel 1 como padrão) e o DTB do R36S V5 está em `BOOT/dtbs/rk3326/` como padrão

### Requirement: Troca de variante pelo PC
A variante de painel do GA36 MUST poder ser trocada num PC, sem recompilar a imagem e sem gravar setores: escrever o nome do DTB do painel em `BOOT/dtbs/force` faz o GA36 subir com esse DTB (ver `dtb-selection`). Enquanto a troca de DTB no boot não estiver provada no GA36, gravar no setor 172032 a imagem de boot do painel desejado, arquivada com o build, MUST continuar trocando o painel.

#### Scenario: Trocar o painel do GA36 pelo force
- **WHEN** o usuário escreve o nome do DTB do painel 2 em `BOOT/dtbs/force` pelo PC e liga o GA36
- **THEN** o kernel sobe com o DTB do painel 2

#### Scenario: Trocar o painel do GA36
- **WHEN** o usuário grava `ga36-android-boot-panel2.img` (da pasta do build em `out/images/console/<build>/`) no setor 172032 pelo PC e liga o GA36
- **THEN** o kernel sobe com o DTB do painel 2
