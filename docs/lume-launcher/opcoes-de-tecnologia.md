# Opções de tecnologia

Critério principal: **baixo consumo** em clones fracos. Ver [Orçamento de performance](orcamento-de-performance.md).

| Opção | RAM/CPU | Dependências no aparelho | Veredito |
| :--- | :--- | :--- | :--- |
| **Rust + SDL2** | Baixo, sem GC | Só SDL2 (binário estático ou linkado) | **Recomendada** |
| **C + SDL2** | O mais baixo possível | Só SDL2 | Alternativa; mais trabalho e menos segurança de memória |
| LÖVE (Lua) | Médio, tem VM e runtime | Runtime LÖVE | Aceitável, mas gasta mais que nativo |
| Python + pygame | Alto no arranque e na memória | Python + pygame | Só para protótipo no PC, não para o aparelho |
| Tema do ES (XML) | O do ES | Nenhuma | Não resolve o requisito |
| Go | GC e binário maior | Nenhuma | Possível, mas sem vantagem sobre Rust aqui |

## Recomendação
**Rust + SDL2**, compilado para o alvo do aparelho (cross-compile). Binário único, sem runtime de script, sem GC, partida rápida.
O motor de tema é declarativo (dados, não código), para ser versátil sem pagar o custo de uma VM de script. Ver [Formato de tema](formato-de-tema.md).

## Pendências
- A versão do SDL2 e o driver de vídeo disponíveis no dArkOS
- Cross-compile: alvo `aarch64-unknown-linux-gnu` primeiro; confirmar se algum clone é 32 bits
- Desenvolvimento no PC com janela do tamanho da tela e o mesmo código

## Qt e GTK: não valem a pena aqui
- **Memória fixa alta**: Qt/QML e GTK carregam bibliotecas grandes e um motor de UI próprio, o que contraria o requisito de consumo mínimo. (Estimativa minha; medir antes de afirmar números.)
- **Dependências**: bibliotecas grandes que o dArkOS provavelmente não traz, e que teríamos de empacotar para cada clone.
- **Vídeo**: Qt precisa de backend gráfico adequado (EGLFS, sem X11) e GTK espera um servidor gráfico (X11/Wayland). Em handhelds sem desktop isso é fonte de problemas. O Pegasus, feito em Qt/QML, tem relatos de pico de GPU com efeito de blur e de carga pesada de capas ao rolar em máquina de 2 GB.
- **SDL2** já é a base do ES e dos emuladores, então é o caminho natural e o mais leve.

## Existe algo pronto parecido? (pesquisa de 2026-11-14)
Nenhum achado tem o Dock horizontal infinito com Favoritos e Configurações no anel.

| Projeto | Stack | Serve como |
| :--- | :--- | :--- |
| [MinUI](https://github.com/nchapman/MinUI) | C + SDL | Referência de UX e de código enxuto; sem temas |
| [mehstation](https://github.com/remeh/mehstation) | C + SDL2 + glib + ffmpeg + SQLite | Referência de estrutura; dependências mais pesadas que o necessário |
| [PortMaster GUI](https://gh.hhj520.top/PortsMaster/PortMaster-GUI) | Python + SDL2 | Referência de sistema de temas em handheld |
| Pegasus Frontend | C++ + Qt/QML | Referência de tema flexível, mas pesado para o nosso requisito |

Referência de nome só, sem pesquisa: o menu **XMB do RetroArch** tem uma barra horizontal de ícones por console, parecida com o Dock. Vale olhar o visual, não reaproveitar.

Voltar: [Visão geral](visao-geral.md)
