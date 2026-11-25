"""
summary.py - sablonove textove shrnuti cenovych trendu (bez AI).

Cte hotove views ze Supabase (v_daily_summary, v_price_index, v_price_daily)
a sklada z nich vety. Funguje vzdy a nepotrebuje API klic.
Funkce build_summary() je oddelena od databaze, aby ji mohl pozdeji
pouzit i Streamlit dashboard.
"""
import re

import pandas as pd


def _datum(d) -> str:
    d = pd.Timestamp(d)
    return f"{d.day}. {d.month}. {d.year}"


def _czk(x) -> str:
    return f"{x:,.0f}".replace(",", " ")


def _pct(x) -> str:
    return f"{x:+.1f}".replace(".", ",") + " %"


def _model(name: str) -> str:
    """Zkrati dlouhy nazev na model + pamet (bez kodu a barvy).

    'Mobilní telefon Samsung Galaxy S25 5G 12 GB / 128 GB (SM-S931B..) černý'
    -> 'Galaxy S25 5G 12 GB / 128 GB'
    """
    name = re.sub(r"^Mobilní telefon Samsung\s+", "", name)
    return name.split(" (")[0].strip()


def _smer(index_value: float) -> str:
    odchylka = f"{abs(100 - index_value):.1f}".replace(".", ",")
    if index_value < 100:
        return f"o {odchylka} % levnější"
    if index_value > 100:
        return f"o {odchylka} % dražší"
    return "beze změny"


