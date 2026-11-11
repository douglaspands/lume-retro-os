"""Resume o r36-thermal.csv no PC por ciclo de descarga: duração, carga entregue e erro do percentual.

Uso: uv run python -I tools/analisa_bateria.py [--desde <boot>] r36-thermal.1.csv r36-thermal.csv

Passe os arquivos do mais antigo para o mais novo. Os boots de uma mesma descarga formam um
ciclo (um novo ciclo começa depois de uma linha Charging/Full, ou num boot que começa mais de
150 mV acima do fim do anterior). Dentro do boot a corrente (bat_current) é integrada em mAh
pelo uptime_s; a carga restante de referência é 100 * (1 - mAh / total) e vale quando o ciclo
termina em desligamento. Por ciclo sai a duração, os mAh, o erro médio e máximo (em pontos) do
bat_pct (kernel) e do bat_pct_pub (publicado) contra essa referência, e os patamares em que o
kernel ficou parado em 100% e em 5%. Colunas que faltam (CSV antigo) são avisadas, não são erro.
--desde escolhe o ciclo que contém o boot informado, a partir dele.
"""

import csv
import sys

SALTO_MV = 150      # boot que começa tanto acima do fim do anterior é outro ciclo
LACUNA_S = 60       # intervalo maior que isto entre amostras não é integrado
FIM_MV = 3450       # o ciclo completo termina em ou abaixo desta tensão
MIN_AMOSTRAS = 10   # ciclos menores são ruído (um boot curto)
PATAMARES = (100, 5)
ESPERADAS = ("boot", "uptime_s", "bat_status", "bat_pct", "bat_voltage", "bat_current", "bat_pct_pub")


def inteiro(texto):
    try:
        return int(texto)
    except (TypeError, ValueError):
        return None


def le_csv(caminho, avisos):
    with open(caminho, newline="", encoding="utf-8") as f:
        leitor = csv.DictReader(f)
        faltam = [c for c in ESPERADAS if c not in (leitor.fieldnames or [])]
        if faltam:
            avisos.append(f"{caminho}: colunas ausentes: {', '.join(faltam)}")
        return list(leitor)


def boots_em_ordem(caminhos, avisos):
    """[(boot, linhas)] na ordem em que cada boot aparece; as linhas ordenadas por uptime_s."""
    boots = {}
    for c in caminhos:
        for linha in le_csv(c, avisos):
            boots.setdefault(linha.get("boot") or "?", []).append(linha)
    for linhas in boots.values():
        linhas.sort(key=lambda l: inteiro(l.get("uptime_s")) if inteiro(l.get("uptime_s")) is not None else 0)
    return list(boots.items())


def separa_ciclos(boots):
    """Lista de ciclos; cada um é a lista de (boot, linha) em Discharging, na ordem."""
    ciclos = []
    atual = None
    carregou = False
    fim_mv = None
    for boot, linhas in boots:
        primeira = True
        for l in linhas:
            st = l.get("bat_status")
            if st in ("Charging", "Full"):
                carregou = True
                continue
            if st != "Discharging":
                continue
            mv = inteiro(l.get("bat_voltage"))
            salto = primeira and mv is not None and fim_mv is not None and mv > fim_mv + SALTO_MV
            if atual is None or carregou or salto:
                atual = []
                ciclos.append(atual)
                carregou = False
            primeira = False
            atual.append((boot, l))
            if mv is not None:
                fim_mv = mv
    return [c for c in ciclos if len(c) >= MIN_AMOSTRAS]


def integra(ciclo):
    """Pontos do ciclo com o tempo e a carga acumulados: dicts com boot, min, mah, mv, ma,
    kernel (bat_pct) e pub (bat_pct_pub). Devolve (pontos, total_mah, total_min)."""
    pontos = []
    mah = 0.0
    seg = 0.0
    anterior = None
    for boot, l in ciclo:
        up = inteiro(l.get("uptime_s"))
        ma = inteiro(l.get("bat_current"))
        ma = abs(ma) if ma is not None else None
        if anterior is not None and anterior["boot"] == boot and up is not None and anterior["up"] is not None:
            dt = up - anterior["up"]
            if 0 < dt <= LACUNA_S:
                seg += dt
                if ma is not None and anterior["ma"] is not None:
                    mah += (ma + anterior["ma"]) / 2 * dt / 3600
        p = {"boot": boot, "up": up, "min": seg / 60, "mah": mah, "mv": inteiro(l.get("bat_voltage")),
             "ma": ma, "kernel": inteiro(l.get("bat_pct")), "pub": inteiro(l.get("bat_pct_pub"))}
        pontos.append(p)
        anterior = p
    return pontos, mah, seg / 60


