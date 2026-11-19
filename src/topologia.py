"""Arma la topologia de la red con pgRouting.

1. enlaces = fibra de Yafun + cables submarinos del sur (FOA, Chacao, Quellon-Chacabuco)
2. pgr_nodeNetwork corta los tramos donde se cruzan y pgr_createTopology crea los vertices
3. los huecos del levantamiento se cierran con enlaces de 'continuidad' (arbol minimo
   entre componentes, solo huecos <= HUECO_MAX_KM)
4. cada nodo clave se une al vertice mas cercano con un enlace de 'acometida'
5. se vuelve a correr pgr_createTopology con todos los enlaces
6. se podan las ramas muertas (tramos que terminan sin llegar a un nodo clave y las
   componentes sin nodos clave), que no participan en ningun camino entre nodos clave, y
   las cadenas de tramos unidas por vertices de grado 2 se juntan en un solo enlace entre
   dos nodos de la red (cruces o nodos clave): tabla enlaces_red
"""
import csv
import json
import math
import sys

import networkx as nx
import numpy as np

import centralidad
from db import conectar

TOL = 0.0005          # tolerancia de pgr_createTopology en grados (~50 m)
HUECO_MAX_KM = 60.0


def km_aprox(a, b):
    lat = math.radians((a[1] + b[1]) / 2)
    return math.hypot((a[0] - b[0]) * math.cos(lat), a[1] - b[1]) * 111.2


def grafo(cur):
    cur.execute("SELECT id, source, target, km FROM enlaces")
    g = nx.Graph()
    for i, s, t, km in cur.fetchall():
        g.add_edge(s, t, id=i, km=km)
    cur.execute("SELECT id, ST_X(the_geom), ST_Y(the_geom) FROM enlaces_vertices_pgr")
    pos = {i: (x, y) for i, x, y in cur.fetchall()}
    return g, pos


