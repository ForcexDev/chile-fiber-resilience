"""ATTR de los nodos clave usando solo la fibra levantada (sin los enlaces de continuidad)."""
import itertools

import networkx as nx

from db import conectar


def main():
    cur = conectar().cursor()
    cur.execute("SELECT source, target FROM enlaces WHERE tipo <> 'continuidad'")
    g = nx.Graph(cur.fetchall())
    comp = {v: i for i, c in enumerate(nx.connected_components(g)) for v in c}
    print(f"componentes de la red sin supuestos: {nx.number_connected_components(g)}")
    for conjunto in ("principal", "ciudades"):
        cur.execute(f"SELECT nombre, vertice FROM nodos_clave WHERE {conjunto} ORDER BY nombre")
        nk = [(n, v) for n, v in cur.fetchall()]
        # sin supuestos un nodo clave solo esta conectado si su acometida llega a la fibra (vertice en g)
        pares = sum(a in g and b in g and comp[a] == comp[b] for (_, a), (_, b) in itertools.combinations(nk, 2))
        total = len(nk) * (len(nk) - 1) // 2
        print(f"== {conjunto}: pares conectados {pares} de {total}, ATTR sin enlaces de continuidad {pares / total:.4f}")
        grupos = {}
        for n, v in nk:
            grupos.setdefault(comp.get(v, n), []).append(n)
        for g_ in grupos.values():
            if len(g_) > 1:
                print("   ", ", ".join(g_))


if __name__ == "__main__":
    main()
