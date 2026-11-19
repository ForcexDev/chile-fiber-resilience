"""Carga el sismo 8.8 (Maule 2010) descargado de USGS en formato GeoJSON."""
import json
import os
import urllib.request

from db import conectar

URL = ("https://earthquake.usgs.gov/fdsnws/event/1/query?format=geojson"
       "&starttime=2010-02-26&endtime=2010-02-28&minmagnitude=8.5")
URL_DETALLE = ("https://earthquake.usgs.gov/fdsnws/event/1/query?format=geojson"
               "&eventid=official20100227063411530_30")
ARCHIVO = "datos/externos/sismo_maule_2010.geojson"
DETALLE = "datos/externos/sismo_detalle.geojson"
RUPTURA = "datos/externos/shakemap_rupture.json"


def main():
    for ruta, url in [(ARCHIVO, URL), (DETALLE, URL_DETALLE)]:
        if not os.path.exists(ruta):
            req = urllib.request.Request(url, headers={"User-Agent": "tarea-resiliencia"})
            open(ruta, "wb").write(urllib.request.urlopen(req).read())
    f = json.load(open(ARCHIVO))["features"][0]
    p = f["properties"]
    lon, lat, prof = f["geometry"]["coordinates"]
    cur = conectar().cursor()
    cur.execute("DROP TABLE IF EXISTS sismo")
    cur.execute("CREATE TABLE sismo (id text PRIMARY KEY, lugar text, magnitud float, tipo_mag text, "
                "fecha timestamptz, profundidad_km float, geom geometry(Point, 4326), geojson jsonb)")
    cur.execute("INSERT INTO sismo VALUES (%s, %s, %s, %s, to_timestamp(%s / 1000.0), %s, "
                "ST_SetSRID(ST_MakePoint(%s, %s), 4326), %s)",
                (f["id"], p["place"], p["mag"], p["magType"], p["time"], prof, lon, lat, json.dumps(f)))
    # ruptura: plano de falla (Hayes 2011) publicado en el ShakeMap del mismo evento
    if not os.path.exists(RUPTURA):
        det = json.load(open(DETALLE))
        url = det["properties"]["products"]["shakemap"][0]["contents"]["download/rupture.json"]["url"]
        req = urllib.request.Request(url, headers={"User-Agent": "tarea-resiliencia"})
        open(RUPTURA, "wb").write(urllib.request.urlopen(req).read())
    rup = json.load(open(RUPTURA))["features"][0]["geometry"]
    esquinas = rup["coordinates"][0][0]
    cur.execute("DROP TABLE IF EXISTS ruptura")
    cur.execute("CREATE TABLE ruptura (esquinas jsonb, geom geometry(Polygon, 4326))")
    cur.execute("INSERT INTO ruptura VALUES (%s, ST_SetSRID(ST_MakePolygon(ST_GeomFromText(%s)), 4326))",
                (json.dumps(esquinas), "LINESTRING(" + ",".join(f"{x} {y}" for x, y, _ in esquinas) + ")"))
    print("ruptura: plano de " + ", ".join(f"({x:.2f}, {y:.2f}, {z:.1f} km)" for x, y, z in esquinas[:4]))
    print(f"sismo {f['id']}: M{p['mag']} {p['place']} ({lat}, {lon}) prof {prof} km")


if __name__ == "__main__":
    main()
