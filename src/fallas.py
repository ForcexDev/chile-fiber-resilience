"""Probabilidad de falla de cada enlace ante el sismo y generacion de main.sql.

PGA mediana: Youngs et al. (1997), sismo de subduccion interplaca, coeficientes para suelo:
    ln PGA[g] = -0.6687 + 1.438 M - 2.329 ln(Rrup + 1.097 e^(0.617 M)) + 0.00648 H
    sigma = 1.45 - 0.1 min(M, 8) = 0.65
Rrup: distancia mas corta del enlace al plano de ruptura del ShakeMap de USGS (Hayes 2011).
Falla: el enlace se corta si la PGA supera el umbral de dano. Umbral = 0.215 g, PGA de la
intensidad VII ("dano moderado") en la leyenda del ShakeMap del evento (Worden et al. 2012).
    P(falla) = 1 - Phi((ln umbral - ln PGA) / sigma)
"""
import math
import sys

import numpy as np
from scipy.spatial import cKDTree

from db import conectar

UMBRAL_G = 0.215
LAT0 = -36.0
KM_LAT = 111.2
KM_LON = 111.2 * math.cos(math.radians(LAT0))

TABLAS_SQL = [
    (
        "fibra",
        "CREATE TABLE fibra (gid int PRIMARY KEY, id_shp text, geom geometry(MultiLineString, 4326));",
        "SELECT gid, id_shp, geom::text FROM fibra ORDER BY gid",
        ("scalar", "scalar", "geom"),
        "CREATE INDEX ON fibra USING gist (geom);",
    ),
    (
        "ferry",
        "CREATE TABLE ferry (gid int PRIMARY KEY, id_shp text, geom geometry(MultiLineString, 4326));",
        "SELECT gid, id_shp, geom::text FROM ferry ORDER BY gid",
        ("scalar", "scalar", "geom"),
        "CREATE INDEX ON ferry USING gist (geom);",
    ),
    (
        "enlaces",
        "CREATE TABLE enlaces (id int PRIMARY KEY, tipo text, nombre text, "
        "geom geometry(LineString, 4326), source int, target int, km float, prob_falla float DEFAULT 0);",
        "SELECT id, tipo, nombre, geom::text, source, target, km, prob_falla FROM enlaces ORDER BY id",
        ("scalar", "scalar", "scalar", "geom", "scalar", "scalar", "scalar", "scalar"),
        "CREATE INDEX ON enlaces USING gist (geom);",
    ),
    (
        "enlaces_vertices_pgr",
        "CREATE TABLE enlaces_vertices_pgr (id int PRIMARY KEY, cnt int, chk int, ein int, eout int, "
        "the_geom geometry(Point, 4326));",
        "SELECT id, cnt, chk, ein, eout, the_geom::text FROM enlaces_vertices_pgr ORDER BY id",
        ("scalar", "scalar", "scalar", "scalar", "scalar", "geom"),
        "CREATE INDEX ON enlaces_vertices_pgr USING gist (the_geom);",
    ),
    (
        "centralidad",
        "CREATE TABLE centralidad (vertice int, grado int, betweenness float, "
        "elegido boolean DEFAULT false, nombre text, geom geometry(Point, 4326));",
        "SELECT vertice, grado, betweenness, elegido, nombre, geom::text FROM centralidad "
        "ORDER BY betweenness DESC, vertice",
        ("scalar", "scalar", "scalar", "scalar", "scalar", "geom"),
        None,
    ),
    (
        "nodos_clave",
        "CREATE TABLE nodos_clave (nombre text PRIMARY KEY, rol text, detalle text, "
        "rol_principal text, principal boolean, ciudades boolean, "
        "geom geometry(Point, 4326), vertice int, acometida_m float);",
        "SELECT nombre, rol, detalle, rol_principal, principal, ciudades, geom::text, vertice, acometida_m "
        "FROM nodos_clave ORDER BY nombre",
        ("scalar", "scalar", "scalar", "scalar", "scalar", "scalar", "geom", "scalar", "scalar"),
        None,
    ),
    (
        "enlaces_red",
        "CREATE TABLE enlaces_red (id int PRIMARY KEY, source int, target int, tramos int[], "
        "tipo text, km float, km_supuesto float, prob_falla float DEFAULT 0, "
        "geom geometry(MultiLineString, 4326));",
        "SELECT id, source, target, tramos, tipo, km, km_supuesto, prob_falla, geom::text "
        "FROM enlaces_red ORDER BY id",
        ("scalar", "scalar", "scalar", "int[]", "scalar", "scalar", "scalar", "scalar", "geom"),
        "CREATE INDEX ON enlaces_red USING gist (geom);",
    ),
    (
        "sismo",
        "CREATE TABLE sismo (id text PRIMARY KEY, lugar text, magnitud float, tipo_mag text, "
        "fecha timestamptz, profundidad_km float, geom geometry(Point, 4326), geojson jsonb);",
        "SELECT id, lugar, magnitud, tipo_mag, fecha, profundidad_km, geom::text, geojson::text "
        "FROM sismo ORDER BY id",
        ("scalar", "scalar", "scalar", "scalar", "scalar", "scalar", "geom", "jsonb"),
        None,
    ),
    (
        "ruptura",
        "CREATE TABLE ruptura (esquinas jsonb, geom geometry(Polygon, 4326));",
        "SELECT esquinas::text, geom::text FROM ruptura",
        ("jsonb", "geom"),
        None,
    ),
]


