# Spec Delta

## Purpose

Define como um DTB do kernel da Rockchip para o RK3326 (do dArkOS, do dArkOSRE, do
arkos4clone ou o de fábrica do próprio aparelho) é aceito no cartão, validado, convertido
para o kernel mainline e reconhecido pelo hardware quando há uma assinatura medida, para que
o R36S e os seus clones usem o DTB que já existe para eles.

## ADDED Requirements

### Requirement: DTB do kernel da Rockchip aceito na pasta do SoC
Um DTB do kernel da Rockchip do dArkOS, do dArkOSRE, do arkos4clone ou o de fábrica do aparelho, copiado para `BOOT/dtbs/rk3326/`, solto ou numa subpasta, MUST ser reconhecido no boot e entrar como candidato depois de convertido. Os DTBs do U-Boot que acompanham esses projetos (`rg351*-uboot.dtb`) MUST ser ignorados sem aviso.

#### Scenario: DTB de fábrica do próprio clone
- **WHEN** o DTB do cartão de fábrica de um clone RK3326 (por exemplo `rf3536k3ka.dtb` ou `rk3326-evb-lp3-v12-linux.dtb`) é copiado para `BOOT/dtbs/rk3326/`
- **THEN** ele é convertido e aparece na lista, como os DTBs do (d)ArkOS

#### Scenario: Pasta do dArkOSRE copiada inteira
- **WHEN** as subpastas de placas do dArkOSRE, cada uma com o seu `rk3326-r36s-linux.dtb`, são copiadas para `BOOT/dtbs/rk3326/` pelo PC
- **THEN** o próximo boot do R36S lista um candidato por placa, com o nome da subpasta, sem recompilar a imagem

#### Scenario: DTB solto
- **WHEN** um DTB do (d)ArkOS é copiado solto para `BOOT/dtbs/rk3326/`
- **THEN** ele vira um candidato com o nome tirado do `model` dele

### Requirement: Validação antes da conversão
O boot MUST converter só um DTB do kernel 4.4 cujo `compatible` seja do SoC em execução e que tenha os nós de painel, controle e PMIC que o conversor conhece. Um DTB que falhe nisso, ou que tenha uma propriedade necessária que o conversor não sabe traduzir, MUST NOT ser candidato, e o log MUST dizer o arquivo e o motivo.

#### Scenario: DTB de outro SoC
- **WHEN** um DTB do kernel 4.4 de outro SoC está na pasta `dtbs/rk3326/`
- **THEN** ele é ignorado e o log registra que o SoC não confere

#### Scenario: Nó desconhecido
- **WHEN** um DTB do (d)ArkOS descreve o painel com um nó que o conversor não conhece
- **THEN** ele não é candidato e o log registra o arquivo e o nó que faltou

### Requirement: Conversão do hardware essencial
O DTB convertido MUST descrever para o kernel mainline, a partir dos dados do DTB de origem, a tela (sequências de inicialização e de desligamento, timings, atrasos e pinos do painel), a luz de fundo, os botões e os analógicos, o som (amplificador e detecção do fone), a bateria (capacidade e tabela de tensão) e os LEDs. O DTB de origem MUST NOT ser alterado.

#### Scenario: DTB de fábrica do R36S convertido
- **WHEN** o DTB de fábrica do R36S V5 (ArkOS) é convertido
- **THEN** o resultado passa na validação de bindings do kernel mainline e descreve o mesmo painel, os mesmos pinos dos botões, os mesmos canais dos analógicos e o mesmo amplificador que o DTB nativo do R36S V5

#### Scenario: Coleções conhecidas
- **WHEN** cada DTB de placa do dArkOSRE, do arkos4clone e os de fábrica do repositório EE-Clones-DTB é convertido
- **THEN** cada um vira um DTB que passa na validação de bindings do kernel mainline, ou é recusado com o motivo no log

#### Scenario: Funcionamento no aparelho
- **WHEN** o R36S V5 sobe com o seu DTB de fábrica convertido
- **THEN** a tela, a luz de fundo, os botões, os analógicos, o som, a bateria e os LEDs funcionam como com o DTB nativo

### Requirement: Volume seguro do alto-falante
O DTB convertido MUST usar no amplificador do alto-falante o ganho seguro do DTB nativo do SoC, e MUST NOT copiar o ganho do DTB de origem; quando o de origem pede outro valor, o log MUST registrar isso.

#### Scenario: DTB que pede ganho alto
- **WHEN** um DTB de origem traz um ganho de alto-falante maior que o do DTB nativo
- **THEN** o convertido usa o ganho do nativo, e o log registra o valor ignorado

### Requirement: Aparelhos fora do alcance documentados
A documentação do projeto MUST listar os aparelhos da família R36S que a conversão não cobre e o motivo: os com eMMC, que iniciam pelo eMMC antes do cartão; as placas A33/A23 sem DTB de fábrica; os de outro SoC (RK3128, MediaTek MT6572, HCSEMI E3100).

#### Scenario: Usuário com um clone de outro SoC
- **WHEN** o usuário consulta a documentação com um GB350, R36SX ou R36HD
- **THEN** ele encontra que o aparelho não é compatível e por quê

### Requirement: DTB convertido sempre confirmado
Um DTB convertido MUST ser tratado como novo no aparelho até ser confirmado: passa pela confirmação na tela, pela volta automática e pelo descarte por aparelho, como qualquer DTB novo (ver `dtb-selection`).

#### Scenario: Painel errado
- **WHEN** o usuário escolhe na lista o DTB convertido de uma placa diferente da sua e a tela fica preta
- **THEN** sem resposta em 15 s o kernel volta ao DTB anterior e o convertido fica descartado naquele aparelho

### Requirement: Detecção pela assinatura medida
Um DTB convertido cuja placa tem uma assinatura medida na tabela do projeto (leituras do hardware que a distinguem, como o ID do painel lido pelo DSI, níveis de pinos e faixas do ADC) MUST entrar na escolha automática com essas leituras como regras. Um DTB convertido sem assinatura MUST NOT ser escolhido pelo automático: ele só entra pela lista ou pelo `force`.

#### Scenario: Placa com assinatura
- **WHEN** o DTB de uma placa com assinatura na tabela está na pasta e as leituras do aparelho batem com ela
- **THEN** o automático escolhe esse DTB convertido e o log registra a assinatura que bateu

#### Scenario: Placa sem assinatura
- **WHEN** só DTBs de placas sem assinatura estão na pasta, além do padrão
- **THEN** o console sobe com o padrão, e os convertidos aparecem na lista para a escolha manual

### Requirement: Registro da conversão
O log de boot MUST registrar, em inglês, cada DTB do kernel da Rockchip encontrado, se foi convertido ou recusado e por quê, e o nome com que entrou na lista.

#### Scenario: Log de um boot com a coleção
- **WHEN** o boot encontra DTBs do kernel da Rockchip na pasta
- **THEN** o log tem uma linha por DTB com o caminho, o resultado (`converted` ou `refused`) e o motivo ou o nome do candidato
