# Spec Delta

## Purpose

Define como o console escolhe sozinho o perfil de energia de cada cenário de uso (boot, menu,
launcher parado, jogo) para durar mais na bateria sem perder qualidade de jogo, e o que ele faz
quando a bateria está acabando.

## ADDED Requirements

### Requirement: Perfil escolhido pelo cenário
O console MUST aplicar sozinho, sem precisar de escolha do usuário, o perfil de energia do cenário em curso: boot, menu do launcher, launcher parado e jogo. A troca de perfil MUST acontecer só na mudança de cenário, nunca no meio de um jogo; dentro do jogo, só o controlador (pela carga ou por gargalo), quando o perfil o liga, MAY variar o clock da CPU ou o piso do clock da GPU, e sempre dentro da faixa de cada recurso no perfil.

#### Scenario: Do menu ao jogo e de volta
- **WHEN** o usuário abre um jogo pelo launcher e depois volta ao launcher
- **THEN** o perfil do jogo vale enquanto o jogo roda, o do menu volta ao reaparecer o launcher, e o `events.log` registra cada troca com o cenário e o perfil

#### Scenario: Jogo longo
- **WHEN** um jogo fica aberto por 30 minutos
- **THEN** o perfil não muda durante o jogo, a menos que a proteção térmica do kernel reduza o clock

### Requirement: Perfil do jogo por classe de sistema
O perfil de um jogo MUST vir da classe do sistema do jogo, com exceção possível por core e, acima dela, por jogo (ajuste do cartão). Um sistema sem classe MUST usar o perfil de jogo padrão.

#### Scenario: Sistemas leves e pesados
- **WHEN** o usuário abre um jogo de NES e depois um de PlayStation
- **THEN** cada um roda com o perfil da sua classe, registrado no `events.log`

#### Scenario: Sistema novo
- **WHEN** um sistema sem classe declarada é aberto
- **THEN** o jogo roda com o perfil de jogo padrão

### Requirement: Perfis dentro dos limites do hardware
Todo perfil MUST ficar dentro da tabela de frequências e tensões do device tree mainline e MUST NOT desligar ou mudar as proteções térmicas do kernel. Um valor fora da tabela MUST ser recusado com uma linha no log, ficando o perfil padrão do kernel.

#### Scenario: Valor inválido
- **WHEN** o arquivo de perfis pede um clock que não existe na tabela do console
- **THEN** o perfil é recusado, o log diz qual valor e qual console, e a CPU fica com o governor padrão do kernel

### Requirement: Piso de clock nos jogos do GA36
No GA36, o mínimo da CPU durante um jogo MUST NOT ser o menor clock da tabela: todo perfil usado em jogo MUST ter um mínimo de pelo menos o piso de jogo do console (600 MHz no início), inclusive quando o perfil é recusado, quando os perfis estão desligados ou quando o usuário o sobrescreve. Uma classe MAY ter piso maior, nunca menor, e só quando uma medição mostrar quadros perdidos sem ele (preferência do usuário: o menor clock que mantém o jogo bom). O piso só muda no arquivo da imagem.

#### Scenario: Perfil de jogo recusado
- **WHEN** o perfil da classe de um jogo é recusado no GA36
- **THEN** o jogo roda com o governor padrão do kernel e o `scaling_min_freq` no piso de jogo, e o log diz por que o perfil foi recusado

#### Scenario: Ajuste do usuário abaixo do piso
- **WHEN** o arquivo de ajustes do cartão pede um mínimo abaixo do piso de jogo para uma classe
- **THEN** essa linha é recusada com uma linha no log e vale o perfil da imagem

#### Scenario: Clock abaixo do piso de jogo
- **WHEN** um jogo roda no GA36
- **THEN** as métricas desse jogo não trazem clock abaixo do mínimo do perfil dele, a não ser que a proteção térmica do kernel baixe o teto

### Requirement: Jogo sem perder quadros
O perfil de cada classe de jogo MUST rodar os jogos de teste sem mais eventos `game FAIL slow` do que o governor padrão do kernel nas mesmas sessões, nos dois consoles.

#### Scenario: Comparação com o padrão
- **WHEN** a mesma sessão de teste de um sistema é jogada com o governor padrão e com o perfil da classe
- **THEN** o perfil não tem mais eventos `game FAIL slow` que o padrão e consome igual ou menos corrente média da bateria

