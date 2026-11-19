"""Resiliencia de la infraestructura de fibra chilena ante el sismo 8.8 del Maule (2010).

Uso:
    python main.py              carga la BD, calcula todo y abre el mapa
    python main.py cargar       carga la fibra, arma la topologia y carga el sismo y main.sql
    python main.py attr         muestra el ATTR antes y despues del sismo
    python main.py mapa         genera mapa.html (Leaflet) y lo abre en el navegador

Opciones:
    --umbral G     PGA de dano en g (por defecto 0.215, intensidad VII del ShakeMap)
    --huecos KM    hueco maximo que se cierra con enlaces de continuidad (por defecto 60)
    --sims N       simulaciones de Monte Carlo (por defecto 10000)
"""
import argparse
import http.server
import json
import os
import sys
import threading
import webbrowser
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

import attr  # noqa: E402
import cargar_fibra  # noqa: E402
import fallas  # noqa: E402
import sismo  # noqa: E402
import topologia  # noqa: E402
from db import DSN, asegurar_bd, conectar  # noqa: E402


def cargar(args):
    if args.desde_sql:
        cargar_main_sql(ejecutar=True)
        return
    cargar_fibra.main()
    topologia.HUECO_MAX_KM = args.huecos
    topologia.main()
    sismo.main()
    datos = fallas.calcular(args.umbral)
    fallas.actualizar_bd(datos[-1])
    fallas.escribir_sql(*datos)
    print(f"main.sql generado ({len(datos[-1])} enlaces, umbral {args.umbral} g)")
    cargar_main_sql(ejecutar=False)


def cargar_main_sql(ejecutar=True):
    cur = conectar().cursor()
    if ejecutar:
        cur.execute(open("main.sql").read())
    cur.execute("SELECT count(*), round(avg(prob_falla)::numeric, 3) FROM probabilidad_falla")
    n, p = cur.fetchone()
    print(f"main.sql cargado en la BD: {n} enlaces, probabilidad media {p}")


def mostrar_attr(args):
    res = {}
    for conjunto in attr.CONJUNTOS:
        r = attr.calcular(args.sims, conjunto=conjunto)
        k = len(r["nodos"])
        print(f"\n== Nodos clave '{conjunto}': {attr.CONJUNTOS[conjunto]}")
        print(f"{k} nodos ({k * (k - 1) // 2} pares)")
        print(f"ATTR antes del sismo:   {r['antes']:.4f}")
        print(f"ATTR despues del sismo: {r['despues']:.4f} (desv. {r['despues_sd']:.4f}, "
              f"P5 {r['p05']:.4f}, P95 {r['p95']:.4f}, {r['n_sim']} simulaciones)")
        res[conjunto] = r
    return res


def geojson(cur, sql):
    cur.execute(sql)
    cols = [d[0] for d in cur.description]
    feats = []
    for fila in cur.fetchall():
        p = {c: float(v) if isinstance(v, Decimal) else v for c, v in zip(cols, fila)}
        g = p.pop("g")
        feats.append({"type": "Feature", "geometry": json.loads(g), "properties": p})
    return {"type": "FeatureCollection", "features": feats}


def color(p):
    if p >= 0.5:
        return "#c0392b"
    if p >= 0.1:
        return "#e67e22"
    if p >= 0.01:
        return "#f1c40f"
    return "#27ae60"


