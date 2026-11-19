"""Nodos clave que intercambian informacion, identificados desde la topologia.

Se calcula la centralidad de intermediacion (betweenness, ponderada por km) de cada vertice
de la red de fibra (Boettcher et al. 2018 usan la centralidad para identificar nodos clave).
Se eligen los N cruces (grado >= 3) con mayor centralidad, separados por al menos SEP_KM
para no tomar varias veces el mismo cruce. Cada cruce se nombra con la localidad mas cercana
(Nominatim/OpenStreetMap, guardado en datos/externos/lugares_centralidad.json).
"""
import json
import math
import os
import time
import urllib.request

import networkx as nx

N_CRUCES = 10
SEP_KM = 50.0
CACHE = "datos/externos/lugares_centralidad.json"


def _km(a, b):
    lat = math.radians((a[1] + b[1]) / 2)
    return math.hypot((a[0] - b[0]) * math.cos(lat), a[1] - b[1]) * 111.2


def lugar(lon, lat, cache):
    clave = f"{lat:.4f},{lon:.4f}"
    if clave not in cache:
        url = (f"https://nominatim.openstreetmap.org/reverse?format=jsonv2&zoom=10&accept-language=es"
               f"&lat={lat}&lon={lon}")
        req = urllib.request.Request(url, headers={"User-Agent": "tarea-resiliencia-udp"})
        d = json.load(urllib.request.urlopen(req))
        a = d.get("address", {})
        cache[clave] = a.get("city") or a.get("town") or a.get("village") or a.get("municipality") \
            or a.get("county") or d.get("name") or clave
        time.sleep(1.1)
    return cache[clave]


def calcular(cur):
    """Guarda la centralidad de todos los cruces en la tabla centralidad y devuelve los elegidos."""
    cur.execute("""SELECT source, target, km FROM enlaces
                   WHERE tipo IN ('fibra', 'continuidad', 'submarino') AND source <> target""")
    g = nx.Graph()
    for s, t, km in cur.fetchall():
        if not g.has_edge(s, t) or g[s][t]["km"] > km:
            g.add_edge(s, t, km=km)
    cur.execute("SELECT id, ST_X(the_geom), ST_Y(the_geom) FROM enlaces_vertices_pgr")
    pos = {i: (x, y) for i, x, y in cur.fetchall()}
    bc = nx.betweenness_centrality(g, weight="km", normalized=True)

    cur.execute("DROP TABLE IF EXISTS centralidad")
    cur.execute("CREATE TABLE centralidad (vertice int, grado int, betweenness float, "
                "elegido boolean DEFAULT false, nombre text, geom geometry(Point, 4326))")
    cruces = sorted((v for v in g if g.degree(v) >= 3), key=lambda v: (-bc[v], v))
    for v in cruces:
        cur.execute("INSERT INTO centralidad (vertice, grado, betweenness, geom) "
                    "VALUES (%s, %s, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326))",
                    (v, g.degree(v), bc[v], *pos[v]))

    elegidos = []
    for v in cruces:
        if all(_km(pos[v], pos[u]) >= SEP_KM for u in elegidos):
            elegidos.append(v)
        if len(elegidos) == N_CRUCES:
            break
    cache = json.load(open(CACHE)) if os.path.exists(CACHE) else {}
    salida = []
    for k, v in enumerate(elegidos, 1):
        nombre = f"C{k} {lugar(*pos[v], cache)}"
        cur.execute("UPDATE centralidad SET elegido = true, nombre = %s WHERE vertice = %s", (nombre, v))
        salida.append((nombre, v, bc[v], g.degree(v), pos[v]))
    json.dump(cache, open(CACHE, "w"), ensure_ascii=False, indent=1)
    print(f"centralidad: {len(cruces)} cruces, elegidos los {len(salida)} mayores (separados >= {SEP_KM:.0f} km)")
    for nombre, v, b, d, _ in salida:
        print(f"   {nombre:20s} betweenness {b:.3f}  grado {d}")
    return salida
