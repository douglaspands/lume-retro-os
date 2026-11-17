# Spec Delta

## ADDED Requirements

### Requirement: Gravar os botões de uma sessão
O `r36os dev record` MUST gravar no console os botões que o launcher e os jogos recebem, com o tempo de cada evento, até o comando de parar, e MUST trazer a gravação para a pasta de rascunho do PC, nunca para um arquivo do repositório.

#### Scenario: Sessão gravada
- **WHEN** o usuário roda `r36os dev record`, joga 60 s e roda o comando de parar
- **THEN** a gravação tem os botões apertados com os tempos e fica em `cache/` no PC

#### Scenario: Gravação sem botões
- **WHEN** a gravação é parada sem nenhum botão apertado
- **THEN** o comando avisa que a gravação está vazia e termina com erro

### Requirement: Repetir uma gravação com o tempo do console
O `r36os dev play` MUST repetir uma gravação no controle que o launcher e os jogos leem, com os intervalos medidos no próprio console, e MUST soltar todos os botões no fim ou quando for interrompido.

#### Scenario: Repetição fiel
- **WHEN** uma gravação de 60 s é repetida no console
- **THEN** cada botão chega com no máximo 10 ms de diferença do tempo gravado

#### Scenario: Interrupção
- **WHEN** a repetição é interrompida no meio, com um botão segurado
- **THEN** o botão é solto e nenhum botão fica preso no launcher nem no jogo

#### Scenario: Atalho com Fn num roteiro
- **WHEN** um roteiro repete uma gravação dentro de um jogo e depois manda Fn+Start
- **THEN** o jogo é encerrado como pelo controle físico e o roteiro vê o evento de jogo fechado

### Requirement: Roteiros de prova com resultado
O `r36os dev run <roteiro>` MUST executar os passos de um roteiro do repositório (botões, esperas por evento ou processo, captura comparada com a referência, comando como root) e MUST terminar com sucesso só se todos os passos passarem, dizendo qual passo falhou.

#### Scenario: Passo que falha
- **WHEN** um roteiro espera um evento que não aparece no tempo limite
- **THEN** o comando termina com erro, nomeando o passo, o evento esperado e o tempo

#### Scenario: Console errado
- **WHEN** o roteiro é só do GA36 e o R36S está no cabo
- **THEN** o comando recusa antes de apertar qualquer botão

### Requirement: Abrir um jogo de um sistema sem nomear o jogo
Um roteiro MUST poder abrir pelo launcher um jogo de um sistema escolhido pelo sistema e pela posição na lista, e MUST conferir que o jogo abriu pelos eventos do console, sem que o roteiro, a saída ou os logs do PC tragam o nome do jogo ou o caminho da ROM.

#### Scenario: Jogo aberto pelo launcher
- **WHEN** um roteiro pede o primeiro jogo do sistema `gba`
- **THEN** o launcher abre esse jogo como pelos botões físicos e o roteiro passa quando o evento de jogo aberto aparece

#### Scenario: Sistema sem jogos no cartão
- **WHEN** o roteiro pede um sistema sem jogos no cartão
- **THEN** o passo falha dizendo que o sistema não tem jogos, sem apertar botões

### Requirement: Replay exato do RetroArch
O `r36os dev replay` MUST gravar a entrada de um jogo do RetroArch desde um ponto salvo e MUST repeti-la quadro a quadro a partir do mesmo ponto, para que duas sessões com o mesmo replay tenham a mesma carga.

#### Scenario: Gravar e repetir
- **WHEN** o usuário grava um replay de um trecho e depois o repete duas vezes
- **THEN** o jogo refaz o mesmo trecho nas duas repetições, sem botão apertado no PC

#### Scenario: Sem jogo do RetroArch
- **WHEN** o comando de replay é dado sem um jogo do RetroArch aberto
- **THEN** o comando termina com erro dizendo que não há jogo do RetroArch rodando

### Requirement: Controle pelo cabo só para o root
As ferramentas de controle pelo cabo MUST exigir o acesso de root que o cabo USB já dá e MUST NOT abrir nenhum meio novo de mandar botões para um usuário sem root ou pela rede.

#### Scenario: Usuário do jogo
- **WHEN** um processo rodando como o usuário dos jogos tenta repetir uma gravação
- **THEN** a repetição é recusada por falta de permissão e nenhum botão é mandado