def mapa(args, res=None):
    import folium

    if res is None:
        res = {c: attr.calcular(args.sims, conjunto=c) for c in attr.CONJUNTOS}
    r, rc = res["principal"], res["ciudades"]
    cur = conectar().cursor()
    m = folium.Map(location=[-36.5, -71.5], zoom_start=6, tiles="OpenStreetMap", control_scale=True)

    fibra = geojson(cur, "SELECT ST_AsGeoJSON(ST_Simplify(geom, 0.0005)) g FROM fibra")
    folium.GeoJson(fibra, name="Fibra levantada (Yafun)",
                   style_function=lambda f: {"color": "#7f8c8d", "weight": 1, "opacity": 0.6}).add_to(m)

    red = geojson(cur, """SELECT ST_AsGeoJSON(ST_Simplify(e.geom, 0.0005)) g, e.id, e.tipo,
                                 round(e.km::numeric, 1) km, round(e.km_supuesto::numeric, 1) km_supuesto,
                                 round(p.rrup_km::numeric, 1) rrup_km, round(p.pga_g::numeric, 3) pga_g,
                                 round(p.prob_falla::numeric, 3) prob_falla
                          FROM enlaces_red e JOIN probabilidad_falla p ON p.id_enlace = e.id""")
    colores_tipo = {"fibra": "#2a78d6", "submarino": "#1baf7a", "supuesto": "#2c3e50"}
    if args.vista == "red":
        estilo = lambda f: {"color": colores_tipo[f["properties"]["tipo"]], "weight": 4, "opacity": 0.9}  # noqa: E731
    else:
        estilo = lambda f: {"color": color(f["properties"]["prob_falla"]), "weight": 4, "opacity": 0.9}  # noqa: E731
    folium.GeoJson(
        red, name="Enlaces de la red" if args.vista == "red" else "Enlaces y probabilidad de falla",
        style_function=estilo,
        tooltip=folium.GeoJsonTooltip(fields=["id", "tipo", "km", "km_supuesto", "rrup_km", "pga_g", "prob_falla"],
                                      aliases=["Enlace", "Tipo", "Largo (km)", "Supuesto (km)", "Rrup (km)",
                                               "PGA (g)", "P(falla)"])).add_to(m)

    sup = geojson(cur, "SELECT ST_AsGeoJSON(geom) g, nombre FROM enlaces WHERE tipo IN ('continuidad', 'acometida')")
    folium.GeoJson(sup, name="Tramos supuestos (huecos y acometidas)",
                   style_function=lambda f: {"color": "#2c3e50", "weight": 2, "dashArray": "6 6"},
                   tooltip=folium.GeoJsonTooltip(fields=["nombre"], aliases=["Supuesto"])).add_to(m)

    rup = geojson(cur, "SELECT ST_AsGeoJSON(geom) g FROM ruptura") if args.vista == "sismo" else None
    if rup:
        folium.GeoJson(rup, name="Ruptura (ShakeMap USGS)",
                       style_function=lambda f: {"color": "#8e44ad", "weight": 2, "fillOpacity": 0.08}).add_to(m)
        cur.execute("SELECT ST_Y(geom), ST_X(geom), magnitud, profundidad_km, lugar FROM sismo")
        lat, lon, mag, prof, lugar = cur.fetchone()
        folium.Marker([lat, lon], tooltip=f"Epicentro M{mag} - {lugar} - {prof} km",
                      icon=folium.Icon(color="purple", icon="star")).add_to(m)

    i_stgo = r["nodos"].index("Santiago")
    colores = {"genera": "red", "intercambia": "blue", "recibe": "green"}
    cur.execute("SELECT nombre, rol_principal, detalle, ST_Y(geom), ST_X(geom) FROM nodos_clave "
                "WHERE principal ORDER BY nombre")
    capa = folium.FeatureGroup(name="Nodos clave").add_to(m)
    for nombre, rol, detalle, la, lo in cur.fetchall():
        j = r["nodos"].index(nombre)
        txt = f"<b>{nombre}</b><br>{rol}: {detalle}"
        if j != i_stgo:
            txt += f"<br>P(sigue conectado con Santiago) = {r['par_ok'][i_stgo, j]:.3f}"
        folium.CircleMarker([la, lo], radius=7, color="black", weight=1, fill=True, fill_opacity=1,
                            fill_color=colores[rol], tooltip=nombre, popup=folium.Popup(txt, max_width=300)).add_to(capa)

    if args.vista == "red":
        panel = f"""
    <div style="position: fixed; bottom: 44px; left: 24px; z-index: 9999; background: white; padding: 10px 14px;
                border: 1px solid #999; border-radius: 6px; font: 13px/1.4 sans-serif;">
      <b>Red en operaci&oacute;n</b><br>ATTR nodos clave ({len(r['nodos'])} nodos): {r['antes']:.3f}<br>
      <span style="font-size:11px">Comparaci&oacute;n, 18 ciudades: {rc['antes']:.3f}</span><hr style="margin:6px 0">
      <span style="color:#2a78d6">&#9644;</span> fibra &nbsp; <span style="color:#1baf7a">&#9644;</span> submarino &nbsp;
      <span style="color:#2c3e50">&#9644;</span> supuesto (- - hueco)<br>
      <span style="color:red">&#9679;</span> genera &nbsp; <span style="color:blue">&#9679;</span> intercambia &nbsp;
      <span style="color:green">&#9679;</span> recibe
    </div>"""
    else:
        panel = f"""
    <div style="position: fixed; bottom: 44px; left: 24px; z-index: 9999; background: white; padding: 10px 14px;
                border: 1px solid #999; border-radius: 6px; font: 13px/1.4 sans-serif;">
      <b>ATTR nodos clave ({len(r['nodos'])} nodos)</b><br>
      Antes del sismo: {r['antes']:.3f}<br>
      Despu&eacute;s del sismo: {r['despues']:.3f} (P5 {r['p05']:.3f} &ndash; P95 {r['p95']:.3f})<br>
      <span style="font-size:11px">Comparaci&oacute;n, 18 ciudades: {rc['antes']:.3f} &rarr; {rc['despues']:.3f}</span><br>
      <span style="font-size:11px">Umbral {args.umbral} g, {r['n_sim']} simulaciones</span><hr style="margin:6px 0">
      <b>P(falla) del enlace</b><br>
      <span style="color:#c0392b">&#9644;</span> &ge; 0.5 &nbsp;
      <span style="color:#e67e22">&#9644;</span> 0.1&ndash;0.5 &nbsp;
      <span style="color:#f1c40f">&#9644;</span> 0.01&ndash;0.1 &nbsp;
      <span style="color:#27ae60">&#9644;</span> &lt; 0.01<br>
      <span style="color:red">&#9679;</span> genera &nbsp; <span style="color:blue">&#9679;</span> intercambia &nbsp;
      <span style="color:green">&#9679;</span> recibe
    </div>"""
    m.get_root().html.add_child(folium.Element(panel))
    folium.LayerControl(collapsed=False).add_to(m)
    salida = "mapa.html" if args.vista == "sismo" else "mapa_red.html"
    m.save(salida)
    print(f"{salida} generado")


