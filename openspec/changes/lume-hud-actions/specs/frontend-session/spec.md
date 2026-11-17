# Spec Delta

## MODIFIED Requirements

### Requirement: Atalhos de controle padronizados
O menu do RetroArch MUST abrir em qualquer jogo pela combinação Fn+B ou pelo item dele no menu do Lume (aberto pelo toque no Fn), e a combinação Start + Select MUST chegar ao jogo sem abrir o menu. Fn+Start MUST encerrar o jogo e voltar ao launcher, sem confirmação. Nenhuma combinação de botões MUST desligar o console.

#### Scenario: Abrir o menu no jogo
- **WHEN** o usuário pressiona Fn+B durante um jogo
- **THEN** o menu do RetroArch abre e o jogo fica pausado

#### Scenario: Start + Select é do jogo
- **WHEN** o usuário pressiona Start + Select durante um jogo
- **THEN** o jogo recebe os dois botões e o menu do RetroArch não abre

#### Scenario: Sem saída acidental
- **WHEN** o usuário pressiona Start + Select, toca o Fn, segura o Fn, pressiona Fn+B ou Esc durante um jogo
- **THEN** o console não desliga e o jogo não é encerrado

#### Scenario: Fn+Start volta ao launcher
- **WHEN** o usuário pressiona Fn+Start durante um jogo do RetroArch
- **THEN** o RetroArch fecha e o launcher reaparece
