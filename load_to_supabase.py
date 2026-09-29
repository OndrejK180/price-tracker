"""
Nahrání scrapovaných dat z Datartu do Supabase.

Postup:
1. Spustí scraper (scrape_category z datart_scraper.py) nad zadanou kategorií.
2. UPSERTNE produkty do dim_products - "upsert" = INSERT, nebo pokud produkt
   (product_id) už existuje, UPDATE jeho měnitelných údajů. Díky tomu
   nevytváříme duplicity při opakovaném spuštění, ale zároveň zachytíme,
   když se produktu např. změní název.
3. VLOŽÍ nový řádek pro každý produkt do fact_price_snapshot - tady žádný
   upsert neděláme schválně: každé spuštění = nový "otisk" cen v čase,
   staré řádky se nikdy nepřepisují. Přesně tohle nám umožní později
   počítat vývoj ceny v čase (window funkce LAG/LEAD přes scraped_at).
"""

import pandas as pd
from sqlalchemy import text

from datart_scraper import scrape_category
from db import get_engine

# TODO: časem přesuneme do konfiguračního souboru/CLI argumentu,
# až budeme sledovat víc kategorií najednou.
CATEGORY_URL = "https://www.datart.cz/mobilni-telefony-samsung.html"


def upsert_products(engine, df: pd.DataFrame) -> None:
    """Vloží nové produkty a aktualizuje existující v dim_products."""
    dim_df = df[["product_id", "name", "brand", "url"]].drop_duplicates(
        subset="product_id"
    )

    # ON CONFLICT (product_id) DO UPDATE je Postgres syntax pro upsert.
    # EXCLUDED odkazuje na hodnotu, kterou jsme se snažili vložit (tu novou) -
    # takže "name = EXCLUDED.name" znamená "přepiš name tou novou hodnotou".
    # Všimni si, že first_seen_at v UPDATE vůbec nezmiňujeme - díky tomu
    # se při aktualizaci nepřepíše a zůstane tam datum PRVNÍHO zaznamenání.
    upsert_sql = text("""
        INSERT INTO dim_products (product_id, name, brand, url)
        VALUES (:product_id, :name, :brand, :url)
        ON CONFLICT (product_id) DO UPDATE SET
            name = EXCLUDED.name,
            brand = EXCLUDED.brand,
            url = EXCLUDED.url
    """)

    # engine.begin() otevře transakci a na konci bloku ji sám potvrdí
    # (commit), nebo při chybě vrátí zpět (rollback) - nemůže se tak stát,
    # že by se zapsala jen polovina produktů kvůli chybě uprostřed.
    with engine.begin() as connection:
        connection.execute(upsert_sql, dim_df.to_dict(orient="records"))


def insert_price_snapshots(engine, df: pd.DataFrame) -> None:
    """Přidá nové řádky do fact_price_snapshot (čistý insert, bez upsertu)."""
    fact_df = df[[
        "product_id", "price_czk", "original_price_czk",
        "is_on_sale", "availability_state", "scraped_at",
    ]].copy()

    # scraped_at v DataFrame je zatím text (ISO 8601 string). Explicitní
    # převod na skutečný datetime typ je bezpečnější, než spoléhat na to,
    # že to za nás "nějak" převede driver při zápisu do TIMESTAMPTZ sloupce.
    fact_df["scraped_at"] = pd.to_datetime(fact_df["scraped_at"])

    # to_sql s if_exists="append" přidá řádky na konec existující tabulky
    # (nikdy ji nemaže/nepřepisuje - to by dělalo "replace", které tu
    # záměrně nepoužíváme). method="multi" pošle data v dávkách místo
    # řádek po řádku, což je výrazně rychlejší u větších objemů dat.
    fact_df.to_sql(
        "fact_price_snapshot",
        con=engine,
        if_exists="append",
        index=False,
        method="multi",
    )


if __name__ == "__main__":
    engine = get_engine()

    print("Spouštím scraper...")
    df = scrape_category(CATEGORY_URL)
    print(f"Nascrapováno {len(df)} produktů.")

    print("Ukládám produkty do dim_products...")
    upsert_products(engine, df)

    print("Ukládám cenové snapshoty do fact_price_snapshot...")
    insert_price_snapshots(engine, df)

    print("Hotovo! Data jsou v Supabase.")