def main():
    con = conectar()
    cur = con.cursor()

    # 1. lineas base
    cur.execute("DROP TABLE IF EXISTS base, base_noded, enlaces, enlaces_vertices_pgr CASCADE")
    cur.execute("CREATE TABLE base (id serial PRIMARY KEY, tipo text, nombre text, geom geometry(LineString, 4326))")
    cur.execute("INSERT INTO base (tipo, nombre, geom) "
                "SELECT 'fibra', 'yafun ' || id_shp, (ST_Dump(geom)).geom FROM fibra")
    for f in json.load(open("datos/externos/cables_sur.geojson"))["features"]:
        cur.execute("INSERT INTO base (tipo, nombre, geom) SELECT 'submarino', %s, "
                    "(ST_Dump(ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326))).geom",
                    (f["properties"]["name"], json.dumps(f["geometry"])))

    # 2. cortar cruces y crear topologia
    cur.execute("SELECT pgr_nodeNetwork('base', %s, 'id', 'geom')", (TOL,))
    cur.execute("""CREATE TABLE enlaces AS
                   SELECT n.id, b.tipo, b.nombre, n.geom::geometry(LineString, 4326) geom
                   FROM base_noded n JOIN base b ON b.id = n.old_id""")
    cur.execute("ALTER TABLE enlaces ADD PRIMARY KEY (id), ADD source int, ADD target int, "
                "ADD km float, ADD prob_falla float DEFAULT 0")
    cur.execute("SELECT pgr_createTopology('enlaces', %s, 'geom', 'id')", (TOL,))

    # 3. enlaces de continuidad entre componentes (Kruskal sobre la distancia mas corta)
    cur.execute("UPDATE enlaces SET km = ST_Length(geom::geography) / 1000")
    g, pos = grafo(cur)
    comps = list(nx.connected_components(g))
    print(f"componentes antes de cerrar huecos: {len(comps)}")
    cv = [np.array([pos[v] for v in c]) for c in comps]
    cl = [list(c) for c in comps]
    cand = []
    for i in range(len(comps)):
        for j in range(i + 1, len(comps)):
            a, b = cv[i], cv[j]
            lat = math.radians(a[:, 1].mean())
            d = np.hypot((a[:, None, 0] - b[None, :, 0]) * math.cos(lat), a[:, None, 1] - b[None, :, 1]) * 111.2
            k = d.argmin()
            x, y = divmod(k, d.shape[1])
            if d[x, y] <= HUECO_MAX_KM:
                cand.append((d[x, y], i, j, cl[i][x], cl[j][y]))
    uf = nx.utils.UnionFind(range(len(comps)))
    n_cont = 0
    for d, i, j, va, vb in sorted(cand):
        if uf[i] != uf[j]:
            uf.union(i, j)
            cur.execute("INSERT INTO enlaces (id, tipo, nombre, geom, source, target, km) "
                        "SELECT (SELECT max(id)+1 FROM enlaces), 'continuidad', %s, ST_MakeLine(a.the_geom, b.the_geom), "
                        "a.id, b.id, ST_Distance(a.the_geom::geography, b.the_geom::geography) / 1000 "
                        "FROM enlaces_vertices_pgr a, enlaces_vertices_pgr b WHERE a.id = %s AND b.id = %s",
                        (f"hueco {d:.1f} km", va, vb))
            n_cont += 1
    print(f"enlaces de continuidad agregados: {n_cont} (huecos <= {HUECO_MAX_KM} km)")

    # 4. nodos clave: ciudades (datos/nodos_clave.csv) y cruces de mayor centralidad
    cur.execute("DROP TABLE IF EXISTS nodos_clave")
    cur.execute("CREATE TABLE nodos_clave (nombre text PRIMARY KEY, rol text, detalle text, "
                "rol_principal text, principal boolean, ciudades boolean, "
                "geom geometry(Point, 4326), vertice int, acometida_m float)")
    for r in csv.DictReader(open("datos/nodos_clave.csv")):
        cur.execute("INSERT INTO nodos_clave (nombre, rol, detalle, rol_principal, principal, ciudades, geom) "
                    "VALUES (%s, %s, %s, %s, %s, true, ST_SetSRID(ST_MakePoint(%s, %s), 4326))",
                    (r["nombre"], r["rol"], r["detalle"], r["rol_principal"] or None, bool(r["rol_principal"]),
                     float(r["lon"]), float(r["lat"])))
    for nombre, v, b, d, (x, y) in centralidad.calcular(cur):
        cur.execute("INSERT INTO nodos_clave (nombre, rol, detalle, rol_principal, principal, ciudades, geom) "
                    "VALUES (%s, 'intercambia', %s, 'intercambia', true, false, ST_SetSRID(ST_MakePoint(%s, %s), 4326))",
                    (nombre, f"cruce de grado {d}, betweenness {b:.3f}", x, y))
    cur.execute("""INSERT INTO enlaces (id, tipo, nombre, geom)
                   SELECT (SELECT max(id) FROM enlaces) + row_number() OVER (), 'acometida', 'acometida ' || n.nombre,
                          ST_MakeLine(n.geom, v.the_geom)
                   FROM nodos_clave n
                   CROSS JOIN LATERAL (SELECT the_geom FROM enlaces_vertices_pgr
                                       WHERE id IN (SELECT source FROM enlaces WHERE tipo <> 'continuidad'
                                                    UNION SELECT target FROM enlaces WHERE tipo <> 'continuidad')
                                       ORDER BY the_geom <-> n.geom LIMIT 1) v
                   WHERE ST_Distance(n.geom, v.the_geom) > 0""")

    # 5. topologia final
    cur.execute("UPDATE enlaces SET source = NULL, target = NULL, km = ST_Length(geom::geography) / 1000")
    cur.execute("DROP TABLE enlaces_vertices_pgr")
    cur.execute("SELECT pgr_createTopology('enlaces', %s, 'geom', 'id', clean := true)", (TOL,))
    cur.execute("""UPDATE nodos_clave n SET vertice = (SELECT id FROM enlaces_vertices_pgr
                                                      ORDER BY the_geom <-> n.geom LIMIT 1),
                   acometida_m = (SELECT coalesce(sum(km), 0) * 1000 FROM enlaces e
                                  WHERE e.tipo = 'acometida' AND e.nombre = 'acometida ' || n.nombre)""")
    cur.execute("CREATE INDEX ON enlaces USING gist (geom)")
    # la tabla centralidad queda con los ids de vertice de la topologia final
    cur.execute("""UPDATE centralidad c SET vertice = (SELECT id FROM enlaces_vertices_pgr
                                                       ORDER BY the_geom <-> c.geom LIMIT 1)""")

    construir_enlaces_red(cur)

    cur.execute("SELECT tipo, count(*), round(sum(km)) FROM enlaces GROUP BY 1 ORDER BY 1")
    for t, n, km in cur.fetchall():
        print(f"  {t:12s} {n:5d} enlaces {km:8.0f} km")
    cur.execute("SELECT count(*) FROM enlaces_vertices_pgr")
    print(f"vertices: {cur.fetchone()[0]}")
    cur.execute("SELECT count(*), round(sum(km)) FROM enlaces_red")
    n, km = cur.fetchone()
    cur.execute("SELECT count(DISTINCT v) FROM (SELECT source v FROM enlaces_red UNION SELECT target FROM enlaces_red) x")
    print(f"enlaces_red: {n} enlaces entre {cur.fetchone()[0]} nodos de red, {km:.0f} km")
    g, _ = grafo(cur)
    cur.execute("SELECT nombre, vertice FROM nodos_clave WHERE principal")
    nk = cur.fetchall()
    comp_de = {v: k for k, c in enumerate(nx.connected_components(g)) for v in c}
    grupos = {}
    for nombre, v in nk:
        grupos.setdefault(comp_de.get(v), []).append(nombre)
    print(f"componentes finales: {nx.number_connected_components(g)}; nodos clave por componente:")
    for c, ns in grupos.items():
        print("  ", ns)


