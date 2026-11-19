# Resiliencia de la fibra chilena ante el sismo 8.8 del Maule

Tarea 2 de Algoritmos de Ruteo y Redes Resilientes (UDP, 2026-2).

Se carga la infraestructura de fibra óptica levantada por el proyecto Yafún (NIC Labs, entregada por SUBTEL en la solicitud T5610), se arma su topología con pgRouting, se calcula el ATTR de los nodos clave, se modela la probabilidad de falla de cada enlace ante el sismo 8.8 del 27/02/2010 y se calcula el ATTR después del sismo.

## Requisitos

- Docker
- Python 3.10 o superior

## Uso

```bash
docker compose up -d                 # PostgreSQL 16 + PostGIS 3.4 + pgRouting 3.6
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python main.py             # carga la BD, calcula el ATTR y abre el mapa
```

Sin `docker compose`:

```bash
docker run -d --name yafun-db -e POSTGRES_DB=yafun -e POSTGRES_USER=yafun \
  -e POSTGRES_PASSWORD=yafun -p 5433:5432 pgrouting/pgrouting:16-3.4-3.6.1
```

Acciones de `main.py`:

| Comando | Qué hace |
|---|---|
| `python main.py cargar` | carga los shapefiles, arma la topología, carga el sismo y genera y carga `main.sql` |
| `python main.py attr` | ATTR antes y después del sismo (Monte Carlo) para los dos conjuntos de nodos clave |
| `python main.py mapa` | genera `mapa.html` (Leaflet) y lo abre en `http://127.0.0.1:8000/mapa.html` |

Opciones: `--umbral 0.215` (PGA de daño en g), `--huecos 60` (hueco máximo en km que se cierra con enlaces de continuidad), `--sims 10000`, `--vista red` (genera `mapa_red.html` antes del sismo), `--no-abrir` (solo genera el HTML sin abrir el navegador).

## Estructura

```
main.py                 punto de entrada
main.sql                probabilidad de falla de cada enlace (generado)
src/cargar_fibra.py     shapefiles -> PostGIS
src/topologia.py        pgr_nodeNetwork + pgr_createTopology, huecos, nodos clave, enlaces_red
src/centralidad.py      cruces de mayor centralidad (nodos que intercambian)
src/sismo.py            sismo y plano de ruptura desde USGS
src/fallas.py           modelo de falla (Youngs et al. 1997) y main.sql
src/attr.py             ATTR antes y después
src/red_sin_supuestos.py ATTR sin enlaces de continuidad
src/figura_validacion.py validación del modelo frente a estaciones del ShakeMap
datos/Respuesta_T5610/  shapefiles de Yafún (SUBTEL)
datos/nodos_clave.csv   ciudades clave y su rol
datos/externos/         USGS (GeoJSON y ShakeMap), cables submarinos y caché OSM
```

## Tablas en la BD

| Tabla | Contenido |
|---|---|
| `fibra`, `ferry` | capas originales de Yafún |
| `enlaces`, `enlaces_vertices_pgr` | tramos y vértices de `pgr_createTopology` |
| `centralidad` | betweenness de los 253 cruces y los 10 elegidos |
| `nodos_clave` | conjunto principal (27, columna `principal`) y comparación (18 ciudades, columna `ciudades`) |
| `enlaces_red` | enlaces entre nodos de la red (sin ramas muertas) |
| `sismo`, `ruptura` | evento USGS y plano de ruptura del ShakeMap |
| `probabilidad_falla` | cargada desde `main.sql` |