def referencia(p, total_mah):
    """Carga restante (%) de um ponto, pela corrente integrada."""
    return 100 * (1 - p["mah"] / total_mah)


def erro(pontos, total_mah, chave):
    """(média, máximo) do erro absoluto em pontos de `chave` contra a referência, ou None."""
    es = [abs(p[chave] - referencia(p, total_mah)) for p in pontos if p[chave] is not None]
    return (sum(es) / len(es), max(es)) if es else None


def patamar(pontos, valor):
    """(primeiro, último) ponto em que o kernel marcou `valor`, ou None."""
    ps = [p for p in pontos if p["kernel"] == valor]
    return (ps[0], ps[-1]) if ps else None


def fmt_mv(p):
    return "n/d" if p["mv"] is None else f"{p['mv']} mV"


def relatorio_ciclo(n, ciclo, avisos, sem_corrente):
    pontos, total_mah, total_min = integra(ciclo)
    boots = []
    for p in pontos:
        if p["boot"] not in boots:
            boots.append(p["boot"])
    saida = [f"ciclo {n}: boots {', '.join(boots)}; {total_min:.0f} min; {total_mah:.0f} mAh; "
             f"tensão {fmt_mv(pontos[0])} -> {fmt_mv(pontos[-1])}"]
    if total_mah <= 0:
        sem_corrente.append(n)
        return saida
    fim = pontos[-1]["mv"]
    if fim is None or fim > FIM_MV:
        avisos.append(f"ciclo {n}: não termina em {FIM_MV} mV ou menos; a referência de carga é relativa "
                      f"ao que foi gravado, não à bateria inteira")
    for rotulo, chave in (("kernel (bat_pct)", "kernel"), ("publicado (bat_pct_pub)", "pub")):
        e = erro(pontos, total_mah, chave)
        if e is None:
            saida.append(f"  {rotulo}: sem dados")
        else:
            saida.append(f"  {rotulo}: erro médio {e[0]:.1f} pontos, máximo {e[1]:.1f}")
    for v in PATAMARES:
        pat = patamar(pontos, v)
        if pat is None:
            saida.append(f"  patamar do kernel em {v}%: nunca")
            continue
        a, b = pat
        saida.append(f"  patamar do kernel em {v}%: de {a['min']:.0f} a {b['min']:.0f} min "
                     f"({b['min'] - a['min']:.0f} min), de {a['mah']:.0f} a {b['mah']:.0f} mAh, "
                     f"entra a {fmt_mv(a)} e sai a {fmt_mv(b)}")
    return saida


def resumo(caminhos, desde=None):
    """Devolve (linhas do resumo, avisos)."""
    avisos = []
    boots = boots_em_ordem(caminhos, avisos)
    ciclos = separa_ciclos(boots)
    if desde:
        escolhidos = []
        for c in ciclos:
            for i, (boot, _) in enumerate(c):
                if boot.startswith(desde):
                    escolhidos.append(c[i:])
                    break
        ciclos = escolhidos
    if not ciclos:
        return ["nenhum ciclo de descarga encontrado" + (f" a partir do boot {desde}" if desde else "")], avisos
    saida = []
    sem_corrente = []
    for n, c in enumerate(ciclos, 1):
        saida.extend(relatorio_ciclo(n, c, avisos, sem_corrente))
    if sem_corrente:
        avisos.append(f"ciclos {', '.join(map(str, sem_corrente))}: sem corrente (bat_current) para integrar, "
                      f"então sem erro contra a carga real")
    return saida, avisos


def main(argv):
    desde = None
    if argv[:1] == ["--desde"] and len(argv) >= 2:
        desde, argv = argv[1], argv[2:]
    if not argv:
        print(__doc__.strip().splitlines()[2], file=sys.stderr)
        return 2
    try:
        saida, avisos = resumo(argv, desde)
    except OSError as e:
        print(f"erro: {e}", file=sys.stderr)
        return 1
    for a in avisos:
        print(f"aviso: {a}", file=sys.stderr)
    print("\n".join(saida))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
