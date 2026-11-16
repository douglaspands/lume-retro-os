# vendor-dtb-compat Specification

## Purpose
Define como um DTB do kernel da Rockchip para o RK3326 (do dArkOS, do dArkOSRE, do
arkos4clone ou o de fábrica do próprio aparelho) é convertido no PC para o kernel mainline,
validado no build, levado ao cartão e escolhido no aparelho, para que o R36S e os seus
clones usem o DTB que já existe para eles.

## Requirements

### Requirement: Importação das coleções no PC
O projeto MUST converter os DTBs das coleções (dArkOSRE, arkos4clone, EE-Clones-DTB e o de fábrica de um aparelho) com `r36os dtb-import`, que escreve um DTS por placa distinta em `board/r36s/dts-vendor/` e um `SOURCES.tsv` com cada arquivo lido, o resultado (`converted`, `refused` ou `same`) e o motivo. Os DTBs do U-Boot que acompanham esses projetos (`rg351*-uboot.dtb`) MUST ser ignorados. Arquivos iguais, ou que convertem para a mesma árvore, MUST virar uma placa só.

#### Scenario: Coleções importadas
- **WHEN** `r36os dtb-import` roda sobre as três coleções
- **THEN** cada DTB de placa aparece no `SOURCES.tsv`, e cada placa convertida tem o seu DTS com o `lume,id` igual ao nome do arquivo

#### Scenario: DTB de fábrica do próprio clone
- **WHEN** o DTB do cartão de fábrica de um clone RK3326 é importado
- **THEN** ele vira um DTS como os do (d)ArkOS, ou é recusado com o motivo

### Requirement: Validação antes da conversão
O importador MUST converter só um DTB cujo `compatible` seja do RK3326 e que tenha os nós de painel, controle e PMIC que ele conhece. Um DTB que falhe nisso, ou que tenha uma propriedade necessária que o importador não sabe traduzir, MUST ser recusado com o motivo no `SOURCES.tsv`.

#### Scenario: DTB de outro SoC
- **WHEN** um DTB de outro SoC está numa coleção
- **THEN** ele é recusado com o motivo "not an RK3326 tree"

#### Scenario: Nó desconhecido
- **WHEN** um DTB descreve o controle com um nó que o importador não conhece
- **THEN** ele é recusado e o motivo diz o nó

### Requirement: Conversão do hardware essencial
O DTS convertido MUST descrever para o kernel mainline, a partir dos dados do DTB de origem, a tela (sequência de inicialização, timings, atrasos e pinos do painel), a luz de fundo, os botões e os analógicos, o som (amplificador e detecção do fone), a bateria (capacidade e tabela de tensão), os LEDs e a alimentação (reguladores do PMIC e domínios de I/O, ver "Alimentação da origem"), sobre o DTB nativo do R36S V5. O DTB de origem MUST NOT ser alterado.

#### Scenario: DTB de fábrica do R36S convertido
- **WHEN** o DTB de fábrica do R36S V5 é convertido
- **THEN** o resultado descreve os mesmos pinos e códigos dos botões, o mesmo mux dos analógicos, o mesmo amplificador, a mesma detecção do fone, a mesma luz de fundo, bateria e LEDs que o DTB nativo do R36S V5

#### Scenario: Validação no build
- **WHEN** o build do console compila os DTS de `board/r36s/dts-vendor/`
- **THEN** cada um compila sem aviso do `dtc` e passa no `dt-validate` do kernel mainline, ou o build falha

#### Scenario: Funcionamento no aparelho
- **WHEN** o R36S V5 sobe com o seu DTB de fábrica convertido
- **THEN** a tela, a luz de fundo, os botões, os analógicos, o som, a bateria e os LEDs funcionam como com o DTB nativo

### Requirement: Alimentação da origem
O DTS convertido MUST levar, para cada regulador do PMIC que o DTB de origem declara, a faixa de tensão e o estado sempre ligado da origem, e MUST refazer o mapa dos domínios de I/O do SoC (`vccio*`, `pmuio*`) apontando os mesmos reguladores que a origem aponta. Um regulador que a origem não declara MUST ficar sem tensão definida no DTS convertido.

#### Scenario: Placa com outra alimentação
- **WHEN** o DTB de origem declara o DCDC4 a 3,0 V e os domínios `vccio3` e `vccio6` no regulador de 1,8 V
- **THEN** o DTS convertido programa o DCDC4 a 3,0 V e liga `vccio3` e `vccio6` ao regulador de 1,8 V, como a origem

