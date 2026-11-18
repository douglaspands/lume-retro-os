# Spec Delta

## MODIFIED Requirements

### Requirement: Importação das coleções no PC
O projeto MUST converter os DTBs das coleções (dArkOSRE, arkos4clone, EE-Clones-DTB e o de fábrica de um aparelho) com `lume dtb-import`, que escreve um DTS por placa distinta em `board/r36s/dts-vendor/` e um `SOURCES.tsv` com cada arquivo lido, o resultado (`converted`, `refused` ou `same`) e o motivo. Os DTBs do U-Boot que acompanham esses projetos (`rg351*-uboot.dtb`) MUST ser ignorados. Arquivos iguais, ou que convertem para a mesma árvore, MUST virar uma placa só.

#### Scenario: Coleções importadas
- **WHEN** `lume dtb-import` roda sobre as três coleções
- **THEN** cada DTB de placa aparece no `SOURCES.tsv`, e cada placa convertida tem o seu DTS com o `lume,id` igual ao nome do arquivo

#### Scenario: DTB de fábrica do próprio clone
- **WHEN** o DTB do cartão de fábrica de um clone RK3326 é importado
- **THEN** ele vira um DTS como os do (d)ArkOS, ou é recusado com o motivo
