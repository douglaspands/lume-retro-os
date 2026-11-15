# Spec Delta

## MODIFIED Requirements

### Requirement: Sair desliga o console
Quando o frontend encerrar normalmente por ação do usuário, o sistema MUST desligar o aparelho. No lume-launcher, essa ação é o item Desligar das Configurações; encerrar um jogo ou o menu do RetroArch aberto pelo launcher MUST voltar ao launcher, não desligar.

#### Scenario: Sair pelo menu
- **WHEN** o usuário escolhe Desligar nas Configurações do launcher e confirma
- **THEN** o sistema grava o que estiver pendente e desliga

#### Scenario: Desligar pede confirmação por padrão
- **WHEN** o usuário abre Desligar e aperta A sem mover o foco, que começa em Cancelar
- **THEN** nada acontece e o aparelho continua ligado

#### Scenario: Sair do RetroArch não desliga
- **WHEN** o usuário escolhe sair no menu do RetroArch durante um jogo aberto pelo launcher
- **THEN** o RetroArch fecha, o launcher reaparece e o aparelho continua ligado

### Requirement: RetroArch como frontend inicial
O frontend padrão desta versão MUST ser o lume-launcher. O RetroArch MUST continuar instalado como provedor dos cores, aberto pelo launcher com o jogo, renderizando direto no vídeo (KMS/DRM) com GLES, com áudio pelo ALSA e controles detectados automaticamente.

#### Scenario: Controle integrado já mapeado
- **WHEN** o RetroArch abre pela primeira vez no console, com um jogo aberto pelo launcher
- **THEN** o controle integrado controla o jogo e navega o menu do RetroArch sem nenhuma configuração manual

#### Scenario: Launcher no boot
- **WHEN** o console termina o boot
- **THEN** o lume-launcher aparece em tela cheia, e não o menu do RetroArch

### Requirement: Menu padrão do RetroArch (Ozone)
O menu do RetroArch MUST usar o driver Ozone com os assets oficiais do pacote `retroarch-assets`, sem tema próprio da distro, com escala de menu e de fonte ajustadas para ficar legível numa tela de 640x480. Nenhum logotipo ou marca registrada de fabricante de console MUST ser adicionado pela distro, nem no menu do RetroArch nem no lume-launcher.

#### Scenario: Aparência do menu
- **WHEN** o menu principal é exibido a 640x480
- **THEN** ele mostra a interface Ozone oficial, com ícones e fontes do RetroArch, e nenhum texto do menu fica cortado

#### Scenario: Sem logotipos no launcher
- **WHEN** os arquivos instalados pelo pacote do lume-launcher são listados
- **THEN** nenhum deles é um logotipo de fabricante de console

### Requirement: Desempenho do menu
O menu do RetroArch MUST rodar sem miniaturas nesta versão. Abrir o menu do RetroArch durante um jogo MUST pausar o jogo. As capas de jogos são mostradas só pelo lume-launcher.

#### Scenario: Menu durante o jogo
- **WHEN** o usuário abre o menu no meio de um jogo
- **THEN** o jogo fica pausado até o menu ser fechado

### Requirement: Atalhos de controle padronizados
O menu do RetroArch MUST abrir em qualquer jogo pela combinação Start + Select. Fn+Start MUST encerrar o jogo e voltar ao launcher. Nenhuma combinação de botões MUST desligar o console.

#### Scenario: Abrir o menu no jogo
- **WHEN** o usuário pressiona Start + Select durante um jogo
- **THEN** o menu do RetroArch abre e o jogo fica pausado

#### Scenario: Sem saída acidental
- **WHEN** o usuário pressiona Start + Select, Fn+Start ou Esc durante um jogo
- **THEN** o console não desliga

#### Scenario: Fn+Start volta ao launcher
- **WHEN** o usuário pressiona Fn+Start durante um jogo do RetroArch
- **THEN** o RetroArch fecha e o launcher reaparece
