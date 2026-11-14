# Decisão: refatorar o do dArkOS ou criar do zero

> Revisada em 2026-11-14 depois de o requisito principal ficar claro: **baixo consumo de recursos em clones fracos do R36S**, com **tema versátil**. Ver [Orçamento de performance](orcamento-de-performance.md).

## Decisão: criar do zero, com motor de tema próprio

Refatorar o tema do dArkOS não resolve o problema, porque o custo de performance está no **ES (fork em C++) e no motor de tema dele**, não no conteúdo do XML. Mudar o XML muda o visual, não o consumo base. Além disso:
- O formato de tema do ES é o que o fork aceita, então a versatilidade é limitada por ele.
- O ES tende a carregar muita coisa (listas, metadados, vídeos e imagens), e em clones com pouca RAM isso pesa. (Não medi no aparelho; ver verificações abaixo.)

## Comparação

| Critério | Tema do ES (refatorar) | Launcher próprio + tema próprio |
| :--- | :--- | :--- |
| Consumo de RAM/CPU | Herda o do ES | Controlado por nós, só o que usamos |
| Versatilidade de tema | Limitada pelo formato do fork | Formato desenhado para o nosso caso |
| Clones com telas e resoluções diferentes | Cada tema precisa tratar | Layout independente de resolução desde o início |
| Esforço inicial | Baixo | Médio/alto |
| Integração | Total com o ES | Via Ports; ES continua existindo |
| Manutenção | Segue o upstream | Só nossa |

## Riscos da decisão e mitigação
- **Esforço alto.** Mitigar com o [Escopo v1](escopo-v1.md) enxuto: lista de sistemas, lista de jogos, abrir e voltar.
- **Clones com arquiteturas ou resoluções diferentes.** Verificar nos aparelhos reais antes de fixar o alvo (ver abaixo).
- **Ficar sem recursos do ES** (scraping, capas, metadados). Ler o `gamelist.xml` que o ES já gera, em vez de reimplementar.

## A verificar (bloqueia o alvo de build)
- [ ] Arquitetura e SoC de cada clone que você quer suportar (`uname -m`, `/proc/cpuinfo`)
- [ ] RAM total e livre com o ES rodando (`free -m`), no clone mais fraco
- [ ] Resoluções das telas dos clones
- [ ] RAM e CPU que o ES consome hoje nesse clone, para ter a linha de base
- [ ] Se SDL2 (e qual driver de vídeo: KMSDRM, fbdev) vem no dArkOS

Voltar: [Visão geral](visao-geral.md)
