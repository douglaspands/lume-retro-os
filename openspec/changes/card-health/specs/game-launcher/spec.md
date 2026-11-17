# Spec Delta

## MODIFIED Requirements

### Requirement: Configurações do aparelho
O item Configurações MUST oferecer Idioma, Tema, Tela (por enquanto, mostrar ou não o percentual da bateria; ligado de fábrica), Volume, Brilho, Sistema, Cartão, Games (com Atualizar listas, uma ação do painel que A executa), RetroArch e Desligar, numa lista à esquerda, com o painel do item em foco à direita (pouco mais da metade da tela) mostrando o valor, o nível ou o que o item faz, e onde os valores são mudados. A lista MUST dar a volta: para baixo no último item vai ao primeiro, para cima no primeiro vai ao último. Wi-Fi e Bluetooth MUST aparecer só quando houver adaptador presente. As escolhas MUST sobreviver ao reboot.

#### Scenario: Lista que dá a volta
- **WHEN** o foco está em Desligar, o último item, e o usuário aperta para baixo
- **THEN** o foco vai para o primeiro item

#### Scenario: Sem dongle
- **WHEN** nenhum adaptador Wi-Fi está conectado
- **THEN** o item Wi-Fi não aparece

#### Scenario: Menu do RetroArch
- **WHEN** o usuário escolhe o item RetroArch
- **THEN** o menu completo do RetroArch abre sem jogo e, ao sair dele, o launcher reaparece nas Configurações

#### Scenario: Painel do Cartão
- **WHEN** o usuário põe o foco no item Cartão e entra no painel
- **THEN** vê o espaço livre, a última otimização e a última verificação pelo número do boot, e as ações "Otimizar agora" e "Verificar no próximo boot", que A executa
