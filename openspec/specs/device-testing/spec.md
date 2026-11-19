# device-testing Specification

## Purpose

Fazer do teste no aparelho pelo cabo USB uma ferramenta do projeto: esperar o boot, conferir o
log e as versões, rodar comandos, capturar a tela, apertar botões e rodar o auto-teste, com
resultado de passou ou falhou.

## Requirements

### Requirement: Push que confere o boot
Depois de reiniciar o console, o `lume push` MUST esperar o console voltar pelo cabo, conferir no
log do boot novo que o boot terminou, que os slots do manifesto foram montados e que os fragmentos
enviados estão nas versões novas, e MUST terminar com sucesso só se tudo conferir.

#### Scenario: Boot certo
- **WHEN** o `push` envia um slot novo e o console reinicia normalmente
- **THEN** o comando mostra `ok` com os tempos de envio e de boot e termina com sucesso

#### Scenario: Boot que não volta
- **WHEN** o console não volta pelo cabo dentro do tempo limite
- **THEN** o comando termina com erro e diz o último passo conferido

#### Scenario: Versão errada
- **WHEN** o console volta, mas um fragmento enviado aparece no log com a versão antiga
- **THEN** o comando termina com erro nomeando o fragmento e as duas versões

### Requirement: Comandos de teste no aparelho
O `lume dev` MUST oferecer esperar o console, rodar um comando como root, capturar a tela, mandar
uma sequência de botões e ler o log do boot, nos dois consoles, sem helper fora do projeto.

#### Scenario: Botões no R36S
- **WHEN** o usuário roda `lume dev keys` com uma sequência no R36S
- **THEN** os botões chegam ao launcher como se apertados, com os dispositivos de entrada daquele console

#### Scenario: Captura de tela
- **WHEN** o usuário roda `lume dev shot <arquivo>`
- **THEN** o arquivo PNG no PC tem a tela atual do console

### Requirement: Console identificado pelo cabo
Com um único cartão usado nos dois consoles, um por vez no cabo, os comandos de atualização e de
teste MUST dizer qual console respondeu e, quando um console for escolhido por opção, MUST recusar
rodar no outro.

#### Scenario: Console certo
- **WHEN** o R36S está no cabo e o usuário roda `lume dev check --console r36s`
- **THEN** o auto-teste roda e o resultado aparece com o nome do console

#### Scenario: Console errado
- **WHEN** o GA36 está no cabo e o usuário roda `lume push --console r36s`
- **THEN** o comando recusa sem enviar nada, dizendo que o console ligado é o GA36

### Requirement: Build e push a cada arquivo salvo
O `lume dev watch <fragmento>` MUST refazer o build pontual e o `push --hot` daquele fragmento a
cada mudança nos arquivos de entrada dele, mostrando o resultado de cada ciclo.

#### Scenario: Script salvo
- **WHEN** o `dev watch lume-core` está rodando e um script do `lume-core` é salvo
- **THEN** em segundos o console roda o script novo, e a saída mostra o tempo e o resultado do ciclo

#### Scenario: Fragmento que não aceita push em RAM
- **WHEN** o usuário roda `lume dev watch lume-kernel`
- **THEN** o comando recusa e diz por quê

### Requirement: Capturas de referência
O `lume dev shot --compare <tela>` MUST comparar a tela atual com a captura de referência daquela
tela e daquele console e MUST falhar quando a diferença passar do limiar, gravando a imagem da
diferença; as capturas de referência MUST NOT conter nomes de jogos reais.

#### Scenario: Tela mudou
- **WHEN** uma mudança no launcher altera o layout da tela de jogos e o usuário roda a comparação
- **THEN** o comando falha e grava a imagem da diferença

#### Scenario: Referência nova
- **WHEN** o usuário aceita a tela nova com `--update`
- **THEN** a captura passa a ser a referência daquela tela e daquele console

### Requirement: Auto-teste no aparelho
O `lume dev check` MUST rodar no console o auto-teste dos serviços no modo de aparelho e MUST
terminar com sucesso só se todas as verificações passarem, listando as que falharam.

#### Scenario: Serviço quebrado
- **WHEN** um serviço do projeto não sobe e o usuário roda `lume dev check`
- **THEN** o comando termina com erro e lista a verificação que falhou

### Requirement: Gravar os botões de uma sessão
O `lume dev record` MUST gravar no console os botões que o launcher e os jogos recebem, com o tempo de cada evento, até o comando de parar, e MUST trazer a gravação para a pasta de rascunho do PC, nunca para um arquivo do repositório.

#### Scenario: Sessão gravada
- **WHEN** o usuário roda `lume dev record`, joga 60 s e roda o comando de parar
- **THEN** a gravação tem os botões apertados com os tempos e fica em `cache/` no PC

#### Scenario: Gravação sem botões
- **WHEN** a gravação é parada sem nenhum botão apertado
- **THEN** o comando avisa que a gravação está vazia e termina com erro

### Requirement: Repetir uma gravação com o tempo do console
O `lume dev play` MUST repetir uma gravação no controle que o launcher e os jogos leem, com os intervalos medidos no próprio console, e MUST soltar todos os botões no fim ou quando for interrompido.

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
O `lume dev run <roteiro>` MUST executar os passos de um roteiro do repositório (botões, esperas por evento ou processo, captura comparada com a referência, comando como root) e MUST terminar com sucesso só se todos os passos passarem, dizendo qual passo falhou.

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
O `lume dev replay` MUST gravar a entrada de um jogo do RetroArch desde um ponto salvo e MUST repeti-la quadro a quadro a partir do mesmo ponto, para que duas sessões com o mesmo replay tenham a mesma carga.

#### Scenario: Gravar e repetir
- **WHEN** o usuário grava um replay de um trecho e depois o repete duas vezes
- **THEN** o jogo refaz o mesmo trecho nas duas repetições, sem botão apertado no PC

#### Scenario: Sem jogo do RetroArch
- **WHEN** o comando de replay é dado sem um jogo do RetroArch aberto
- **THEN** o comando termina com erro dizendo que não há jogo do RetroArch rodando

### Requirement: Controle pelo cabo só para o root
As ferramentas de controle pelo cabo MUST rodar só como root, o acesso que o cabo USB já dá, recusando qualquer outro usuário, e MUST NOT abrir nenhum meio novo de mandar botões para um usuário sem root ou pela rede.

#### Scenario: Usuário do jogo
- **WHEN** um processo rodando como o usuário dos jogos tenta repetir uma gravação
- **THEN** a repetição é recusada por falta de permissão e nenhum botão é mandado
