# Spec Delta

## Purpose

Define os atalhos do sistema durante o jogo: o Fn como modificador do Lume, as ações com nome
que cada acorde dispara, o menu do Lume sobre o jogo e como cada runner executa as ações, para
que os atalhos valham em qualquer emulador e não só no RetroArch.

## ADDED Requirements

### Requirement: Fn pertence ao Lume
O Fn MUST pertencer ao Lume e nunca chegar ao programa aberto, sozinho ou junto de outra tecla. Um acorde Fn+tecla sem ação MUST NOT ser entregue ao programa, nem a tecla sozinha: esses acordes ficam reservados para atalhos futuros.

#### Scenario: Acorde reservado
- **WHEN** o usuário segura Fn e aperta A durante um jogo
- **THEN** o jogo não recebe nem o A nem o Fn, e nada mais acontece

### Requirement: Três gestos do Fn, à moda do botão Steam
O daemon de entrada MUST distinguir três gestos do Fn: **toque** (solto antes do tempo de segurar, sem outra tecla), **segurar** (mantido pelo tempo de segurar, sem outra tecla) e **acorde** (outra tecla com o Fn seguro). O tempo de segurar MUST vir do perfil do console (padrão 500 ms). Um Fn que fez acorde MUST NOT virar toque ao ser solto.

#### Scenario: Toque no Fn durante o jogo
- **WHEN** o usuário aperta e solta o Fn, sem outra tecla, durante um jogo do RetroArch
- **THEN** o menu do Lume abre sobre o jogo

#### Scenario: Acorde não vira toque
- **WHEN** o usuário segura Fn, aperta e solta R1, e depois solta o Fn rapidamente
- **THEN** só o `save_state` acontece e o menu do Lume não abre

### Requirement: Dica dos acordes ao segurar o Fn
Segurar o Fn durante um jogo MUST mostrar sobre o jogo os acordes que valem nele (as ações que o runner declara, mais Fn+Start), com o botão e o nome da ação no idioma do usuário, sem pausar o jogo. Soltar o Fn MUST esconder a dica sem abrir o menu do Lume; um acorde MUST esconder a dica e ser executado. A lista MUST vir da tabela do daemon de entrada, sem segunda cópia.

#### Scenario: Descobrir os atalhos
- **WHEN** o usuário segura o Fn sozinho por 1 segundo durante um jogo do RetroArch
- **THEN** aparece a lista com Fn+B, Fn+R1, Fn+L1, Fn+Y, Fn+X e Fn+Start e o nome de cada ação

#### Scenario: Soltar sem escolher
- **WHEN** a dica está na tela e o usuário solta o Fn sem apertar outra tecla
- **THEN** a dica some, o menu do Lume não abre e o jogo continua

#### Scenario: Acorde a partir da dica
- **WHEN** a dica está na tela e o usuário aperta R1 sem soltar o Fn
- **THEN** a dica some e o estado é gravado

#### Scenario: Runner com menos ações
- **WHEN** o usuário segura o Fn num jogo cujo runner só declara `app_menu`
- **THEN** a dica lista só Fn+B e Fn+Start

### Requirement: Acordes do sistema
Durante um jogo, Fn+B MUST disparar `app_menu`, Fn+R1 `save_state`, Fn+L1 `load_state`, Fn+Y `screenshot`, Fn+X `hud` e Fn+Start `quit`. As duas teclas de um acorde MUST NOT chegar ao programa. Os acordes MUST ser os mesmos no GA36 e no R36S.

#### Scenario: Acorde não vaza para o jogo
- **WHEN** o usuário segura Fn e aperta R1 durante um jogo
- **THEN** o jogo não recebe o R1

#### Scenario: Mesmos acordes nos dois consoles
- **WHEN** o mesmo cartão é usado no GA36 e depois no R36S
- **THEN** o toque no Fn, Fn+B, Fn+R1, Fn+L1, Fn+Y, Fn+X e Fn+Start fazem a mesma coisa nos dois

### Requirement: Ações executadas pelo runner do jogo
As ações `app_menu`, `reset`, `save_state`, `load_state`, `screenshot` e `quit` MUST ser executadas pelo supervisor do jogo pela forma que o runner do jogo declara. Uma ação que o runner não declara MUST ser ignorada, com uma linha no log que diz a ação e o runner. Fora de um jogo, com o launcher na tela, todos os acordes do jogo MUST ser ignorados; o toque e o segurar do Fn no launcher pertencem ao launcher e ficam fora desta change.

#### Scenario: Ação não suportada
- **WHEN** o usuário aperta Fn+R1 num jogo LÖVE cujo runner não declara `save_state`
- **THEN** o jogo continua sem mudança e o log do supervisor registra `save_state` não suportado pelo runner `love`