def build_summary(daily, index_row, hist, baseline_den, okno_dnu=7) -> str:
    daily = daily.copy()
    daily["den"] = pd.to_datetime(daily["den"])
    hist = hist.copy()
    hist["den"] = pd.to_datetime(hist["den"])
    baseline_den = pd.Timestamp(baseline_den)

    posledni = daily.iloc[0]  # daily je seřazené od nejnovějšího dne
    r = [
        f"Cenový přehled k {_datum(posledni['den'])} "
        f"(sledovaných produktů: {int(posledni['produktu'])})",
        "",
    ]

    # 1) celkový vývoj (cenový index od prvního dne)
    r.append("1) Celkový vývoj od začátku sledování")
    r.append(
        f"Oproti prvnímu dni sledování ({_datum(baseline_den)}) jsou stejné produkty "
        f"v průměru {_smer(float(index_row['index_prum']))} "
        f"(medián {_smer(float(index_row['index_median']))}). "
        f"Počet porovnávaných produktů: {int(index_row['produktu'])} "
        f"(existovaly od začátku sledování)."
    )
    r.append("")

    # 2) poslední snapshot
    r.append("2) Poslední snapshot")
    if len(daily) > 1:
        odstup = (daily.iloc[0]["den"] - daily.iloc[1]["den"]).days
        r.append(
            f"Oproti předchozímu snapshotu (odstup {odstup} d): "
            f"zdražilo {int(posledni['zdrazilo'])}, "
            f"zlevnilo {int(posledni['zlevnilo'])}, "
            f"beze změny {int(posledni['beze_zmeny'])}."
        )
    else:
        r.append("K dispozici je zatím jen jeden snapshot.")
    r.append("")

    # 3) největší jednorázové vlny
    r.append(f"3) Největší jednorázové změny (snapshotů v přehledu: {len(daily)})")
    nalezeno = False
    for sloupec, popis in (("zlevnilo", "zlevnění"), ("zdrazilo", "zdražení")):
        vlna = daily.loc[daily[sloupec].idxmax()]
        if vlna[sloupec] > 0:
            nalezeno = True
            podil = vlna[sloupec] * 100 / vlna["produktu"]
            r.append(
                f"- Nejvíce {popis} najednou: {_datum(vlna['den'])}, "
                f"počet produktů: {int(vlna[sloupec])} ({podil:.0f} % sledovaných)."
            )
    if nalezeno:
        r.append("  Změna mohla nastat kdykoli mezi dvěma po sobě jdoucími snapshoty.")
    else:
        r.append("- Žádné změny cen.")
    r.append("")

    # 4) největší změny cen za okno (varianty téhož modelu sloučené)
    h = hist.sort_values("den")
    posledni_den = h["den"].max()
    prvni_den = h["den"].min()
    r.append(
        f"4) Největší změny cen za poslední období "
        f"({_datum(prvni_den)} až {_datum(posledni_den)})"
    )
    prvni = h.groupby("product_id").first()
    posl = h.groupby("product_id").last()
    zm = prvni[["name", "den", "price_czk"]].join(
        posl[["den", "price_czk"]], lsuffix="_pred", rsuffix="_nyni"
    )
    zm = zm[(zm["den_nyni"] == posledni_den) & (zm["den_pred"] < posledni_den)].copy()
    zm["zmena_pct"] = (zm["price_czk_nyni"] - zm["price_czk_pred"]) * 100 / zm["price_czk_pred"]
    zm = zm[zm["zmena_pct"] != 0]
    zm["model"] = zm["name"].map(_model)
    modely = zm.groupby("model").agg(
        zmena_pct=("zmena_pct", "median"),
        pred=("price_czk_pred", "median"),
        nyni=("price_czk_nyni", "median"),
        varianty=("zmena_pct", "size"),
    )
    if modely.empty:
        r.append("Za toto období se cena žádného produktu nezměnila.")
    else:
        for nadpis, vyber in (
            ("Největší zlevnění:", modely[modely["zmena_pct"] < 0].nsmallest(3, "zmena_pct")),
            ("Největší zdražení:", modely[modely["zmena_pct"] > 0].nlargest(3, "zmena_pct")),
        ):
            if vyber.empty:
                continue
            r.append(nadpis)
            for model, row in vyber.iterrows():
                r.append(
                    f"- {model}: {_czk(row['pred'])} -> {_czk(row['nyni'])} Kč "
                    f"({_pct(row['zmena_pct'])}), počet variant: {int(row['varianty'])}"
                )
    r.append("")

    # 5) sortiment (množinový rozdíl mezi dvěma posledními snapshoty)
    r.append("5) Sortiment")
    dny = sorted(h["den"].unique())
    if len(dny) > 1:
        ted = set(h.loc[h["den"] == dny[-1], "product_id"])
        pred = set(h.loc[h["den"] == dny[-2], "product_id"])
        r.append(
            f"Oproti předchozímu snapshotu: přibylo {len(ted - pred)}, "
            f"ubylo {len(pred - ted)} (počet produktů)."
        )
    else:
        r.append("K dispozici je zatím jen jeden snapshot.")
    r.append("")
    r.append(
        "Poznámka: shrnutí vzniklo automaticky šablonou z dat v databázi. "
        "Příčiny změn cen z dat určit nelze."
    )
    return "\n".join(r)


def main():
    from sqlalchemy import text

    from db import get_engine

    engine = get_engine()
    with engine.connect() as conn:
        daily = pd.read_sql(text("SELECT * FROM v_daily_summary ORDER BY den DESC LIMIT 30"), conn)
        index_row = pd.read_sql(
            text("SELECT * FROM v_price_index ORDER BY den DESC LIMIT 1"), conn
        ).iloc[0]
        baseline = pd.read_sql(text("SELECT MIN(den) AS den FROM v_price_daily"), conn).iloc[0]["den"]
        hist = pd.read_sql(
            text(
                """
                SELECT v.product_id, d.name, v.den, v.price_czk
                FROM v_price_daily v
                JOIN dim_products d USING (product_id)
                WHERE v.den >= (SELECT MAX(den) - 7 FROM v_price_daily)
                """
            ),
            conn,
        )

    summary = build_summary(daily, index_row, hist, baseline)
    print(summary)
    with open("latest_summary.txt", "w", encoding="utf-8") as f:
        f.write(summary)
    print("\n[Uloženo do latest_summary.txt]")


if __name__ == "__main__":
    main()