### Requirement: Launcher parado gasta menos
Com o launcher na tela e nenhum botão apertado por alguns minutos, o console MUST passar ao perfil de launcher parado e escurecer a tela; o primeiro botão MUST devolver o brilho e o perfil do menu, sem executar a ação desse botão.

#### Scenario: Voltar do escuro
- **WHEN** o launcher fica parado até a tela escurecer e o usuário aperta A
- **THEN** a tela volta ao brilho escolhido e nada é aberto pelo A

### Requirement: Controlador pela carga do jogo
Um perfil de jogo MAY ligar o controlador pela carga: durante o jogo, a frequência da CPU MUST subir um degrau da tabela quando a thread principal do jogo passar de cerca de 85% de um núcleo por 1 s e descer um degrau abaixo de cerca de 50% por 3 s, sempre dentro da faixa do perfil e do teto que a proteção térmica do kernel impõe.

#### Scenario: Carga alta sobe o clock
- **WHEN** a thread principal de um jogo com o controlador ligado fica acima de 85% de um núcleo por mais de 1 s
- **THEN** a frequência sobe um degrau da tabela, sem passar do máximo do perfil

#### Scenario: Fim do jogo
- **WHEN** o jogo com o controlador ligado termina
- **THEN** o controlador para e o perfil do menu volta, como em qualquer fim de jogo

### Requirement: Controlador por gargalo
Um perfil de jogo MAY ligar o controlador por gargalo. Durante o jogo, ele MUST medir a cada segundo os quadros entregues à tela, a ocupação da GPU e a da thread mais ocupada da CPU, e MUST subir só o recurso que limita: o recurso acima de cerca de 85% de ocupação sobe um degrau; com quadros perdidos e nenhum recurso saturado, sobe o mais ocupado; um recurso abaixo de cerca de 50% por 3 s, sem quadros perdidos nesse tempo, desce um degrau. Cada recurso MUST ficar dentro da sua faixa no perfil e abaixo do teto térmico do kernel. O controlador MUST publicar, legível sem root, o degrau de cada recurso e o último gargalo visto, e MUST registrar no `events.log`, ao fim do jogo, o tempo em cada degrau de cada recurso e quantas vezes cada gargalo apareceu. Nenhum dado publicado ou registrado MAY trazer nome de jogo.

#### Scenario: Jogo limitado pela GPU
- **WHEN** num jogo com o controlador por gargalo a GPU passa de 85% de ocupação e a CPU fica folgada
- **THEN** o piso do clock da GPU sobe e o clock da CPU não sobe

#### Scenario: Jogo leve com CPU sobrando
- **WHEN** num jogo com o controlador por gargalo a thread mais ocupada fica abaixo de 50% de um núcleo por mais de 3 s, sem quadros perdidos
- **THEN** o clock da CPU desce um degrau, sem passar abaixo do mínimo do perfil (no GA36, o piso de jogo)

#### Scenario: Quadros perdidos sem recurso saturado
- **WHEN** o jogo entrega menos quadros que o seu ritmo e nem a CPU nem a GPU passam de 85%
- **THEN** o recurso mais ocupado sobe um degrau, e o gargalo publicado é o de ritmo

#### Scenario: Recurso travado
- **WHEN** o perfil do jogo tem a faixa da GPU com um só degrau
- **THEN** o controlador nunca muda a GPU e continua controlando a CPU

### Requirement: Ajuste manual por recurso e por jogo
O arquivo de ajustes do cartão MUST permitir escolher, separadamente, a faixa de clock da CPU e a da GPU de um perfil (uma faixa de um só degrau trava o recurso), e MUST permitir ligar um perfil a um jogo, acima da exceção por core e da classe do sistema. Um jogo MUST ser identificado por uma chave calculada do caminho da ROM, nunca pelo nome, no arquivo, no estado publicado e nos logs. O piso de clock nos jogos do GA36 MUST valer também para o perfil de um jogo.

#### Scenario: Perfil de um jogo
- **WHEN** o arquivo de ajustes liga um perfil à chave de um jogo e o usuário abre esse jogo
- **THEN** o jogo roda com esse perfil, mesmo com uma classe ou exceção por core para o sistema dele, e o `events.log` e o estado publicado mostram só a chave

