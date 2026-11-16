# Spec Delta

## Purpose

Fazer do teste no aparelho pelo cabo USB uma ferramenta do projeto: esperar o boot, conferir o
log e as versões, rodar comandos, capturar a tela, apertar botões e rodar o auto-teste, com
resultado de passou ou falhou.

## ADDED Requirements

### Requirement: Push que confere o boot
Depois de reiniciar o console, o `r36os push` MUST esperar o console voltar pelo cabo, conferir no
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
O `r36os dev` MUST oferecer esperar o console, rodar um comando como root, capturar a tela, mandar
uma sequência de botões e ler o log do boot, nos dois consoles, sem helper fora do projeto.

#### Scenario: Botões no R36S
- **WHEN** o usuário roda `r36os dev keys` com uma sequência no R36S
- **THEN** os botões chegam ao launcher como se apertados, com os dispositivos de entrada daquele console

#### Scenario: Captura de tela
- **WHEN** o usuário roda `r36os dev shot <arquivo>`
- **THEN** o arquivo PNG no PC tem a tela atual do console

### Requirement: Os dois consoles ao mesmo tempo
Com o GA36 e o R36S ligados ao mesmo PC, os comandos de atualização e de teste MUST alcançar cada
um pelo próprio endereço, escolhido por opção ou pelo único que responder, e MUST rodar nos dois
em paralelo quando nenhum for escolhido.

#### Scenario: Conferência nos dois
- **WHEN** os dois consoles estão ligados ao PC e o usuário roda `r36os dev check` sem escolher console
- **THEN** o auto-teste roda nos dois ao mesmo tempo e o resultado de cada um aparece com o nome do console

#### Scenario: Push num só
- **WHEN** os dois estão ligados e o usuário roda `r36os push --console r36s`
- **THEN** só o R36S é atualizado

### Requirement: Build e push a cada arquivo salvo
O `r36os dev watch <fragmento>` MUST refazer o build pontual e o `push --hot` daquele fragmento a
cada mudança nos arquivos de entrada dele, mostrando o resultado de cada ciclo.

#### Scenario: Script salvo
- **WHEN** o `dev watch lume-core` está rodando e um script do `lume-core` é salvo
- **THEN** em segundos o console roda o script novo, e a saída mostra o tempo e o resultado do ciclo

#### Scenario: Fragmento que não aceita push em RAM
- **WHEN** o usuário roda `r36os dev watch lume-kernel`
- **THEN** o comando recusa e diz por quê

### Requirement: Capturas de referência
O `r36os dev shot --compare <tela>` MUST comparar a tela atual com a captura de referência daquela
tela e daquele console e MUST falhar quando a diferença passar do limiar, gravando a imagem da
diferença; as capturas de referência MUST NOT conter nomes de jogos reais.

#### Scenario: Tela mudou
- **WHEN** uma mudança no launcher altera o layout da tela de jogos e o usuário roda a comparação
- **THEN** o comando falha e grava a imagem da diferença

#### Scenario: Referência nova
- **WHEN** o usuário aceita a tela nova com `--update`
- **THEN** a captura passa a ser a referência daquela tela e daquele console

### Requirement: Auto-teste no aparelho
O `r36os dev check` MUST rodar no console o auto-teste dos serviços no modo de aparelho e MUST
terminar com sucesso só se todas as verificações passarem, listando as que falharam.

#### Scenario: Serviço quebrado
- **WHEN** um serviço do projeto não sobe e o usuário roda `r36os dev check`
- **THEN** o comando termina com erro e lista a verificação que falhou
