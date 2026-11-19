"""Conexion y arranque automatico de la base de datos PostGIS/pgRouting."""
import os
import shutil
import subprocess
import time

import psycopg2

DSN = os.environ.get("YAFUN_DSN", "host=localhost port=5433 dbname=yafun user=yafun password=yafun")


def conectar():
    con = psycopg2.connect(DSN)
    con.autocommit = True
    return con


def asegurar_bd(timeout=30):
    """Verifica conexion a PostgreSQL; si no responde, inicia el contenedor Docker."""
    try:
        conectar().close()
        return
    except psycopg2.OperationalError:
        pass

    if "YAFUN_DSN" not in os.environ and os.path.exists("docker-compose.yml") and shutil.which("docker"):
        print("Iniciando contenedor PostGIS/pgRouting...")
        for cmd in (["docker", "start", "yafun-db"],
                    ["docker", "compose", "up", "-d"],
                    ["docker-compose", "up", "-d"]):
            if not shutil.which(cmd[0]):
                continue
            try:
                res = subprocess.run(cmd, check=False, capture_output=True, text=True)
            except OSError:
                continue
            if res.returncode == 0:
                break

    for _ in range(timeout):
        time.sleep(1)
        try:
            conectar().close()
            return
        except psycopg2.OperationalError:
            continue
    raise SystemExit(f"No se pudo conectar a PostgreSQL ({DSN}) despues de {timeout} s.")
