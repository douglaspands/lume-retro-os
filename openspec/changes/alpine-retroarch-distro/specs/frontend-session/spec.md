# Spec Delta

## Purpose

Define a sessão do frontend: como ele sobe direto no boot, como pode ser trocado no futuro e o comportamento do frontend inicial (RetroArch com o tema Lume).

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
- **WHEN** o usuário escolhe sair no menu do RetroArch
- **THEN** o sistema grava o que estiver pendente e desliga

### Requirement: Recuperação de falhas do frontend
Se o frontend terminar com erro, o sistema MUST reiniciá-lo. Após 3 falhas em 60 segundos, MUST parar de reiniciar e deixar na tela a mensagem de erro e o caminho do log.

#### Scenario: Falha isolada
- **WHEN** o frontend termina com erro uma vez
- **THEN** ele é reiniciado e volta ao menu

#### Scenario: Falhas repetidas
- **WHEN** o frontend termina com erro 3 vezes em 60 segundos
- **THEN** ele não é mais reiniciado e a tela mostra o erro e onde está o log

### Requirement: RetroArch como frontend inicial
O frontend padrão desta versão MUST ser o RetroArch, com o menu XMB, renderizando direto no vídeo (KMS/DRM) com GLES, com áudio pelo ALSA e controles detectados automaticamente.

#### Scenario: Controle integrado já mapeado
- **WHEN** o RetroArch abre pela primeira vez no console
- **THEN** o controle integrado navega o menu sem nenhuma configuração manual

### Requirement: Tema visual Lume
O menu do RetroArch MUST usar o tema Lume: fundo Aurora em 640x480, fonte Plus Jakarta Sans, ícone redondo colorido com a inicial de cada sistema e ícones de interface no estilo Lucide. Nenhum logotipo ou marca registrada de fabricante de console MUST aparecer.

#### Scenario: Aparência do menu
- **WHEN** o menu principal é exibido
- **THEN** ele mostra o fundo Aurora, a fonte Plus Jakarta Sans e, para cada sistema com jogos, o ícone redondo com a inicial do sistema

### Requirement: Menu enxuto (modo kiosk)
O menu MUST mostrar só os sistemas com jogos, o histórico, os favoritos e um item de configurações. Atualizadores online, importação de conteúdo, netplay, música, vídeo e imagens MUST ficar ocultos.

#### Scenario: Itens ocultos
- **WHEN** o usuário percorre o menu principal
- **THEN** não encontra Online Updater, Core Updater, importação de conteúdo, netplay, música, vídeo nem imagens

### Requirement: Desempenho do menu
O menu MUST rodar sem efeitos animados de fundo, sem sombras e sem miniaturas nesta versão, com o fundo carregado uma única vez. Abrir o menu durante um jogo MUST pausar o jogo.

#### Scenario: Menu durante o jogo
- **WHEN** o usuário abre o menu no meio de um jogo
- **THEN** o jogo fica pausado até o menu ser fechado

### Requirement: Atalhos de controle padronizados
O menu MUST abrir em qualquer jogo pela combinação Select + X. O atalho de sair do RetroArch pelo controle MUST ficar desativado, para evitar desligamento acidental.

#### Scenario: Abrir o menu no jogo
- **WHEN** o usuário pressiona Select + X durante um jogo
- **THEN** o menu do RetroArch abre

#### Scenario: Sem saída acidental
- **WHEN** o usuário pressiona Select + Start durante um jogo
- **THEN** o RetroArch não encerra e o console não desliga