def construir_enlaces_red(cur):
    cur.execute("SELECT id, source, target FROM enlaces WHERE source <> target")
    g = nx.MultiGraph()
    for i, s, t in cur.fetchall():
        g.add_edge(s, t, key=i)
    cur.execute("SELECT vertice FROM nodos_clave")
    clave = {v for (v,) in cur.fetchall()}
    # componentes sin nodos clave
    for c in list(nx.connected_components(g)):
        if not c & clave:
            g.remove_nodes_from(c)
    # ramas muertas
    hojas = [v for v in g if g.degree(v) == 1 and v not in clave]
    while hojas:
        g.remove_nodes_from(hojas)
        hojas = [v for v in g if g.degree(v) == 1 and v not in clave]
    g.remove_nodes_from([v for v in g if g.degree(v) == 0 and v not in clave])
    es_nodo = {v for v in g if g.degree(v) != 2 or v in clave}
    visto, cadenas = set(), []
    for v in sorted(es_nodo) + sorted(v for v in g if v not in es_nodo):
        if v not in es_nodo and v in {x for c in cadenas for x in c[2]}:
            continue
        for _, w, k in sorted(g.edges(v, keys=True), key=lambda e: e[2]):
            if k in visto:
                continue
            ids, verts, prev, cur_v = [k], [v, w], v, w
            visto.add(k)
            while cur_v not in es_nodo and cur_v != v:
                sig = sorted((kk, x) for _, x, kk in g.edges(cur_v, keys=True) if kk not in visto)
                if not sig:
                    break
                kk, x = sig[0]
                visto.add(kk)
                ids.append(kk)
                verts.append(x)
                prev, cur_v = cur_v, x
            cadenas.append((v, cur_v, verts, ids))
    cur.execute("DROP TABLE IF EXISTS enlaces_red CASCADE")
    cur.execute("""CREATE TABLE enlaces_red (id int PRIMARY KEY, source int, target int, tramos int[],
                   tipo text, km float, km_supuesto float, prob_falla float DEFAULT 0,
                   geom geometry(MultiLineString, 4326))""")
    for n, (a, b, _, ids) in enumerate(cadenas, 1):
        cur.execute("""INSERT INTO enlaces_red
                       SELECT %s, %s, %s, %s,
                              CASE WHEN bool_and(tipo = 'submarino') THEN 'submarino'
                                   WHEN bool_and(tipo IN ('continuidad', 'acometida')) THEN 'supuesto'
                                   ELSE 'fibra' END,
                              sum(km), coalesce(sum(km) FILTER (WHERE tipo IN ('continuidad', 'acometida')), 0),
                              0.0, ST_Multi(ST_LineMerge(ST_Collect(geom)))
                       FROM enlaces WHERE id = ANY(%s)""", (n, a, b, ids, ids))
    # ids estables: pgr_createTopology no siempre numera igual los vertices, asi que los enlaces
    # se numeran de norte a sur segun su centroide
    cur.execute("""CREATE TABLE enlaces_red_ord AS
                   SELECT row_number() OVER (ORDER BY round(ST_Y(ST_Centroid(geom))::numeric, 6) DESC,
                                                      round(ST_X(ST_Centroid(geom))::numeric, 6),
                                                      round(km::numeric, 4))::int AS id,
                          source, target, tramos, tipo, km, km_supuesto, prob_falla, geom
                   FROM enlaces_red""")
    cur.execute("DROP TABLE enlaces_red")
    cur.execute("ALTER TABLE enlaces_red_ord RENAME TO enlaces_red")
    cur.execute("ALTER TABLE enlaces_red ADD PRIMARY KEY (id)")
    cur.execute("ALTER TABLE enlaces_red ALTER COLUMN prob_falla SET DEFAULT 0")
    cur.execute("CREATE INDEX ON enlaces_red USING gist (geom)")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        HUECO_MAX_KM = float(sys.argv[1])
    main()
