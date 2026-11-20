# Aprendizado: qual core roda melhor cada placa

Registro vivo do que as medições ensinaram sobre a escolha de core por **placa de hardware**
(família), para explorar no futuro (pedido do usuário, 2026-11-20). Nada aqui nomeia jogo nem
caminho: o resultado por jogo fica só nos arquivos privados, fora do git
(`out/tuning/<console>-cores.jsonl` e o mapa de famílias `var/roms_test/families.toml`). Os
números completos estão na seção de cores de [`ga36.md`](ga36.md) (e de `r36s.md`, quando
medido).

## Como se mede

`tests/device/tuning_ab.py` com um plano de comparação de cores (`tests/device/tuning/*.toml`,
variantes `core = "..."`): cada jogo roda no core padrão da pasta (A1), em cada core alternativo
(B, pela opção por jogo do launcher, devolvida depois) e de novo no padrão (A2), 30 s de
aquecimento e 60 s de medição. Conta: se abre, velocidade do core (≥ 99% é cheia), quadros
mostrados por segundo, clock médio escolhido pelo governor (menor = menos bateria),
temperatura e falhas de som. O vencedor de um jogo é o de menor clock entre os de velocidade
cheia; sem nenhum de velocidade cheia, o mais rápido.

## GA36 (Allwinner A33, Cortex-A7 a 1008 MHz, armv7) — 2026-11-20

Um jogo por placa no arcade e três por sistema em CPS-1, CPS-2 e Neo Geo: amostra pequena, a
confirmar com mais jogos da mesma placa.

| Placa | Melhor core | Observação |
|---|---|---|
| Sega System 16B | FB Alpha 2012 | 100%; FBNeo 63%; os MAME não abrem o romset do FBNeo |
| Data East (16 bits) | FBNeo | o único que abre; 65% |
| Irem M72 | FB Alpha 2012 | 90%; FBNeo 80% |
| Irem M84 | MAME 2000 | 100% a 720 MHz; MAME 2003-Plus 100% a 1008 MHz |
| Irem M92 | MAME 2003-Plus | 83%; FBNeo 49%, FB Alpha 2012 62% |
| Konami (TMNT, TMNT2, X-Men) | MAME 2003-Plus | 100% nos três; FBNeo 66% a 100% |
| Capcom CPS-1 | recorte `fbalpha2012_cps1` ou FB Alpha 2012 completo | 100% nos dois, 720 a 816 MHz; FBNeo precisa de 1008 MHz |
| Capcom CPS-2 | recorte `fbalpha2012_cps2` | 100% a 720–816 MHz; o completo 816 MHz; FBNeo 912–1008 MHz |
| SNK Neo Geo | recorte ou FB Alpha 2012 completo | 100% a ~816 MHz nos dois; FBNeo 1008 MHz |

**Padrões que apareceram:**
- O FBNeo é o mais pesado em todas as placas do GA36 (mais fiel, mais CPU).
- O MAME 2003-Plus vai melhor nas placas Konami e nas Irem mais pesadas, mas abre poucos
  romsets do FBNeo (versões diferentes).
- O FB Alpha 2012 é o melhor equilíbrio: abre quase tudo do FBNeo das placas antigas e roda bem
  mais leve.
- O MAME 2000 é o mais econômico onde abre, mas abre pouco.
- As flags do processador (`_lume`) não mudaram os cores de arcade (o FBNeo `_lume` ficou ~1,5
  ponto mais lento); ver [`ga36.md`](ga36.md).
- O FBNeo pesado a 1008 MHz travou o GA36 duas vezes (P-115).

## R36S (Rockchip RK3326, Cortex-A35, aarch64)

A medir na J2. Hipótese: mais rápido por núcleo, a escolha pode mudar (menos placas no limite; o
critério passa a ser o clock).

## Perguntas em aberto

- A mesma placa se comporta igual com outros jogos? (medir 3+ jogos por placa)
- Um core por placa resolve, ou há jogos da mesma placa que pedem cores diferentes?
- Dá para o próprio console descobrir o melhor core de um jogo (P-116)?
- Os romsets do usuário são do FBNeo: quanto da escolha é limitado pela versão do romset, e não
  pela velocidade do core?
