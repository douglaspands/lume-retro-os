# lume-launcher · candidato 20261114-033157

**Status: candidato** (oficializado em 2026-11-14, substituindo o 20261114-030031). É o protótipo de referência para o que o app real deve fazer. **Não é o app**: o app será em Rust + SDL2 e ainda não foi iniciado.

Abrir: `index.html` no navegador. Gerar os dados da coleção: `node tools/build-catalog.js <pasta-das-roms>`. Conferir as traduções: `node tools/check-i18n.js`.

## O que o candidato inclui
- **Dock** sem pontinhos, com ícones de console (logos de marca chapados), rotação infinita e **ampliação estilo macOS** (foco 10,8em, vizinhos 8,1em, 2º vizinho 5,1em, 5 ícones inteiros na tela). Favoritos no início e Configurações por último.
- **Lista de jogos** com capas reais, **busca por nome** com teclado na tela, **L1/R1** com salto proporcional que acelera e selo ⚙ nos jogos com opção própria.
- **Menu do jogo**: Iniciar, Iniciar de um save state (por core), Emulador/core, Aspecto (do core ou 4:3), Shader (só core do RetroArch) e Favoritos, com a capa em destaque.
- **Emulador/aspecto/shader em 3 camadas**: jogo → console (tecla Y) → padrão do sistema.
- **Configurações**: Wi-Fi e Bluetooth (só com dongle), Idioma, **Tema**, **Modo lite**, Volume, Brilho, Sistema (CPU e memória ao selecionar) e Desligar o aparelho com confirmação.
- **Arquivos** (abre imagens e .txt) e **Capturas** do RetroArch.
- **Rodapé**: botões de letra (A, B, X, Y) na cor de destaque do tema; setas (◀▶ ▲▼) em chip tonal do tema, sem inverter.
- **3 idiomas** (pt-BR, en, es) com chaves conferidas por script, **2 temas** (Material 3 escuro e claro) e **layout responsivo** a qualquer tela.

## O que foi verificado
No navegador, com os dados reais da coleção: Dock (medido: tamanhos dos ícones e posição dentro da tela), grade, menu do jogo, opções por console e por jogo, save states por core, busca, salto do L1/R1, Arquivos e leitor de .txt, Capturas, Configurações (em espanhol), troca de tema, rodapé nos dois temas e layout em 640x480, 854x480 e 720x720.

## Alterações depois da oficialização
- **Modo lite** passou a ser um item das Configurações (Ligado/Desligado), no lugar da caixa "Forçar modo lite" da barra do protótipo. Verificado: ligado, a transição vai a 0s; desligado, volta a 0,2s; a escolha é salva.
- **Correção:** o modo lite não desligava as animações, porque os valores do tema (em estilo inline) venciam a regra do CSS. Agora o motor fixa `--t` em 0s e `--blur` em nenhum quando o lite está ativo.
- Nos 2 temas Material o efeito visível do lite é pequeno (animações desligadas), pois já são opacos e sem desfoque.
- Estas mudanças foram feitas **na própria pasta do candidato** a pedido do usuário. A tag `lume-launcher-rc-20261114-033157` foi movida para o commit que as inclui (a tag antes apontava para o commit `841e0ca`).

## Pendências e limites conhecidos
**Não verificado no aparelho (nada foi rodado no R36S):**
- Consumo de memória e CPU, que é o requisito principal. O navegador não representa o R36S; as metas em [Orçamento de performance](orcamento-de-performance.md) seguem sem medição.
- Mapeamento real do gamepad: X (`buttons[2]`), Y (`[3]`), L1/R1 (`[4]` e `[5]`).
- Como o dArkOS guarda emulador/core por jogo e como o runner abre o jogo já com core, aspecto, shader e save state.

**Suposições nos dados:**
- Alternativas de core marcadas com `*` em `src/data.js` são prováveis, não confirmadas. Só os cores vistos nos `savestates/` são confirmados.
- Saves soltos na raiz de `savestates/<sistema>/` são tratados como do core padrão.
- Os save states "de demonstração" são inventados (caixa na barra do protótipo).
- A lista de shaders é de exemplo.

**Qualidade dos dados da coleção:** 186 capas não são imagem (180 no SNES) e usam uma caixa gerada.

**Não conferido visualmente:** a opção "Janela (responsivo)" da barra; o tema claro em todas as telas; o rodapé em Arquivos, Capturas e no teclado de busca (usam o mesmo componente, mas não olhei cada um).

**Detalhes visuais:** o texto "Iniciar de um save state" é cortado quando a linha mostra "N em outro core". Com a ampliação maior, os 5 ícones do Dock ficam a 0,4em das bordas.

**Licença:** os logos são de marcas registradas, copiados de um tema de EmulationStation. Servem só para uso pessoal e não estão no repositório (`assets/logos/` fica no `.gitignore`; sem eles o Dock usa a sigla).

**Só do protótipo:** `catalog.js`, `fs.js` e `assets/logos/` são gerados por `tools/build-catalog.js`; `fs.js` é um índice, e no app real isso vira um `readdir` sob demanda.
