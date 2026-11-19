# frontend-session Specification

## Purpose

Define a sessão do frontend: como ele sobe direto no boot, como pode ser trocado no futuro e o comportamento do frontend inicial (RetroArch com o menu Ozone padrão).

## Requirements

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

### Requirement: Recuperação de falhas do frontend
Se o frontend terminar com erro, o sistema MUST reiniciá-lo. Após 3 falhas em 60 segundos, MUST parar de reiniciar e deixar na tela a mensagem de erro e o caminho do log.

#### Scenario: Falha isolada
- **WHEN** o frontend termina com erro uma vez
- **THEN** ele é reiniciado e volta ao menu

#### Scenario: Falhas repetidas
- **WHEN** o frontend termina com erro 3 vezes em 60 segundos
- **THEN** ele não é mais reiniciado e a tela mostra o erro e onde está o log

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

### Requirement: Menu completo (sem modo kiosk)
O menu MUST exibir as abas e opções padrão do RetroArch (carregar conteúdo, carregar core, importação de conteúdo, atualizador online, abas de mídia e configurações avançadas). O Core Updater MUST ficar oculto, porque os cores do atualizador online são compilados para glibc e não rodam no Alpine (musl).

#### Scenario: Itens disponíveis no menu completo
- **WHEN** o usuário percorre o menu principal
- **THEN** encontra o atualizador online, a importação de conteúdo, o netplay e as configurações de drivers e diretórios

#### Scenario: Sem Core Updater
- **WHEN** o usuário abre o atualizador online
- **THEN** não encontra a opção de baixar cores

### Requirement: Desempenho do menu
O menu do RetroArch MUST rodar sem miniaturas nesta versão. Abrir o menu do RetroArch durante um jogo MUST pausar o jogo. As capas de jogos são mostradas só pelo lume-launcher.

#### Scenario: Menu durante o jogo
- **WHEN** o usuário abre o menu no meio de um jogo
- **THEN** o jogo fica pausado até o menu ser fechado

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

### Requirement: Configuração do RetroArch compartilhada entre consoles
A configuração do RetroArch persistida na `ROMS` MUST servir aos dois consoles. As chaves que dependem do aparelho MUST ser reaplicadas pelo console a cada início do frontend, de modo que um valor gravado num console nunca valha no outro. Toda chave fixada para um console MUST ter também um valor fixado para o outro.

#### Scenario: Taxa de atualização por console
- **WHEN** o RetroArch inicia no GA36, grava a configuração na `ROMS` e o cartão vai para o R36S
- **THEN** no R36S o `video_refresh_rate` em uso é o do painel do R36S, e ao voltar para o GA36 é de novo o do painel do GA36

#### Scenario: Escolhas do usuário passam entre consoles
- **WHEN** o usuário muda no GA36 uma opção que não depende do aparelho (o idioma do menu, por exemplo) e leva o cartão ao R36S
- **THEN** o R36S abre com a mesma escolha

#### Scenario: Chave fixada em só um console
- **WHEN** os arquivos de chaves fixas por console são conferidos pelos testes
- **THEN** o teste falha se uma chave estiver fixada para um console e não para o outro

### Requirement: Reiniciar pelo frontend
O contrato de sessão MUST ter um fim de frontend que pede reinício, distinto do fim normal que desliga e dos fins com erro. Pedido o reinício, o sistema MUST gravar o pendente e reiniciar o aparelho, sem contar como falha do frontend. Um frontend que não usa esse fim MUST continuar funcionando como antes.

#### Scenario: Reiniciar pelo launcher
- **WHEN** o usuário escolhe Reiniciar no menu do sistema do launcher e confirma
- **THEN** o sistema grava o que estiver pendente, reinicia, e o `events.log` registra o reinício pedido pelo usuário, não uma falha

#### Scenario: RetroArch como frontend
- **WHEN** o frontend configurado é o RetroArch e o usuário sai pelo menu dele
- **THEN** o aparelho desliga, como antes
