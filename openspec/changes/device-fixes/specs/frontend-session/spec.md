# Spec Delta

## ADDED Requirements

### Requirement: Reiniciar pelo frontend
O contrato de sessão MUST ter um fim de frontend que pede reinício, distinto do fim normal que desliga e dos fins com erro. Pedido o reinício, o sistema MUST gravar o pendente e reiniciar o aparelho, sem contar como falha do frontend. Um frontend que não usa esse fim MUST continuar funcionando como antes.

#### Scenario: Reiniciar pelo launcher
- **WHEN** o usuário escolhe Reiniciar no menu do sistema do launcher e confirma
- **THEN** o sistema grava o que estiver pendente, reinicia, e o `events.log` registra o reinício pedido pelo usuário, não uma falha

#### Scenario: RetroArch como frontend
- **WHEN** o frontend configurado é o RetroArch e o usuário sai pelo menu dele
- **THEN** o aparelho desliga, como antes

## MODIFIED Requirements

### Requirement: Sair desliga o console
Quando o frontend encerrar normalmente por ação do usuário, o sistema MUST desligar o aparelho. No lume-launcher, essa ação é o item Desligar do menu do sistema (aberto pelo toque no Fn); encerrar um jogo ou o menu do RetroArch aberto pelo launcher MUST voltar ao launcher, não desligar.

#### Scenario: Sair pelo menu
- **WHEN** o usuário escolhe Desligar no menu do sistema do launcher e confirma
- **THEN** o sistema grava o que estiver pendente e desliga

#### Scenario: Desligar pede confirmação por padrão
- **WHEN** o usuário abre Desligar e aperta A sem mover o foco, que começa em Cancelar
- **THEN** nada acontece e o aparelho continua ligado

#### Scenario: Sair do RetroArch não desliga
- **WHEN** o usuário escolhe sair no menu do RetroArch durante um jogo aberto pelo launcher
- **THEN** o RetroArch fecha, o launcher reaparece e o aparelho continua ligado