#### Scenario: Só a GPU fixada pelo usuário
- **WHEN** um perfil traz o piso e o teto da GPU no mesmo clock e a CPU com a faixa inteira e o controlador por gargalo
- **THEN** a GPU fica nesse clock durante o jogo e a CPU varia pelo controlador

### Requirement: Ajustes pelo cartão
O usuário MUST poder, num arquivo de texto da partição `ROMS`, sobrescrever perfis, mudar o tempo do launcher parado e desligar os perfis. Com os perfis desligados, a CPU e a GPU MUST ficar no padrão do kernel, exceto o piso de clock nos jogos do GA36. Um valor inválido MUST ser ignorado com uma linha no log, valendo o padrão.

#### Scenario: Perfis desligados
- **WHEN** o arquivo de ajustes desliga os perfis e o console reinicia
- **THEN** a CPU usa o governor padrão do kernel em todos os cenários (no GA36, com o piso nos jogos) e o `events.log` registra que os perfis estão desligados

### Requirement: Ajustes prontos para a interface
O mesmo arquivo de ajustes do cartão MUST poder ser mudado por um programa, sem reiniciar e sem perder o que o usuário escreveu à mão: o sistema MUST publicar, legível sem root, o estado em vigor (valores aceitos pelo console, perfis com a origem de cada um, cenário e perfil atuais, perfis recusados) e MUST aceitar um pedido para reler os ajustes. A gravação feita por programa MUST manter comentários e linhas desconhecidas e MUST ser atômica.

#### Scenario: Ajuste mudado com o console ligado
- **WHEN** um programa muda o perfil de uma classe no arquivo de ajustes e pede a releitura
- **THEN** o próximo jogo dessa classe roda com o perfil novo, sem reiniciar, e o estado publicado mostra o perfil com a origem no cartão

#### Scenario: Arquivo escrito à mão preservado
- **WHEN** o programa grava uma mudança num arquivo de ajustes com comentários do usuário
- **THEN** os comentários e as outras linhas continuam iguais, e um corte de energia no meio deixa o arquivo antigo ou o novo, nunca um pela metade

#### Scenario: Tempo do launcher parado
- **WHEN** o arquivo de ajustes muda o tempo do launcher parado para 5 minutos
- **THEN** a tela escurece só depois de 5 minutos sem botão

### Requirement: Relatório de energia no PC
O projeto MUST ter um comando no PC que lê as métricas e os eventos do cartão e resume, por cenário e por sistema, a corrente média da bateria, o FPS contra o nominal, os eventos `game FAIL slow`, a CPU por núcleo, o clock médio, a temperatura máxima e o custo do coletor de métricas. O relatório MUST NOT trazer nome de jogo nem caminho de ROM.

#### Scenario: Antes e depois
- **WHEN** o relatório é gerado sobre sessões com o governor padrão e com os perfis
- **THEN** cada sistema aparece com as duas medições lado a lado, sem nome de jogo

### Requirement: Aviso de bateria fraca
Descarregando e num nível baixo de bateria, o console MUST avisar o usuário uma vez, no launcher ou por cima do jogo, nos idiomas do sistema.

#### Scenario: Aviso no jogo
- **WHEN** a bateria cai ao nível de aviso durante um jogo do RetroArch
- **THEN** uma mensagem aparece por cima do jogo e o jogo continua

#### Scenario: Carregando
- **WHEN** a bateria está no nível de aviso com o carregador ligado
- **THEN** nenhum aviso aparece

### Requirement: Desligamento limpo com bateria crítica
Descarregando e no nível crítico, o console MUST desligar sozinho pelo caminho normal: o jogo aberto recebe o pedido de saída (o RetroArch grava a SRAM), os dados e os logs são gravados e o cartão fica limpo. O desligamento MUST ser registrado no `events.log`.

#### Scenario: Bateria acabando no jogo
- **WHEN** a bateria chega ao nível crítico durante um jogo do RetroArch com save interno alterado
- **THEN** o save é gravado, o console desliga, e o boot seguinte registra o desligamento anterior como limpo e o motivo `battery critical`
