# Spec Delta

## Purpose

Define como o boot escolhe a descrição do hardware (DTB) do aparelho em que o cartão está:
automaticamente pela leitura do hardware, manualmente pela tecla ou pelo PC, com o DTB de
hoje como padrão, a confirmação na tela de cada DTB novo e a volta ao último que funcionou,
com a escolha guardada por aparelho.

## ADDED Requirements

### Requirement: Pasta de DTBs por SoC
A `BOOT` MUST ter uma pasta de DTBs por SoC (`dtbs/a33/` e `dtbs/rk3326/`). Cada DTB da pasta MUST declarar, num nó do Lume, o seu nome, a sua prioridade e as regras de reconhecimento, e exatamente um DTB por SoC MUST ser o padrão. Um DTB cujo `compatible` de SoC difere do console em execução MUST NOT ser candidato.

#### Scenario: DTB novo na pasta
- **WHEN** um DTB com o nó do Lume é copiado pelo PC para `BOOT/dtbs/rk3326/`
- **THEN** o próximo boot do R36S lista esse DTB entre os candidatos, sem recompilar a imagem

#### Scenario: DTB de outro SoC
- **WHEN** a pasta `dtbs/rk3326/` contém um DTB cujo `compatible` é de outro SoC
- **THEN** o boot não o oferece nem o escolhe e registra no log que ele foi ignorado

### Requirement: DTB padrão
Sem escolha forçada, sem escolha manual gravada e sem nenhuma regra que bata, o console MUST subir com o DTB padrão do seu SoC, sem reiniciar o kernel, e o boot MUST ser igual ao de antes desta change.

#### Scenario: Aparelho original
- **WHEN** o R36S V5 ou o GA36 com painel 1 é ligado com um cartão novo, sem `dtbs/force` e sem escolha gravada
- **THEN** o kernel sobe uma só vez, com o DTB padrão, e o log registra que nenhuma regra bateu

### Requirement: Escolha automática pela leitura do hardware
O boot MUST avaliar as regras de cada candidato com leituras só de leitura do hardware (valor de um canal de ADC numa faixa, nível de um GPIO, presença de um endereço num barramento I2C) e escolher o candidato de maior prioridade cujas regras batem todas. Nenhuma leitura MUST escrever em registradores ou em dispositivos.

#### Scenario: Regra que bate
- **WHEN** um candidato exige o canal 1 do ADC entre 800 e 950 e a leitura dá 870
- **THEN** esse candidato é escolhido, se nenhum outro de prioridade maior também bater

#### Scenario: Sonda que falha
- **WHEN** a leitura exigida por uma regra não pode ser feita (barramento ausente, canal inexistente)
- **THEN** a regra conta como não batida, o boot continua com os outros candidatos e o log registra a falha

### Requirement: Escolha manual pela tecla
Segurando a tecla de seleção do console ao ligar, o boot MUST mostrar na tela a lista dos candidatos do SoC, marcando o escolhido pelo automático e o último que funcionou, e deixar navegar e confirmar pelos botões do console. A escolha confirmada MUST ser gravada na `ROMS`, separada por aparelho (ver "Escolha por aparelho"), e valer nos boots seguintes.

#### Scenario: Escolher pela lista
- **WHEN** o usuário liga o GA36 segurando a tecla de seleção e confirma o DTB do painel 2
- **THEN** o kernel sobe com o DTB do painel 2, e o próximo boot sem a tecla também usa o painel 2

#### Scenario: Escolha separada por console
- **WHEN** a escolha manual foi feita no GA36 e o mesmo cartão é ligado no R36S
- **THEN** o R36S usa a sua própria escolha (ou o automático), sem ser afetado pela do GA36

#### Scenario: Voltar ao automático
- **WHEN** o usuário escolhe na lista a opção do automático
- **THEN** a escolha gravada é apagada e o boot volta à escolha automática

### Requirement: Escolha forçada pelo PC
Se `BOOT/dtbs/force` existir e nomear um candidato do SoC em execução, o boot MUST usar esse DTB acima de qualquer outra escolha, passando pela confirmação na tela na primeira vez em cada aparelho. Um nome que não existe, é de outro SoC ou foi descartado naquele aparelho MUST ser ignorado, com o motivo no log, e o boot MUST seguir as outras escolhas.

#### Scenario: Tela preta resolvida pelo PC
- **WHEN** o usuário escreve `ga36-panel2` em `BOOT/dtbs/force` pelo PC e liga o GA36
- **THEN** o kernel sobe com o DTB do painel 2, sem usar a tela nem os botões

#### Scenario: Nome inválido
- **WHEN** `BOOT/dtbs/force` nomeia um DTB que não está em `dtbs/a33/`
- **THEN** o GA36 ignora o arquivo, registra o nome inválido no log e segue a escolha manual gravada, a automática ou o padrão

### Requirement: Confirmação na tela do DTB novo
No primeiro boot com um DTB diferente do padrão e ainda não confirmado no aparelho, o boot MUST mostrar na tela, já com esse DTB em uso, um pedido para apertar a tecla de confirmar em até 15 s. Confirmado, o DTB MUST valer sem nova pergunta naquele aparelho. Sem resposta, o boot MUST descartar esse DTB naquele aparelho e reiniciar o kernel com o último DTB confirmado (ou o padrão). O padrão e os DTBs confirmados MUST NOT perguntar.