#### Scenario: DTB de fábrica do R36S V5
- **WHEN** o DTB de fábrica do R36S V5 é convertido
- **THEN** os reguladores e os domínios de I/O do resultado são iguais aos do DTB nativo

#### Scenario: Regulador ausente na origem
- **WHEN** o DTB de origem não declara um regulador que o DTB nativo declara
- **THEN** o DTS convertido não define tensão para ele

### Requirement: Recusa por alimentação desconhecida
O importador MUST recusar, com o motivo no `SOURCES.tsv`, um DTB de origem sem os reguladores do PMIC, com um domínio de I/O alimentado por um regulador fora do PMIC ou com um domínio de I/O acima de 3,6 V.

#### Scenario: Domínio fora do PMIC
- **WHEN** um domínio de I/O do DTB de origem é alimentado por um regulador fora do PMIC
- **THEN** o DTB é recusado e o motivo diz o domínio

### Requirement: Volume seguro do alto-falante
O DTS convertido MUST NOT copiar o ganho do alto-falante do DTB de origem (`spk-volume`): vale o volume seguro do DTB nativo e do codec. Quando o de origem pede um valor, o DTS e o `SOURCES.tsv` MUST registrar o valor ignorado.

#### Scenario: DTB que pede ganho alto
- **WHEN** um DTB de origem traz um `spk-volume`
- **THEN** o DTS convertido não o tem, e a nota registra o valor ignorado

### Requirement: Carga sob demanda no boot
Os DTBs convertidos MUST ir para `BOOT/dtbs/rk3326/vendor/<lume,id>.dtb` e MUST NOT ser lidos num boot normal. O `lume-bootsel` MUST carregar um deles só quando o `force`, a lista, a escolha salva, o aprendido ou o estado o nomeiam, e a lista MUST mostrar todos pelo nome, com rolagem.

#### Scenario: Boot normal
- **WHEN** o R36S liga sem `force`, sem a tecla da lista e sem escolha salva de um convertido
- **THEN** nenhum arquivo de `vendor/` é aberto, e o log não cita nenhum

#### Scenario: Escolha na lista
- **WHEN** o usuário abre a lista, rola até um DTB convertido e confirma
- **THEN** ele é carregado, sobe como `manual` e passa pela confirmação na tela

#### Scenario: Força pelo PC
- **WHEN** `BOOT/dtbs/force` tem o nome de um DTB convertido
- **THEN** ele é carregado de `vendor/` e escolhido com o motivo `forced`

### Requirement: Aparelhos fora do alcance documentados
A documentação do projeto MUST listar os aparelhos da família R36S que a conversão não cobre e o motivo: os com eMMC, que iniciam pelo eMMC antes do cartão; as placas A33/A23 sem DTB de fábrica; os de outro SoC (RK3128, MediaTek MT6572, HCSEMI E3100); e as famílias de DTB recusadas pelo importador.

#### Scenario: Usuário com um clone de outro SoC
- **WHEN** o usuário consulta a documentação com um GB350, R36SX ou R36HD
- **THEN** ele encontra que o aparelho não é compatível e por quê

### Requirement: DTB convertido sempre confirmado
Um DTB convertido MUST ser tratado como novo no aparelho até ser confirmado: passa pela confirmação na tela, pela volta automática e pelo descarte por aparelho, como qualquer DTB novo (ver `dtb-selection`). Confirmado na tela, ele MUST ser aprendido para o ID do painel como qualquer escolha da lista.

#### Scenario: Painel errado
- **WHEN** o usuário escolhe na lista o DTB convertido de uma placa diferente da sua e a tela fica preta
- **THEN** sem resposta em 15 s o kernel volta ao DTB anterior e o convertido fica descartado naquele aparelho

### Requirement: Registro da escolha de um convertido
O log de boot MUST registrar, em inglês, quando um DTB de `vendor/` é carregado e por qual nome, e quantos convertidos a lista mostrou.

#### Scenario: Log de um boot com o force num convertido
- **WHEN** o `force` nomeia um DTB convertido
- **THEN** o log tem `vendor device tree <id> loaded on demand` e a linha do candidato com o caminho `vendor/<id>.dtb`
