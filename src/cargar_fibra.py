"""Carga los shapefiles de Yafun (respuesta SUBTEL T5610) en PostGIS."""
import shapefile
from db import conectar

CAPAS = {
    "fibra": "datos/Respuesta_T5610/fibra_optica_detectada",
    "ferry": "datos/Respuesta_T5610/trayecto_en_ferry",
}


def wkt(shape):
    partes = list(shape.parts) + [len(shape.points)]
    lineas = []
    for a, b in zip(partes[:-1], partes[1:]):
        pts = shape.points[a:b]
        if len(pts) >= 2:
            lineas.append("(" + ",".join(f"{x} {y}" for x, y in pts) + ")")
    return "MULTILINESTRING(" + ",".join(lineas) + ")" if lineas else None


def main():
    con = conectar()
    cur = con.cursor()
    cur.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    cur.execute("CREATE EXTENSION IF NOT EXISTS pgrouting")
    for tabla, ruta in CAPAS.items():
        cur.execute(f"DROP TABLE IF EXISTS {tabla}")
        cur.execute(f"CREATE TABLE {tabla} (gid serial PRIMARY KEY, id_shp text, geom geometry(MultiLineString, 4326))")
        r = shapefile.Reader(ruta)
        n = 0
        for sr in r.iterShapeRecords():
            g = wkt(sr.shape)
            if g:
                cur.execute(f"INSERT INTO {tabla} (id_shp, geom) VALUES (%s, ST_GeomFromText(%s, 4326))",
                            (str(sr.record[0]), g))
                n += 1
        cur.execute(f"CREATE INDEX ON {tabla} USING gist (geom)")
        cur.execute(f"SELECT round(sum(ST_Length(geom::geography))/1000) FROM {tabla}")
        print(f"{tabla}: {n} tramos, {cur.fetchone()[0]:.0f} km")


if __name__ == "__main__":
    main()
