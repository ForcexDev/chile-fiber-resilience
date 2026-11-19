"""Probabilidad de falla de cada enlace ante el sismo y generacion de main.sql.

PGA mediana: Youngs et al. (1997), sismo de subduccion interplaca, coeficientes para suelo:
    ln PGA[g] = -0.6687 + 1.438 M - 2.329 ln(Rrup + 1.097 e^(0.617 M)) + 0.00648 H
    sigma = 1.45 - 0.1 min(M, 8) = 0.65
Rrup: distancia mas corta del enlace al plano de ruptura del ShakeMap de USGS (Hayes 2011).
Falla: el enlace se corta si la PGA supera el umbral de dano. Umbral = 0.215 g, PGA de la
intensidad VII ("dano moderado") en la leyenda del ShakeMap del evento (Worden et al. 2012).
    P(falla) = 1 - Phi((ln umbral - ln PGA) / sigma)
"""
import json
import math
import sys

import numpy as np
from scipy.spatial import cKDTree

from db import conectar

UMBRAL_G = 0.215
LAT0 = -36.0
KM_LAT = 111.2
KM_LON = 111.2 * math.cos(math.radians(LAT0))


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


def escribir_sql(sid, m, h, umbral, filas, ruta="main.sql"):
    with open(ruta, "w") as f:
        f.write(f"-- Probabilidad de falla de cada enlace ante el sismo {sid} (M{m}, prof. {h} km)\n")
        f.write("-- PGA: Youngs et al. (1997), interplaca, suelo, Rrup al plano de ruptura del ShakeMap USGS\n")
        f.write(f"-- P(falla) = P(PGA > {umbral} g), sigma = 0.65\n")
        f.write("DROP TABLE IF EXISTS probabilidad_falla;\n")
        f.write("CREATE TABLE probabilidad_falla (\n  id_enlace int PRIMARY KEY,\n  tipo text,\n"
                "  km float,\n  rrup_km float,\n  pga_g float,\n  prob_falla float\n);\n")
        f.write("INSERT INTO probabilidad_falla VALUES\n")
        f.write(",\n".join(f"({i}, '{t}', {km:.3f}, {r:.2f}, {pga:.4f}, {p:.6f})"
                           for i, t, km, r, pga, p in filas))
        f.write(";\n")


def main():
    datos = calcular(float(sys.argv[1]) if len(sys.argv) > 1 else UMBRAL_G)
    escribir_sql(*datos)
    filas = datos[-1]
    print(f"main.sql: {len(filas)} enlaces, umbral {datos[3]} g")
    for a, b in [(0.5, 1.01), (0.1, 0.5), (0.01, 0.1), (0, 0.01)]:
        sel = [x for x in filas if a <= x[5] < b]
        print(f"  P en [{a}, {b}): {len(sel)} enlaces, {sum(x[2] for x in sel):.0f} km")


if __name__ == "__main__":
    main()