#### Scenario: No launcher
- **WHEN** o usuário aperta Fn+R1 ou Fn+B na grade de jogos
- **THEN** o launcher continua na mesma tela

### Requirement: Menu da aplicação pelo Fn+B
No RetroArch, a ação `app_menu` MUST abrir o menu do RetroArch com o jogo pausado e, apertada de novo com o menu aberto, MUST fechá-lo e voltar ao jogo.

#### Scenario: Abrir e fechar
- **WHEN** o usuário aperta Fn+B durante um jogo do RetroArch e depois Fn+B de novo
- **THEN** o menu do RetroArch abre com o jogo pausado e, no segundo acorde, fecha e o jogo continua

### Requirement: Menu do Lume sobre o jogo
O toque no Fn MUST abrir, sobre a imagem do jogo, o menu do Lume com os itens, nesta ordem, Voltar ao jogo, Encerrar jogo, Reiniciar e Menu da aplicação (com o nome dela, "Menu do RetroArch" no RetroArch). B ou outro toque no Fn MUST fechar o menu e voltar ao jogo. Os textos MUST seguir o idioma do usuário.

#### Scenario: Abrir e voltar
- **WHEN** o usuário toca o Fn durante um jogo do RetroArch e depois aperta B
- **THEN** o menu do Lume aparece sobre o jogo e, com o B, some e o jogo continua de onde estava

#### Scenario: Fechar com outro toque
- **WHEN** o menu do Lume está aberto e o usuário toca o Fn
- **THEN** o menu some e o jogo continua de onde estava

#### Scenario: Ir ao menu da aplicação
- **WHEN** o usuário escolhe "Menu do RetroArch" no menu do Lume
- **THEN** o menu do Lume some e o menu do RetroArch abre, como no Fn+B

### Requirement: Jogo pausado com o menu do Lume
Ao abrir o menu do Lume, o jogo MUST ser pausado pela ação `pause` do runner (no RetroArch, a pausa do próprio RetroArch, a mesma para qualquer core), sem som. Ao voltar ao jogo, ele MUST ser despausado só se foi o menu que o pausou. Sem `pause` declarada, o sistema MUST congelar o programa enquanto o menu estiver aberto.

#### Scenario: Jogo parado
- **WHEN** o menu do Lume fica aberto por 10 segundos
- **THEN** o jogo não avança nesse tempo e volta do mesmo ponto ao fechar o menu

#### Scenario: Jogo que já estava pausado
- **WHEN** o jogo estava pausado pelo RetroArch e o usuário abre e fecha o menu do Lume
- **THEN** o jogo continua pausado, como estava

#### Scenario: Runner sem pausa
- **WHEN** o usuário abre o menu do Lume num Port e volta ao jogo
- **THEN** o Port fica parado com o menu aberto e continua de onde estava ao voltar

### Requirement: Aplicação sem resposta
Se a aplicação não responder à pausa em até 1 segundo depois do toque no Fn, o menu do Lume MUST aparecer mesmo assim, com o item "Forçar fechamento", que MUST encerrar todos os processos do jogo na hora e voltar ao launcher.

#### Scenario: RetroArch travado
- **WHEN** o RetroArch está travado e o usuário toca o Fn
- **THEN** em até 2 segundos o menu do Lume aparece com "Forçar fechamento", e escolhê-lo fecha o RetroArch e mostra o launcher

### Requirement: Confirmação de Reiniciar e Encerrar
Reiniciar e Encerrar jogo MUST pedir confirmação, com Não em foco, antes de agir. Confirmado, Reiniciar MUST reiniciar o jogo pela ação `reset` do runner, e Encerrar MUST seguir o mesmo encerramento educado do Fn+Start. Não ou B MUST voltar ao menu do Lume sem mudar nada.

#### Scenario: Encerrar confirmado
- **WHEN** o usuário escolhe Encerrar jogo e confirma com Sim
- **THEN** a SRAM é gravada, o jogo fecha e o launcher reaparece

#### Scenario: Engano no Reiniciar
- **WHEN** o usuário escolhe Reiniciar e aperta A sem mover o foco
- **THEN** nada é reiniciado, porque o foco começa em Não

### Requirement: Controle capturado só com o menu do Lume aberto
Com o menu do Lume aberto, os botões MUST navegar o menu e MUST NOT chegar ao jogo. Ao fechar o menu, o controle MUST voltar ao jogo sem botão preso. Se o supervisor do jogo terminar ou parar de responder com o menu aberto, o controle MUST voltar ao jogo em até 2 segundos.

