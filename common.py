import os

import psycopg
from pymongo import MongoClient

PG_DSN = os.environ.get("PG_DSN", "host=localhost dbname=library_db user=postgres password=postgres")
MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB = os.environ.get("MONGO_DB", "library_lab2")
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")


def pg_connect(autocommit=True):
    conn = psycopg.connect(PG_DSN, autocommit=autocommit)
    conn.execute("SET search_path TO lab2, public")
    return conn


def mongo_db():
    client = MongoClient(MONGO_URI, w=1, journal=True)
    return client[MONGO_DB]