def youngs_suelo(m, rrup, h):
    ln = -0.6687 + 1.438 * m - 2.329 * np.log(rrup + 1.097 * math.exp(0.617 * m)) + 0.00648 * h
    return ln, 1.45 - 0.1 * min(m, 8.0)


def phi(x):
    return 0.5 * (1 + np.vectorize(math.erf)(x / math.sqrt(2)))


def xyz(lon, lat, z):
    return np.column_stack([np.asarray(lon) * KM_LON, np.asarray(lat) * KM_LAT, np.asarray(z)])


def plano_ruptura(esquinas, paso_km=1.0):
    """Malla de puntos sobre el cuadrilatero de la ruptura (interpolacion bilineal)."""
    p = xyz(*zip(*[e for e in esquinas[:4]]))
    a, b, c, d = p          # a-b borde superior, d-c borde inferior
    nu = int(np.linalg.norm(b - a) / paso_km) + 1
    nv = int(np.linalg.norm(d - a) / paso_km) + 1
    u, v = np.meshgrid(np.linspace(0, 1, nu), np.linspace(0, 1, nv))
    u, v = u.ravel()[:, None], v.ravel()[:, None]
    return (1 - u) * (1 - v) * a + u * (1 - v) * b + u * v * c + (1 - u) * v * d


def calcular(umbral=UMBRAL_G):
    cur = conectar().cursor()
    cur.execute("SELECT id, magnitud, profundidad_km FROM sismo")
    sid, m, h = cur.fetchone()
    cur.execute("SELECT esquinas FROM ruptura")
    arbol = cKDTree(plano_ruptura(cur.fetchone()[0]))
    # puntos de cada enlace cada 1 km
    cur.execute("""SELECT e.id, e.tipo, e.km, ST_X(p.geom), ST_Y(p.geom)
                   FROM enlaces_red e,
                        ST_DumpPoints(ST_Segmentize(e.geom::geography, 1000)::geometry) p
                   ORDER BY e.id""")
    rows = cur.fetchall()
    ids = np.array([r[0] for r in rows])
    dist, _ = arbol.query(xyz([r[3] for r in rows], [r[4] for r in rows], np.zeros(len(rows))))
    rrup = {}
    info = {}
    for i, d, r in zip(ids, dist, rows):
        rrup[i] = min(rrup.get(i, 1e9), d)
        info[i] = (r[1], r[2])
    filas = []
    for i in sorted(rrup):
        ln, sigma = youngs_suelo(m, rrup[i], h)
        p = float(1 - phi((math.log(umbral) - ln) / sigma))
        filas.append((int(i), info[i][0], info[i][1], float(rrup[i]), float(math.exp(ln)), p))
    return sid, m, h, umbral, filas


def actualizar_bd(filas):
    """Guarda las probabilidades en probabilidad_falla y actualiza enlaces_red.prob_falla."""
    cur = conectar().cursor()
    cur.execute("DROP TABLE IF EXISTS probabilidad_falla")
    cur.execute("""CREATE TABLE probabilidad_falla (
                     id_enlace int PRIMARY KEY REFERENCES enlaces_red(id),
                     tipo text,
                     km float,
                     rrup_km float,
                     pga_g float,
                     prob_falla float
                   )""")
    cur.executemany("INSERT INTO probabilidad_falla VALUES (%s, %s, %s, %s, %s, %s)", filas)
    cur.executemany("UPDATE enlaces_red SET prob_falla = %s WHERE id = %s",
                    [(p, i) for i, _, _, _, _, p in filas])


