"""
Test připojení k Supabase (Postgres) databázi.

Nečte a nezapisuje žádná reálná data - jen ověří, že připojení
funguje a že vidíme naše dvě tabulky.
"""

from sqlalchemy import text

from db import get_engine

engine = get_engine()

# Skutečné připojení se stane až tady, uvnitř "with" bloku.
# connect() automaticky připojení zase zavře, i kdyby nastala chyba.
with engine.connect() as connection:
    result = connection.execute(text("SELECT NOW();"))
    server_time = result.scalar()
    print(f"Připojení funguje! Aktuální čas na serveru: {server_time}")

    # Ověříme, že vidíme naše tabulky.
    tables_result = connection.execute(text("""
        SELECT table_name FROM information_schema.tables
        WHERE table_schema = 'public';
    """))
    table_names = [row[0] for row in tables_result]
    print(f"Nalezené tabulky: {table_names}")
