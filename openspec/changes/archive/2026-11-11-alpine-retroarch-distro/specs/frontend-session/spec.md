# Spec Delta

## Purpose

Define a sessão do frontend: como ele sobe direto no boot, como pode ser trocado no futuro e o comportamento do frontend inicial (RetroArch com o menu Ozone padrão).

## ADDED Requirements

### Requirement: Frontend sobe direto, sem login
Ao fim do boot, o sistema MUST iniciar o frontend configurado em tela cheia, sem login, sem servidor gráfico (X11 ou Wayland) e com um usuário sem privilégios de administrador.

#### Scenario: Ligar e jogar
- **WHEN** o console é ligado com a partição de jogos já criada
- **THEN** o frontend aparece em tela cheia sem nenhuma interação do usuário

#### Scenario: Sem privilégios
- **WHEN** o processo do frontend é inspecionado
- **THEN** ele roda com um usuário comum, que não é root

### Requirement: Frontend substituível
O frontend MUST ser escolhido por uma única configuração do serviço de sessão. Trocar de frontend MUST exigir apenas instalar outro pacote e mudar essa configuração, sem mexer no contrato de jogos.

#### Scenario: Troca de frontend
- **WHEN** a configuração do serviço de sessão aponta para outro frontend instalado
- **THEN** no boot seguinte esse frontend sobe no lugar do RetroArch, com as mesmas pastas de jogos, saves e estados

### Requirement: Sair desliga o console
Quando o frontend encerrar normalmente por ação do usuário, o sistema MUST desligar o aparelho.

#### Scenario: Sair pelo menu
- **WHEN** o usuário escolhe "Desligar" (o item de sair do RetroArch) no menu e o escolhe de novo em até 3 segundos, confirmando
- **THEN** o sistema grava o que estiver pendente e desliga

#### Scenario: Desligar pede confirmação por padrão
- **WHEN** o usuário escolhe "Desligar" no menu uma única vez
- **THEN** o menu só mostra "Pressione novamente para desligar..." e o aparelho continua ligado

### Requirement: Recuperação de falhas do frontend
Se o frontend terminar com erro, o sistema MUST reiniciá-lo. Após 3 falhas em 60 segundos, MUST parar de reiniciar e deixar na tela a mensagem de erro e o caminho do log.

#### Scenario: Falha isolada
- **WHEN** o frontend termina com erro uma vez
- **THEN** ele é reiniciado e volta ao menu

#### Scenario: Falhas repetidas
- **WHEN** o frontend termina com erro 3 vezes em 60 segundos
- **THEN** ele não é mais reiniciado e a tela mostra o erro e onde está o log

### Requirement: RetroArch como frontend inicial
O frontend padrão desta versão MUST ser o RetroArch, com o menu Ozone (driver oficial do RetroArch), renderizando direto no vídeo (KMS/DRM) com GLES, com áudio pelo ALSA e controles detectados automaticamente.

#### Scenario: Controle integrado já mapeado
- **WHEN** o RetroArch abre pela primeira vez no console
- **THEN** o controle integrado navega o menu sem nenhuma configuração manual

### Requirement: Menu padrão do RetroArch (Ozone)
O menu do RetroArch MUST usar o driver Ozone com os assets oficiais do pacote `retroarch-assets`, sem tema próprio da distro, com escala de menu e de fonte ajustadas para ficar legível numa tela de 640x480. Nenhum logotipo ou marca registrada de fabricante de console MUST ser adicionado pela distro.

#### Scenario: Aparência do menu
- **WHEN** o menu principal é exibido a 640x480
- **THEN** ele mostra a interface Ozone oficial, com ícones e fontes do RetroArch, e nenhum texto do menu fica cortado

### Requirement: Menu completo (sem modo kiosk)
O menu MUST exibir as abas e opções padrão do RetroArch (carregar conteúdo, carregar core, importação de conteúdo, atualizador online, abas de mídia e configurações avançadas). O Core Updater MUST ficar oculto, porque os cores do atualizador online são compilados para glibc e não rodam no Alpine (musl).

#### Scenario: Itens disponíveis no menu completo
- **WHEN** o usuário percorre o menu principal
- **THEN** encontra o atualizador online, a importação de conteúdo, o netplay e as configurações de drivers e diretórios

#### Scenario: Sem Core Updater
- **WHEN** o usuário abre o atualizador online
- **THEN** não encontra a opção de baixar cores

### Requirement: Desempenho do menu
O menu MUST rodar sem miniaturas nesta versão. Abrir o menu durante um jogo MUST pausar o jogo.

#### Scenario: Menu durante o jogo
- **WHEN** o usuário abre o menu no meio de um jogo
- **THEN** o jogo fica pausado até o menu ser fechado

### Requirement: Atalhos de controle padronizados
O menu MUST abrir em qualquer jogo pela combinação Start + Select. Nenhuma combinação de botões MUST encerrar o RetroArch, para evitar desligamento acidental.

#### Scenario: Abrir o menu no jogo
- **WHEN** o usuário pressiona Start + Select durante um jogo
- **THEN** o menu do RetroArch abre e o jogo fica pausado

#### Scenario: Sem saída acidental
- **WHEN** o usuário pressiona Start + Select ou Esc durante um jogo
- **THEN** o RetroArch não encerra e o console não desliga