#### Scenario: Confirmar o DTB novo
- **WHEN** o GA36 sobe pela primeira vez com o DTB do painel 2, a mensagem aparece e o usuário aperta A
- **THEN** o boot segue com o painel 2, e os boots seguintes com o painel 2 não perguntam mais

#### Scenario: Tela preta volta sozinha
- **WHEN** o DTB novo deixa a tela preta e ninguém aperta nada por 15 s
- **THEN** o kernel reinicia com o último DTB confirmado (ou o padrão), o log registra o motivo `reverted`, e o DTB descartado não é mais escolhido pelo automático naquele aparelho

#### Scenario: Escolha forçada também confirma
- **WHEN** `BOOT/dtbs/force` nomeia um DTB ainda não confirmado no aparelho
- **THEN** o boot sobe com ele e mostra o pedido de confirmação, como para um DTB vindo das regras ou da lista

### Requirement: Confirmação sem tecla
Quando o console não tem dispositivo de entrada com a tecla de confirmar, o boot MUST NOT mostrar o pedido, e o DTB novo MUST ser confirmado quando o boot chega ao frontend.

#### Scenario: Sem tecla de confirmar
- **WHEN** um DTB novo sobe num console sem a tecla de confirmar disponível no início do boot
- **THEN** não há pedido na tela, e o DTB é confirmado quando o frontend sobe

### Requirement: Volta ao último DTB que funcionou
Um DTB diferente do padrão MUST só ser considerado bom depois de confirmado. Se um boot com um DTB não confirmado for interrompido antes da confirmação (travamento reiniciado pelo watchdog do SoC, ou o usuário desligando), o boot seguinte MUST usar o último DTB confirmado do aparelho (ou o padrão) e registrar no log o DTB descartado e o motivo.

#### Scenario: DTB que trava o kernel
- **WHEN** o kernel trava com o DTB novo antes da pergunta na tela
- **THEN** o watchdog reinicia o aparelho, o boot seguinte sobe com o último DTB que funcionou, e o log diz que o anterior foi descartado (`fallback`)

### Requirement: Força de um DTB descartado
Uma escolha forçada pelo PC que nomeia um DTB descartado naquele aparelho MUST ser ignorada, com o motivo no log, até o arquivo ser apagado ou o DTB ser escolhido na lista.

#### Scenario: Força de um DTB descartado
- **WHEN** `BOOT/dtbs/force` nomeia um DTB que foi descartado neste aparelho
- **THEN** o boot ignora o arquivo, registra o motivo no log e segue as outras escolhas

### Requirement: Escolha por aparelho
A escolha salva, os DTBs confirmados e os descartados MUST ser guardados por aparelho, identificado pelo número de série do SoC, de modo que o mesmo cartão em dois aparelhos do mesmo SoC mantenha uma escolha para cada um. Sem número de série do SoC, eles MUST ser guardados por SoC, e o log MUST avisar disso. A escolha forçada pelo PC vale para o cartão, em qualquer aparelho do SoC.

#### Scenario: Cartão levado a outro GA36
- **WHEN** o painel 2 foi escolhido e confirmado num GA36 e o cartão é ligado em outro GA36
- **THEN** o segundo GA36 sobe pelas regras ou pelo padrão, sem a escolha do primeiro, e o primeiro continua com o painel 2 quando o cartão volta para ele

#### Scenario: Sem número de série
- **WHEN** o kernel do console não informa o número de série do SoC
- **THEN** a escolha vale para todo aparelho daquele SoC e o log registra o aviso

### Requirement: Precedência das escolhas
O boot MUST decidir o DTB nesta ordem: escolha forçada pelo PC; escolha feita na lista neste boot; volta ao último que funcionou; escolha manual gravada; escolha automática; padrão.

#### Scenario: Força acima da lista
- **WHEN** `BOOT/dtbs/force` nomeia um DTB válido e o usuário segura a tecla de seleção
- **THEN** o boot usa o DTB do `force` e a lista informa que a escolha está forçada pelo PC

### Requirement: No máximo uma troca e uma volta por boot
Quando o DTB escolhido não é o que o bootloader carregou, o boot MUST reiniciar o mesmo kernel com o DTB escolhido sem passar de novo pelo bootloader, e o kernel reiniciado MUST seguir sem escolher outra vez. A única troca adicional permitida no mesmo boot é a volta ao DTB anterior quando o novo não é confirmado na tela; o kernel que vem dessa volta MUST seguir sem perguntar nem trocar.

#### Scenario: Troca sem laço
- **WHEN** o DTB escolhido difere do carregado pelo bootloader
- **THEN** o kernel reinicia uma vez com o DTB escolhido, o segundo início registra que o DTB veio da troca e o boot segue até o frontend sem nova troca

#### Scenario: Volta sem laço
- **WHEN** o DTB novo não é confirmado e o kernel volta ao anterior
- **THEN** o terceiro início registra que veio da volta (`reverted`) e segue até o frontend sem perguntar nem trocar

### Requirement: Registro da escolha
O boot MUST registrar no log de boot, em inglês, as leituras feitas, os candidatos considerados e ignorados, o DTB escolhido e a regra ou a escolha que o decidiu. O relatório de hardware do boot MUST trazer o DTB em uso.

#### Scenario: Log de um boot
- **WHEN** o log de boot de qualquer console é lido
- **THEN** ele tem uma linha com o DTB em uso e o motivo (`default`, `rule`, `manual`, `forced`, `fallback`, `reverted`), a confirmação ou a falta dela, o aparelho (número de série do SoC, ou o aviso de que não há), e o relatório `hw/boot-<n>.txt` tem o campo do DTB
