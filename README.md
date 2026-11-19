# Resiliencia de la fibra chilena ante el sismo 8.8 del Maule (27-F)

Tarea 2 de Algoritmos de Ruteo y Redes Resilientes (UDP, 2026-2).

Se carga la infraestructura de fibra óptica levantada por el proyecto Yafún (NIC Labs, entregada por SUBTEL en la solicitud T5610), se arma su topología con pgRouting (`prob_falla = 0` por defecto), se calcula el ATTR de los nodos clave, se modela la probabilidad de falla de cada enlace ante el terremoto del 27/02/2010 y se calcula el ATTR después del sismo.

## Requisitos y dependencias

- **Docker**: levanta PostgreSQL 16 + PostGIS 3.4 + pgRouting 3.6.1 (`pgrouting/pgrouting:16-3.4-3.6.1`), requerido por `pgr_nodeNetwork`, `pgr_createTopology` y geometrías en EPSG:4326.
- **Python 3.10 o superior**, con las librerías de `requirements.txt`:

| Librería | Uso en el proyecto |
|---|---|
| `psycopg2-binary` | Conexión y consultas SQL desde Python hacia PostgreSQL/PostGIS |
| `pyshp` | Lectura directa de los shapefiles originales de Yafún (`Respuesta_T5610`) |
| `networkx` | Grafo topológico, árbol mínimo de continuidad (Kruskal), poda de ramas muertas y centralidad |
| `numpy` | Muestreo vectorizado de distancias, malla de ruptura y sorteos de Monte Carlo |
| `scipy` | Árbol espacial `cKDTree` para $R_{rup}$ 3D y cálculo de componentes conexas (`csgraph`) |
| `folium` | Generación del mapa interactivo en Leaflet (`mapa.html` / `mapa_red.html`) |
| `matplotlib` | Gráficos de validación frente al ShakeMap (`src/figura_validacion.py`) |

## Uso en un solo comando

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python main.py             # inicia Docker si hace falta, carga la BD, calcula ATTR y abre el mapa
```

Si prefieres iniciar el contenedor manualmente (o cargar directo desde `main.sql` en una base de datos vacía):

```bash
docker compose up -d
.venv/bin/python main.py --desde-sql # carga main.sql (infraestructura + fallas), calcula ATTR y abre el mapa
# o directo con psql en una BD vacía:
docker exec -i yafun-db psql -U yafun -d yafun -v ON_ERROR_STOP=1 < main.sql
```

Sin `docker compose`:

```bash
docker run -d --name yafun-db -e POSTGRES_DB=yafun -e POSTGRES_USER=yafun \
  -e POSTGRES_PASSWORD=yafun -p 5433:5432 pgrouting/pgrouting:16-3.4-3.6.1
```

Acciones de `main.py`:

| Comando | Qué hace |
|---|---|
| `python main.py cargar` | carga los shapefiles, arma la topología (`prob_falla = 0`), carga el sismo, calcula fallas y exporta `main.sql` |
| `python main.py attr` | ATTR antes y después del sismo (Monte Carlo) para los dos conjuntos de nodos clave |
| `python main.py mapa` | genera `mapa.html` (Leaflet) y lo abre en `http://127.0.0.1:8000/mapa.html` |

Opciones: `--umbral 0.215` (PGA de daño en g), `--huecos 60` (hueco máximo en km que se cierra con enlaces de continuidad), `--sims 10000`, `--vista red` (genera `mapa_red.html` antes del sismo), `--desde-sql` (restaura directamente `main.sql`), `--no-abrir` (solo genera el HTML sin abrir el navegador).

El mapa muestra el umbral guardado con las probabilidades de la BD. Para cambiar de escenario, ejecuta por ejemplo `python main.py --umbral 0.401`. Al restaurar un volcado antiguo sin umbral, el panel indica «sin registrar».

## Estructura

```
main.py                      punto de entrada único
main.sql                     dump autocontenido (infraestructura + probabilidades de falla)
src/db.py                    conexión y arranque automático del contenedor PostgreSQL/pgRouting
src/cargar_fibra.py          shapefiles -> PostGIS
src/topologia.py             pgr_nodeNetwork + pgr_createTopology, huecos, nodos clave, enlaces_red
src/centralidad.py           cruces de mayor centralidad (nodos que intercambian)
src/sismo.py                 sismo y plano de ruptura desde USGS
src/fallas.py                modelo de falla (Youngs et al. 1997), update BD y main.sql
src/attr.py                  ATTR antes y después
src/red_sin_supuestos.py     ATTR sin enlaces de continuidad
src/figura_validacion.py     validación del modelo frente a estaciones del ShakeMap
datos/Respuesta_T5610/       shapefiles de Yafún (SUBTEL)
datos/nodos_clave.csv        ciudades clave y su rol
datos/externos/              USGS (GeoJSON y ShakeMap), cables submarinos, PeeringDB y caché OSM
```

## Tablas en la BD

| Tabla | Contenido |
|---|---|
| `fibra`, `ferry` | capas originales de Yafún |
| `enlaces`, `enlaces_vertices_pgr` | tramos (`prob_falla = 0` inicial) y vértices de `pgr_createTopology` |
| `centralidad` | betweenness de los 253 cruces y los 10 elegidos |
| `nodos_clave` | conjunto principal (27, columna `principal`) y comparación (18 ciudades, columna `ciudades`) |
| `enlaces_red` | enlaces entre nodos de la red (sin ramas muertas, con `prob_falla`) |
| `sismo`, `ruptura` | evento USGS y plano de ruptura del ShakeMap |
| `probabilidad_falla` | resumen por enlace de $R_{rup}$, PGA, probabilidad de falla y umbral utilizado (g) |