#### Scenario: Botão não vaza
- **WHEN** o menu do Lume está aberto e o usuário aperta A para escolher um item
- **THEN** o jogo não recebe o A

#### Scenario: Supervisor some
- **WHEN** o supervisor do jogo termina com o menu do Lume aberto
- **THEN** em até 2 segundos o controle volta a funcionar no jogo

### Requirement: Menu do Lume em qualquer runner
O menu do Lume MUST ser desenhado pelo sistema, e não pela aplicação, para aparecer sobre qualquer runner (RetroArch, LÖVE, Ports, emuladores standalone), travado ou não. Os itens que dependem de ação do runner (Reiniciar, Menu da aplicação) MUST aparecer só quando o runner os declara.

#### Scenario: Port nativo
- **WHEN** o usuário toca o Fn num script de Ports
- **THEN** o menu do Lume aparece com Voltar ao jogo e Encerrar jogo, e Voltar ao jogo retoma o script

### Requirement: Dica dos acordes só em runner que a desenha
A dica dos acordes MUST aparecer só em jogos cujo runner declara que sabe desenhá-la (o RetroArch nesta versão). Nos demais, segurar o Fn MUST ser ignorado com uma linha no log, e os acordes que o runner declara MUST continuar valendo.

#### Scenario: Segurar o Fn num Port
- **WHEN** o usuário segura o Fn num script de Ports
- **THEN** nada aparece, o log registra que o runner `sh` não desenha a dica, e Fn+Start ainda encerra o script

### Requirement: Salvar e carregar no slot rápido
No RetroArch, `save_state` MUST gravar o estado no slot rápido da sessão e `load_state` MUST carregar desse mesmo slot. O slot rápido MUST ser o 0, ou o slot N quando o jogo foi aberto pelo launcher a partir do slot N. O RetroArch MUST mostrar a confirmação dele. Carregar sem estado salvo MUST deixar o jogo como está.

#### Scenario: Jogo aberto pela grade
- **WHEN** o usuário abre um jogo pela grade e aperta Fn+R1
- **THEN** o estado é gravado no slot 0

#### Scenario: Jogo aberto de um slot
- **WHEN** o usuário abre um jogo pelo slot 3 em "Save states" e aperta Fn+R1
- **THEN** o estado é gravado no slot 3

#### Scenario: Salvar e voltar
- **WHEN** o usuário aperta Fn+R1, joga mais um pouco e aperta Fn+L1
- **THEN** o jogo volta ao ponto do Fn+R1

#### Scenario: Carregar sem estado
- **WHEN** o usuário aperta Fn+L1 num jogo que nunca teve estado salvo
- **THEN** o jogo continua de onde estava

### Requirement: Foto do jogo pelo Fn+Y
No RetroArch, a ação `screenshot` MUST gravar a imagem atual do jogo, sem a barra de status nem o menu do Lume, como PNG em `ROMS/screenshots/`, sem sobrescrever uma foto anterior, e o RetroArch MUST mostrar a confirmação dele. O jogo MUST continuar sem pausa perceptível.

#### Scenario: Duas fotos seguidas
- **WHEN** o usuário aperta Fn+Y duas vezes, com alguns segundos entre elas, durante um jogo
- **THEN** `ROMS/screenshots/` ganha dois arquivos PNG diferentes, legíveis no PC

#### Scenario: Barra visível
- **WHEN** a barra de status está visível e o usuário aperta Fn+Y
- **THEN** a foto mostra só a imagem do jogo, sem a barra

### Requirement: Foto em todo save state
Todo save state gravado pelo RetroArch aberto pelo launcher MUST gravar a imagem do jogo ao lado do estado, também num cartão criado antes desta versão ou em que a opção tenha sido desligada no menu do RetroArch.

#### Scenario: Foto no menu do jogo
- **WHEN** o usuário salva pelo Fn+R1, sai do jogo e abre "Save states" no menu do jogo
- **THEN** o slot 0 aparece com a imagem do momento em que foi salvo

#### Scenario: Cartão antigo
- **WHEN** a configuração do RetroArch no cartão tem a captura da imagem do estado desligada
- **THEN** um save state gravado no jogo ainda tem a imagem ao lado

### Requirement: Slots salvos no jogo vão para o registro do launcher
Um estado salvo pelo Fn+R1 MUST entrar no registro de save states do launcher com o core do jogo, como um estado salvo pelo menu do RetroArch.

#### Scenario: Slot do core efetivo
- **WHEN** o usuário salva pelo Fn+R1 num jogo de SNES aberto no Snes9x 2010 e sai do jogo
- **THEN** "Save states" do jogo lista o slot 0 como do Snes9x 2010
