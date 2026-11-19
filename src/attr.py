"""ATTR (Average Two-Terminal Reliability) de los nodos clave, antes y despues del sismo.

ATTR = C(n,2)^-1 * sum_{i<j} Z_ij, con Z_ij = 1 si existe un camino entre i y j
(Boettcher et al. 2018, ec. 8). Despues del sismo cada enlace falla con su probabilidad
(tabla probabilidad_falla) y el ATTR se promedia sobre N simulaciones de Monte Carlo,
que equivale al promedio ponderado por la probabilidad de cada escenario (ec. 9).
"""
import itertools
import sys

import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components

from db import conectar


CONJUNTOS = {"principal": "ciudades que generan y reciben + cruces de mayor centralidad",
             "ciudades": "18 ciudades (cables, IXP de PeeringDB y capitales)"}


def cargar(cur, conjunto="principal"):
    cur.execute("SELECT to_regclass('probabilidad_falla') IS NOT NULL")
    if cur.fetchone()[0]:
        cur.execute("""SELECT e.id, e.source, e.target, coalesce(p.prob_falla, e.prob_falla, 0)
                       FROM enlaces_red e LEFT JOIN probabilidad_falla p ON p.id_enlace = e.id
                       WHERE e.source <> e.target ORDER BY e.id""")
    else:
        cur.execute("""SELECT id, source, target, coalesce(prob_falla, 0)
                       FROM enlaces_red WHERE source <> target ORDER BY id""")
    e = np.array(cur.fetchall(), dtype=float)
    assert conjunto in CONJUNTOS
    cur.execute(f"SELECT nombre, vertice, rol FROM nodos_clave WHERE {conjunto} ORDER BY nombre")
    nodos = cur.fetchall()
    return e[:, 0].astype(int), e[:, 1].astype(int), e[:, 2].astype(int), e[:, 3], nodos


def etiquetas(src, tgt, vivo, n):
    a = coo_matrix((np.ones(vivo.sum()), (src[vivo], tgt[vivo])), shape=(n, n))
    return connected_components(a, directed=False)[1]


def attr(lab, verts):
    k = len(verts)
    pares = sum(lab[a] == lab[b] for a, b in itertools.combinations(verts, 2))
    return pares / (k * (k - 1) / 2)


def calcular(n_sim=10000, semilla=2010, conjunto="principal"):
    cur = conectar().cursor()
    ids, src, tgt, prob, nodos = cargar(cur, conjunto)
    n = int(max(src.max(), tgt.max())) + 1
    verts = [v for _, v, _ in nodos]
    antes = attr(etiquetas(src, tgt, np.ones(len(src), bool), n), verts)

    rng = np.random.default_rng(semilla)
    valores = np.empty(n_sim)
    par_ok = np.zeros((len(verts), len(verts)))
    for s in range(n_sim):
        vivo = rng.random(len(src)) >= prob
        lab = etiquetas(src, tgt, vivo, n)
        lv = lab[verts]
        iguales = lv[:, None] == lv[None, :]
        par_ok += iguales
        k = len(verts)
        valores[s] = (iguales.sum() - k) / (k * (k - 1))
    # escenario mas probable: caen los enlaces con P >= 0.5
    lab50 = etiquetas(src, tgt, prob < 0.5, n)
    return {
        "nodos": [x[0] for x in nodos],
        "antes": antes,
        "despues": valores.mean(),
        "despues_sd": valores.std(),
        "p05": np.percentile(valores, 5),
        "p95": np.percentile(valores, 95),
        "esc50": attr(lab50, verts),
        "esc50_grupos": [[nodos[i][0] for i in range(len(verts)) if lab50[verts[i]] == g]
                         for g in dict.fromkeys(lab50[verts])],
        "par_ok": par_ok / n_sim,
        "n_sim": n_sim,
        "conjunto": conjunto,
    }


def main():
    n_sim = int(sys.argv[1]) if len(sys.argv) > 1 else 10000
    for conjunto in CONJUNTOS:
        r = calcular(n_sim, conjunto=conjunto)
        k = len(r["nodos"])
        print(f"== Conjunto {conjunto}: {CONJUNTOS[conjunto]}")
        print(f"Nodos clave: {k} ({k * (k - 1) // 2} pares)")
        print(f"ATTR antes del sismo:   {r['antes']:.4f}")
        print(f"ATTR despues del sismo: {r['despues']:.4f} +- {r['despues_sd']:.4f} "
              f"(P5 {r['p05']:.4f}, P95 {r['p95']:.4f}, {r['n_sim']} simulaciones)")
        print(f"Escenario con los enlaces de P >= 0.5 cortados: ATTR {r['esc50']:.4f}")
        for g in r["esc50_grupos"]:
            print("   ", ", ".join(g))
        i = r["nodos"].index("Santiago")
        print("Probabilidad de seguir conectado con Santiago:")
        for j, nom in enumerate(r["nodos"]):
            if j != i:
                print(f"   {nom:28s} {r['par_ok'][i, j]:.3f}")
        print()


if __name__ == "__main__":
    main()
