# Spec Delta

## Purpose

Define os atalhos do sistema durante o jogo: o Fn como modificador do Lume, as ações com nome
que cada acorde dispara, o menu do Lume sobre o jogo e como cada runner executa as ações, para
que os atalhos valham em qualquer emulador e não só no RetroArch.

## ADDED Requirements

### Requirement: Fn é o modificador do sistema
O Fn MUST pertencer ao Lume e nunca chegar ao programa aberto, sozinho ou junto de outra tecla. O Fn apertado e solto sem outra tecla MUST NOT fazer nada. Um acorde Fn+tecla sem ação MUST NOT ser entregue ao programa, nem a tecla sozinha: esses acordes ficam reservados para atalhos futuros.

#### Scenario: Fn sozinho
- **WHEN** o usuário aperta e solta o Fn durante um jogo do RetroArch
- **THEN** nada acontece: nenhum menu abre e o jogo continua

#### Scenario: Acorde reservado
- **WHEN** o usuário segura Fn e aperta A durante um jogo
- **THEN** o jogo não recebe nem o A nem o Fn

### Requirement: Acordes do sistema
Durante um jogo, Fn+Select MUST disparar `lume_menu`, Fn+B `app_menu`, Fn+R1 `save_state`, Fn+L1 `load_state`, Fn+Y `screenshot`, Fn+X `hud` e Fn+Start `quit`. As duas teclas de um acorde MUST NOT chegar ao programa. Os acordes MUST ser os mesmos no GA36 e no R36S.

#### Scenario: Acorde não vaza para o jogo
- **WHEN** o usuário segura Fn e aperta R1 durante um jogo
- **THEN** o jogo não recebe o R1

#### Scenario: Mesmos acordes nos dois consoles
- **WHEN** o mesmo cartão é usado no GA36 e depois no R36S
- **THEN** Fn+Select, Fn+B, Fn+R1, Fn+L1, Fn+Y, Fn+X e Fn+Start fazem a mesma coisa nos dois

### Requirement: Ações executadas pelo runner do jogo
As ações `app_menu`, `reset`, `save_state`, `load_state`, `screenshot` e `quit` MUST ser executadas pelo supervisor do jogo pela forma que o runner do jogo declara. Uma ação que o runner não declara MUST ser ignorada, com uma linha no log que diz a ação e o runner. Fora de um jogo, com o launcher na tela, todos os acordes MUST ser ignorados.

#### Scenario: Ação não suportada
- **WHEN** o usuário aperta Fn+R1 num jogo LÖVE cujo runner não declara `save_state`
- **THEN** o jogo continua sem mudança e o log do supervisor registra `save_state` não suportado pelo runner `love`

#### Scenario: No launcher
- **WHEN** o usuário aperta Fn+R1 ou Fn+Select na grade de jogos
- **THEN** o launcher continua na mesma tela

### Requirement: Menu da aplicação pelo Fn+B
No RetroArch, a ação `app_menu` MUST abrir o menu do RetroArch com o jogo pausado e, apertada de novo com o menu aberto, MUST fechá-lo e voltar ao jogo.

#### Scenario: Abrir e fechar
- **WHEN** o usuário aperta Fn+B durante um jogo do RetroArch e depois Fn+B de novo
- **THEN** o menu do RetroArch abre com o jogo pausado e, no segundo acorde, fecha e o jogo continua

### Requirement: Menu do Lume sobre o jogo
Fn+Select MUST abrir, sobre a imagem do jogo, o menu do Lume com os itens Voltar ao jogo, Reiniciar, Menu da aplicação (com o nome dela, "Menu do RetroArch" no RetroArch) e Encerrar jogo. B ou Fn+Select de novo MUST fechar o menu e voltar ao jogo. Os textos MUST seguir o idioma do usuário.

#### Scenario: Abrir e voltar
- **WHEN** o usuário aperta Fn+Select durante um jogo do RetroArch e depois B
- **THEN** o menu do Lume aparece sobre o jogo e, com o B, some e o jogo continua de onde estava

#### Scenario: Ir ao menu da aplicação
- **WHEN** o usuário escolhe "Menu do RetroArch" no menu do Lume
- **THEN** o menu do Lume some e o menu do RetroArch abre, como no Fn+B

### Requirement: Jogo pausado com o menu do Lume
Com o menu do Lume aberto, o jogo MUST ficar pausado, sem som, e MUST continuar exatamente de onde parou ao fechar, mesmo que já estivesse pausado antes.

#### Scenario: Jogo parado
- **WHEN** o menu do Lume fica aberto por 10 segundos
- **THEN** o jogo não avança nesse tempo e volta do mesmo ponto ao fechar o menu

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

### Requirement: Menu do Lume só em runner que o desenha
O menu do Lume MUST abrir só em jogos cujo runner declara que sabe desenhá-lo (o RetroArch nesta versão). Nos demais, Fn+Select MUST ser ignorado com uma linha no log, e Fn+Start MUST continuar encerrando o jogo.

#### Scenario: Port nativo
- **WHEN** o usuário aperta Fn+Select num script de Ports
- **THEN** nada muda na tela, o log registra que o runner `sh` não tem o menu do Lume, e Fn+Start ainda encerra o script

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
