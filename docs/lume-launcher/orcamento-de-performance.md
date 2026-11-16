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

A linha de base é o menu do RetroArch, o frontend anterior do projeto (o ES nunca rodou
nele). Medidas pelo `/proc/<pid>/stat` e `status` em 60 s, parado, sem input, e conferidas
nas métricas do `logd` (colunas `lume_*` e `input_*`).

| Aparelho | SoC | RAM | Menu do RetroArch (RSS/CPU) | Launcher (RSS/CPU) |
| :--- | :--- | :--- | :--- | :--- |
| GA36-MB V1.2 (build 20261114-143705) | A33, 4× Cortex-A7, Mali-400 (`lima`) | 512 MB | 79 MB / 73% de um núcleo | `lume-ui` 59 MB / 0,1% de um núcleo |

Durante um jogo (NES, fceumm, 60 fps) só ficam o `lume-run` (696 KB, 0% de CPU) e o
`r36os-input` (500 KB, 0% de CPU); o `lume-ui` sai e devolve a memória ao jogo.

Tempos no mesmo aparelho: do fim do jogo até a grade de volta, 0,80–0,93 s (meta de 1 s); do
aperto de Fn+Start até a grade, 1,70–1,78 s, com 0,85–0,90 s gastos pelo RetroArch para
fechar.

RSS do `lume-ui` por mapeamento (`/proc/<pid>/smaps`, 58 MB no total): `libLLVM` 26,5 MB,
memória anônima 17,5 MB, `libgallium` 8 MB, `libstdc++` 1,3 MB, o binário 1,1 MB, SDL2 1 MB.
Mais da metade é o Mesa (risco previsto na tarefa 2.1 do change): páginas de arquivo, que o
RetroArch também usa, e o `lima` nem precisa do LLVM, que vem com o llvmpipe do Mesa do Alpine
(pendência P-59).

Voltar: [Visão geral](visao-geral.md)
