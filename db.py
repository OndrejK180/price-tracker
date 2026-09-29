"""
Sdílený modul pro připojení k Supabase (Postgres) databázi.

Proč samostatný soubor: connection logiku (čtení .env, sestavení URL)
bychom jinak museli kopírovat do každého skriptu, který potřebuje přístup
k databázi (test_connection.py, loader dat, později analytické skripty).
Když se něco změní (např. přejdeme na jiný pooler nebo port), opravíme
to na JEDNOM místě, místo hledání ve všech souborech.
"""

import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.engine import URL, Engine

load_dotenv()

REQUIRED_ENV_VARS = ["DB_USER", "DB_PASSWORD", "DB_HOST", "DB_PORT", "DB_NAME"]


def get_engine() -> Engine:
    """
    Sestaví a vrátí SQLAlchemy engine pro připojení k databázi.

    Podporuje dva formáty v .env:
      1) DATABASE_URL=postgresql://uzivatel:heslo@host:port/db  (jeden řádek)
      2) samostatné proměnné DB_USER, DB_PASSWORD, DB_HOST, DB_PORT, DB_NAME
         (bezpečnější, pokud heslo obsahuje speciální znaky)
    """
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        # Novější verze SQLAlchemy mohou pro obyčejné "postgresql://" (bez
        # explicitně uvedeného ovladače) zkusit sáhnout po psycopg v3 místo
        # psycopg2, kterého máme v requirements.txt. Explicitním "+psycopg2"
        # v adrese tomuhle hádání předejdeme a chování bude vždy stejné,
        # ať skript běží lokálně, nebo na GitHub Actions.
        if database_url.startswith("postgresql://"):
            database_url = database_url.replace(
                "postgresql://", "postgresql+psycopg2://", 1
            )
        return create_engine(database_url)

    missing = [v for v in REQUIRED_ENV_VARS if not os.getenv(v)]
    if missing:
        raise RuntimeError(
            f"V .env chybí proměnné: {', '.join(missing)}. "
            "Zkontroluj DB_USER, DB_PASSWORD, DB_HOST, DB_PORT, DB_NAME."
        )

    connection_url = URL.create(
        drivername="postgresql+psycopg2",
        username=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        host=os.getenv("DB_HOST"),
        port=int(os.getenv("DB_PORT")),
        database=os.getenv("DB_NAME"),
    )
    return create_engine(connection_url)
