import os
import psycopg2

DSN = os.environ.get("YAFUN_DSN", "host=localhost port=5433 dbname=yafun user=yafun password=yafun")


def conectar():
    con = psycopg2.connect(DSN)
    con.autocommit = True
    return con
