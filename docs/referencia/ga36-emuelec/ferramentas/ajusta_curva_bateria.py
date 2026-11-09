"""Gera a curva de bateria (r36-bateria-curva.conf) a partir de um ciclo do r36-thermal.csv.

Uso: uv run python -I tools/ajusta_curva_bateria.py [--desde <boot>] [--aceita-relativo]
         [--r-mohm R] [--filtro N] [--v-zero mV] [--v-um mV] [-o r36-bateria-curva.conf]
         r36-thermal.1.csv r36-thermal.csv

Usa o ciclo escolhido por --desde (o último, se omitido) e a mesma integração de corrente de
analisa_bateria.py como carga restante de referência. Para cada resistência R de 0 a 400 mohm
(passo de 10), filtra a tensão compensada V + R * I como o aparelho faz, ajusta uma curva de
percentual que nunca diminui com a tensão (regressão isotônica, PAV) e fica com o R de menor erro
médio (ou usa o de --r-mohm); depois reduz a curva a cerca de 12 pontos e escreve o arquivo no formato que o
feature 48-bateria-percentual aceita na raiz da p1. Um ciclo que não termina em desligamento só
tem referência relativa: o arquivo exige --aceita-relativo.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import analisa_bateria as ab  # noqa: E402

PONTOS = 12
R_MAX = 400
R_PASSO = 10
PADRAO = {"filtro": 4, "v_zero": 3450, "v_um": 3500}


def amostras(pontos, total_mah):
    """[(boot, mv, ma, ref)] das linhas com tensão e corrente."""
    return [(p["boot"], p["mv"], p["ma"], ab.referencia(p, total_mah))
            for p in pontos if p["mv"] is not None and p["ma"] is not None]


def compensadas(amos, r_mohm, filtro):
    """Tensão compensada V + R * I já filtrada, reiniciando o filtro a cada boot."""
    xs = []
    boot = f = None
    for b, mv, ma, _ in amos:
        vc = mv + r_mohm * ma / 1000
        f = vc if b != boot or f is None else f + (vc - f) / filtro
        boot = b
        xs.append(f)
    return xs


def pav(pares):
    """Regressão isotônica (não decrescente) de [(x, y)]: blocos (x médio, y médio, n)."""
    blocos = []
    for x, y in sorted(pares):
        blocos.append([x, y, 1])
        while len(blocos) > 1 and blocos[-2][1] / blocos[-2][2] > blocos[-1][1] / blocos[-1][2]:
            b = blocos.pop()
            blocos[-1] = [blocos[-1][0] + b[0], blocos[-1][1] + b[1], blocos[-1][2] + b[2]]
    return [(sx / n, sy / n, n) for sx, sy, n in blocos]


def interpola(pontos, x):
    """Percentual da curva em x (lista de (mV, %) crescente), cortado nas pontas, como no aparelho."""
    if x <= pontos[0][0]:
        return pontos[0][1]
    if x >= pontos[-1][0]:
        return pontos[-1][1]
    for (x0, y0), (x1, y1) in zip(pontos, pontos[1:]):
        if x <= x1:
            return y0 + (x - x0) * (y1 - y0) / (x1 - x0)
    return pontos[-1][1]


def reduz(blocos, alvo):
    """Tira, um a um, o ponto interior cuja ausência menos desvia a curva, até sobrar `alvo`."""
    pts = [(x, y) for x, y, _ in blocos]
    pesos = [n for _, _, n in blocos]
    while len(pts) > alvo:
        melhor = None
        for i in range(1, len(pts) - 1):
            (xa, ya), (xb, yb) = pts[i - 1], pts[i + 1]
            desvio = abs(pts[i][1] - (ya + (pts[i][0] - xa) * (yb - ya) / (xb - xa)))
            custo = desvio * (xb - xa) * pesos[i]
            if melhor is None or custo < melhor[0]:
                melhor = (custo, i)
        _, i = melhor
        pesos[i - 1] += pesos[i]
        del pts[i], pesos[i]
    return pts


def inteira(pts):
    """Pontos inteiros: mV estritamente crescente e % que não diminui, entre 0 e 100."""
    saida = []
    for x, y in pts:
        x, y = round(x), min(100, max(0, round(y)))
        if saida and x <= saida[-1][0]:
            continue
        saida.append((x, max(y, saida[-1][1]) if saida else y))
    return saida


def erro_da_curva(xs, amos, pontos):
    es = [abs(int(interpola(pontos, x) + 0.5) - ref) for x, (_, _, _, ref) in zip(xs, amos)]
    return sum(es) / len(es), max(es)


def ajusta(amos, filtro, r_fixo=None):
    """(r_mohm, pontos, erro médio, erro máximo) do R de menor erro médio (ou do R fixo)."""
    melhor = None
    for r in [r_fixo] if r_fixo is not None else range(0, R_MAX + 1, R_PASSO):
        xs = compensadas(amos, r, filtro)
        blocos = pav([(x, a[3]) for x, a in zip(xs, amos)])
        pts = inteira(reduz(blocos, PONTOS))
        if len(pts) < 2:
            continue
        medio, maximo = erro_da_curva(xs, amos, pts)
        if melhor is None or medio < melhor[2]:
            melhor = (r, pts, medio, maximo)
    return melhor


def escolhe_ciclo(caminhos, desde, avisos):
    boots = ab.boots_em_ordem(caminhos, avisos)
    ciclos = ab.separa_ciclos(boots)
    if desde:
        ciclos = [c[i:] for c in ciclos for i, (b, _) in enumerate(c) if b.startswith(desde)][:1]
    ciclos = [c for c in ciclos if ab.integra(c)[1] > 0]
    return ciclos[-1] if ciclos else None


def conf(r, pts, args, boots, total_min, total_mah, medio, maximo, relativo):
    linhas = [
        "# Curva da bateria do R36S (feature 48-bateria-percentual): coloque este arquivo",
        "# como r36-bateria-curva.conf na raiz da p1 para trocar a curva do system.",
        f"# Gerada por tools/ajusta_curva_bateria.py do ciclo dos boots {', '.join(boots)}:",
        f"# {total_min:.0f} min, {total_mah:.0f} mAh integrados"
        + (" (ciclo incompleto: referência relativa)" if relativo else "") + ".",
        f"# Erro contra a carga integrada, dentro da amostra: médio {medio:.1f}, máximo {maximo:.1f} pontos.",
        f"r_mohm={r}",
        f"filtro={args.filtro}",
        f"v_zero={args.v_zero}",
        f"v_um={args.v_um}",
    ]
    linhas += [f"ponto={x},{y}" for x, y in pts]
    return "\n".join(linhas) + "\n"


def main(argv):
    ap = argparse.ArgumentParser(prog="ajusta_curva_bateria.py", description=__doc__.strip().splitlines()[0])
    ap.add_argument("csv", nargs="+", help="r36-thermal.1.csv e r36-thermal.csv, do mais antigo ao mais novo")
    ap.add_argument("--desde", help="escolhe o ciclo que contém este boot, a partir dele (padrão: o último)")
    ap.add_argument("--aceita-relativo", action="store_true", help="aceita um ciclo que não termina em desligamento")
    ap.add_argument("--r-mohm", type=int, help="usa esta resistência em vez de procurar a de menor erro")
    ap.add_argument("--filtro", type=int, default=PADRAO["filtro"])
    ap.add_argument("--v-zero", type=int, default=PADRAO["v_zero"])
    ap.add_argument("--v-um", type=int, default=PADRAO["v_um"])
    ap.add_argument("-o", "--saida", default="r36-bateria-curva.conf")
    args = ap.parse_args(argv)
    if args.filtro < 1 or args.v_zero >= args.v_um or (args.r_mohm is not None and args.r_mohm < 0):
        print("erro: --filtro deve ser >= 1, --r-mohm >= 0 e --v-zero menor que --v-um", file=sys.stderr)
        return 2

    avisos = []
    try:
        ciclo = escolhe_ciclo(args.csv, args.desde, avisos)
    except OSError as e:
        print(f"erro: {e}", file=sys.stderr)
        return 1
    for a in avisos:
        print(f"aviso: {a}", file=sys.stderr)
    if ciclo is None:
        print("erro: nenhum ciclo de descarga com corrente (bat_current) no CSV", file=sys.stderr)
        return 1
    pontos, total_mah, total_min = ab.integra(ciclo)
    fim = pontos[-1]["mv"]
    relativo = fim is None or fim > ab.FIM_MV
    if relativo:
        print(f"aviso: o ciclo não termina em {ab.FIM_MV} mV ou menos: a referência de carga é relativa "
              f"ao que foi gravado", file=sys.stderr)
        if not args.aceita_relativo:
            print("erro: arquivo não escrito; use --aceita-relativo para gerar mesmo assim", file=sys.stderr)
            return 1
    amos = amostras(pontos, total_mah)
    r, pts, medio, maximo = ajusta(amos, args.filtro, args.r_mohm)
    boots = list(dict.fromkeys(p["boot"] for p in pontos))
    with open(args.saida, "w", encoding="utf-8") as f:
        f.write(conf(r, pts, args, boots, total_min, total_mah, medio, maximo, relativo))
    print(f"ciclo: {total_min:.0f} min, {total_mah:.0f} mAh, {len(amos)} amostras")
    print(f"R = {r} mohm, {len(pts)} pontos; erro médio {medio:.1f} pontos, máximo {maximo:.1f}")
    print(f"escrito: {args.saida}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
