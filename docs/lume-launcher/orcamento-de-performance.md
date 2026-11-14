# Orçamento de performance

> Metas iniciais. **São chutes até medirmos no clone mais fraco.** Ajustar depois da linha de base.

## Metas
| Métrica | Meta |
| :--- | :--- |
| RAM residente (RSS) | bem abaixo da do ES (definir o número depois da medição) |
| CPU parado (sem input) | ~0% |
| Tempo até a primeira tela | < 1 s |
| Fluidez na navegação | 30 fps estáveis, sem quedas ao rolar listas |
| Tamanho do binário + tema padrão | poucos MB |

## Técnicas
- **Renderização por evento**: só redesenha quando há input ou animação. Parado, o processo dorme.
- **Teto de 30 fps** (ou menos no modo econômico).
- **Texto em cache**: glifos e linhas já renderizados viram textura reaproveitada.
- **Imagens pré-escaladas** para a resolução da tela, nunca escalar em tempo real. Uma ferramenta de build do tema faz isso.
- **Carregamento preguiçoso com cache LRU** para capas: só o que está visível mais um vizinho.
- **Índice de ROMs em cache** (arquivo binário ou SQLite) para não varrer o SD a cada abertura.
- **Sem runtime de script** e sem VM no caminho de renderização.
- **Níveis de tema** (lite/normal): o tema declara o que é opcional (capas, animações) e o launcher desliga conforme o aparelho.

## Memória (prioridade máxima)
- **Cache de texturas com teto fixo em bytes**, independente do número de jogos.
- **Sem processos residentes** além do próprio launcher; Wi-Fi, Bluetooth e demais ajustes chamam ferramentas do sistema sob demanda ([Configurações](configuracoes.md)).
- **Sem runtime de script nem VM**, que são memória fixa.
- O menu Sistema mostra o RSS do launcher, para medirmos continuamente.
- Definir o número da meta de RSS depois da linha de base do ES.

## Como medir
1. Linha de base: RAM e CPU do ES no clone mais fraco (`free -m`, `top`).
2. Mesmas medidas com o launcher em cada tela.
3. Registrar aqui os números por aparelho.

| Aparelho | SoC | RAM | ES (RAM/CPU) | Launcher (RAM/CPU) |
| :--- | :--- | :--- | :--- | :--- |
| _(preencher)_ | | | | |

Voltar: [Visão geral](visao-geral.md)
