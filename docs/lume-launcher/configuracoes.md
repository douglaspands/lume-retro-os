# Configurações do aparelho

> Requisitos do usuário, 2026-11-14. Parte do [Design das telas](design-das-telas.md) (último item do Dock).
> O que o dArkOS oferece de fato **não foi verificado**; a lista abaixo é o alvo, e a coluna "Como" é hipótese até checar no aparelho.

## Menus

| Menu | Aparece quando | Como (hipótese a verificar) |
| :--- | :--- | :--- |
| **Wi-Fi** | Há adaptador Wi-Fi presente (dongle USB plugado) | Detectar interface em `/sys/class/net`; listar e conectar chamando a ferramenta de rede que o dArkOS já usa |
| **Bluetooth** | Há adaptador Bluetooth presente (dongle) | Detectar via `/sys/class/bluetooth` ou `rfkill`; parear chamando a ferramenta do sistema |
| **Idioma** | Sempre | Idioma do próprio launcher (arquivos de tradução leves); ver nota abaixo |
| **Volume** | Sempre | Mixer ALSA |
| **Brilho** | Sempre | Backlight em `/sys/class/backlight` |
| **Sistema** (especificações) | Sempre | Ver seção abaixo |
| Mais, se existirem no dArkOS | | Ver "Candidatos" |

Wi-Fi e Bluetooth **somem do menu** quando não há dongle, em vez de aparecerem desativados.

## Menu Sistema (especificações e consumo)
Informações lidas de `/proc` e `/sys`, que são baratas:
- **Modelo, SoC e arquitetura**: `/proc/cpuinfo`, `uname`
- **CPU**: núcleos, frequência atual e máxima, uso (de `/proc/stat`), temperatura se houver sensor
- **Memória**: total, usada e livre (`/proc/meminfo`)
- **Consumo do próprio launcher**: RSS lido de `/proc/self/status`, para mostrar quanto ele gasta
- **Armazenamento**: espaço do cartão SD
- **Bateria**: nível e se está carregando
- **Rede**: IP, se conectado

**Regra de custo**: as estatísticas aparecem ao apenas **selecionar** o item Sistema, sem apertar A. O launcher só lê e atualiza (a cada ~1 s) enquanto esse item está selecionado; ao sair dele, para de ler.

## Candidatos a "mais configurações úteis"
Só entram se o dArkOS já tiver o recurso (a verificar):
- [ ] Hora, data e fuso
- [ ] Saída de áudio
- [x] Desligar o aparelho, com confirmação (Cancelar é a opção padrão). Não há "desligar tela"
- [ ] Mapeamento e teste de controles
- [ ] Reiniciar e desligar
- [ ] Informações de versão do dArkOS
- [ ] Atualização

## Tema
Item **Tema** na lista, com os 2 temas Material 3 (Escuro e Claro). ◀▶ troca na hora e a escolha fica salva. Ver [Protótipos](prototipos.md).

## Modo lite
Item **Modo lite** (Ligado/Desligado) na lista, logo depois de Tema. Desliga animações, desfoque e fundos translúcidos, para aparelhos fracos. Nos 2 temas Material, que já são opacos e sem desfoque, o efeito visível é basicamente a animação desligada. Ver [Orçamento de performance](orcamento-de-performance.md).

## Idioma
Tradução do próprio launcher, com arquivos de texto simples por idioma (por exemplo `pt-BR`, `en`), carregados na hora. Não é o idioma do sistema operacional, que continua sendo do dArkOS. Fontes precisam cobrir os caracteres dos idiomas suportados.

## Consumo de memória (requisito forte)
Detalhes de metas em [Orçamento de performance](orcamento-de-performance.md). Para esta tela:
- **Sem processo residente** para Wi-Fi ou Bluetooth. O launcher chama as ferramentas do sistema quando o usuário abre o menu e não guarda estado.
- **Telas de configuração são leves**: texto e barras, sem imagens grandes.
- **Cache de texturas com limite fixo em bytes**, para a RAM não crescer com o número de jogos.
- **Dados lidos de `/proc` e `/sys`** não ficam em memória; mostra e descarta.
- O menu Sistema exibe o RSS do launcher, o que também serve como medidor para nós.

## A verificar no aparelho
- [ ] Qual ferramenta o dArkOS usa para Wi-Fi e Bluetooth
- [ ] Caminhos de volume e brilho (variam entre clones)
- [ ] Quais ajustes o menu de configurações do ES do dArkOS tem hoje
- [ ] Como o launcher roda com permissão para esses ajustes (root ou usuário)

Voltar: [Visão geral](visao-geral.md)