def _sql_val(v, kind="scalar"):
    if v is None:
        return "NULL"
    if kind == "geom":
        return f"'{v}'::geometry"
    if kind == "jsonb":
        return "'" + v.replace("'", "''") + "'::jsonb"
    if kind == "int[]":
        return "'{" + ",".join(str(x) for x in v) + "}'::int[]"
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, (int, float)):
        return repr(v)
    if hasattr(v, "isoformat"):
        return f"'{v.isoformat()}'"
    return "'" + str(v).replace("'", "''") + "'"


def _volcar_tabla(cur, f, tabla, ddl, select_sql, kinds, indice_sql, batch=100):
    f.write(f"-- {tabla}\n{ddl}\n")
    cur.execute("SELECT to_regclass(%s) IS NOT NULL", (tabla,))
    if cur.fetchone()[0]:
        cur.execute(select_sql)
        rows = cur.fetchall()
        for ini in range(0, len(rows), batch):
            bloque = rows[ini:ini + batch]
            tuplas = ",\n".join(
                "(" + ", ".join(_sql_val(v, k) for v, k in zip(row, kinds)) + ")"
                for row in bloque
            )
            f.write(f"INSERT INTO {tabla} VALUES\n{tuplas};\n")
    if indice_sql:
        f.write(indice_sql + "\n")
    f.write("\n")


def escribir_sql(sid, m, h, umbral, filas, ruta="main.sql"):
    """Escribe main.sql autocontenido (infraestructura completa + probabilidades de falla)."""
    cur = conectar().cursor()
    nombres = ", ".join(t[0] for t in TABLAS_SQL)
    with open(ruta, "w") as f:
        f.write(f"-- Infraestructura y probabilidad de falla ante el sismo {sid} (M{m}, prof. {h} km)\n")
        f.write("-- PGA: Youngs et al. (1997), interplaca, suelo, Rrup al plano de ruptura del ShakeMap USGS\n")
        f.write(f"-- P(falla) = P(PGA > {umbral} g), sigma = 0.65\n")
        f.write("-- Carga directa sobre BD vacia: psql -v ON_ERROR_STOP=1 -f main.sql\n\n")
        f.write("CREATE EXTENSION IF NOT EXISTS postgis;\n")
        f.write("CREATE EXTENSION IF NOT EXISTS pgrouting;\n\n")
        f.write("BEGIN;\n")
        f.write(f"DROP TABLE IF EXISTS probabilidad_falla, {nombres} CASCADE;\n\n")
        for tabla, ddl, select_sql, kinds, indice_sql in TABLAS_SQL:
            _volcar_tabla(cur, f, tabla, ddl, select_sql, kinds, indice_sql)

        f.write("-- probabilidad_falla\n")
        f.write("CREATE TABLE probabilidad_falla (\n"
                "  id_enlace int PRIMARY KEY REFERENCES enlaces_red(id),\n"
                "  tipo text,\n  km float,\n  rrup_km float,\n  pga_g float,\n  prob_falla float\n);\n")
        f.write("INSERT INTO probabilidad_falla VALUES\n")
        f.write(",\n".join(f"({i}, '{t}', {km:.3f}, {r:.2f}, {pga:.4f}, {p:.6f})"
                           for i, t, km, r, pga, p in filas))
        f.write(";\n")
        f.write("UPDATE enlaces_red e SET prob_falla = p.prob_falla "
                "FROM probabilidad_falla p WHERE p.id_enlace = e.id;\n")
        f.write("COMMIT;\n")


def main():
    datos = calcular(float(sys.argv[1]) if len(sys.argv) > 1 else UMBRAL_G)
    actualizar_bd(datos[-1])
    escribir_sql(*datos)
    filas = datos[-1]
    print(f"main.sql: {len(filas)} enlaces, umbral {datos[3]} g")
    for a, b in [(0.5, 1.01), (0.1, 0.5), (0.01, 0.1), (0, 0.01)]:
        sel = [x for x in filas if a <= x[5] < b]
        print(f"  P en [{a}, {b}): {len(sel)} enlaces, {sum(x[2] for x in sel):.0f} km")
    orden = sorted(filas, key=lambda x: (-x[5], x[0]))
    print("Enlaces mas afectados:")
    for i, t, km, r, pga, p in orden[:5]:
        print(f"  enlace {i:3d} ({t:9s}): {km:6.1f} km, Rrup {r:6.2f} km, PGA {pga:.4f} g, P={p:.4f}")
    print("Enlaces menos afectados:")
    for i, t, km, r, pga, p in orden[-5:][::-1]:
        print(f"  enlace {i:3d} ({t:9s}): {km:6.1f} km, Rrup {r:7.2f} km, PGA {pga:.4f} g, P={p:.6f}")


if __name__ == "__main__":
    main()