def servir(pagina="mapa.html", puerto=8000):
    handler = lambda *a: http.server.SimpleHTTPRequestHandler(*a, directory=os.getcwd())  # noqa: E731
    srv = None
    for p in range(puerto, puerto + 20):
        try:
            srv = http.server.ThreadingHTTPServer(("127.0.0.1", p), handler)
            puerto = p
            break
        except OSError:
            continue
    if srv is None:
        raise SystemExit(f"No se encontro puerto libre desde {puerto}")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{puerto}/{pagina}"
    print(f"mapa en {url} (Ctrl+C para salir)")
    webbrowser.open(url)
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        srv.shutdown()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("accion", nargs="?", default="todo", choices=["todo", "cargar", "attr", "mapa"])
    ap.add_argument("--umbral", type=float, default=0.215)
    ap.add_argument("--huecos", type=float, default=60.0)
    ap.add_argument("--sims", type=int, default=10000)
    ap.add_argument("--vista", choices=["sismo", "red"], default="sismo",
                    help="sismo: probabilidad de falla (mapa.html); red: red antes del sismo (mapa_red.html)")
    ap.add_argument("--desde-sql", action="store_true",
                    help="carga la BD directamente desde main.sql en lugar de reprocesar los shapefiles")
    ap.add_argument("--no-abrir", action="store_true", help="no levanta el servidor del mapa")
    args = ap.parse_args()
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    print(f"BD: {DSN.split('password')[0].strip()}")
    asegurar_bd()

    if args.accion in ("todo", "cargar"):
        cargar(args)
    r = None
    if args.accion in ("todo", "attr"):
        r = mostrar_attr(args)
    if args.accion in ("todo", "mapa"):
        mapa(args, r)
        if not args.no_abrir:
            servir("mapa.html" if args.vista == "sismo" else "mapa_red.html")


if __name__ == "__main__":
    main()
