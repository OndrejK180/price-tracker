"""
Datart.cz - scraper cen produktů z kategorie
=============================================

Princip:
--------
Datart si do každé produktové karty vkládá atribut `data-gtm-data-product`
obsahující JSON, který používají pro Google Analytics (e-commerce tracking).
My tento JSON využijeme jako "API zdarma" - je to mnohem spolehlivější
než parsovat viditelný text ceny (např. "4 990 Kč"), protože:
  1) nemusíme řešit formátování (mezery, měna, desetinné oddělovače)
  2) JSON obsahuje i strukturovaná data jako brand, dostupnost, rating
  3) tahle GTM data se mění méně často než CSS třídy použité pro vzhled

Poznámka k etice/legalitě:
---------------------------
- robots.txt byl zkontrolován, kategorie a produktové stránky nejsou
  v Disallow, takže scraping je v souladu s pravidly webu.
- Přesto: děláme jen NÍZKOFREKVENČNÍ požadavky (sleep mezi requesty),
  nastavujeme si vlastní User-Agent (transparentnost, ne předstírání
  prohlížeče) a nescrapujeme rychleji, než by to dělal běžný návštěvník.
"""

import json
import re
import time
from datetime import datetime, timezone
from urllib.parse import urljoin

import pandas as pd
import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.datart.cz"

# --- Konfigurace -----------------------------------------------------------

# Vlastní User-Agent: dobrá praxe je se "podepsat", ne se vydávat za
# běžný prohlížeč. Pokud by administrátor webu chtěl vědět, kdo mu
# generuje provoz, může nás dohledat/kontaktovat.
HEADERS = {
    "User-Agent": "PriceTrackerBot/0.1 (osobni analyticky projekt; kontakt: ondrejjkysely@gmail.com)"
}

# Zpoždění mezi jednotlivými požadavky (sekundy) - šetrnost k serveru.
REQUEST_DELAY_SECONDS = 2


def fetch_page(url: str) -> str:
    """Stáhne HTML dané stránky a vrátí ho jako text."""
    response = requests.get(url, headers=HEADERS, timeout=15)
    # raise_for_status() vyhodí výjimku, pokud server vrátí chybu (4xx/5xx).
    # Bez tohohle bychom mohli tiše zpracovávat prázdnou/chybovou stránku.
    response.raise_for_status()
    return response.text


def _parse_czk_price(text: str) -> int | None:
    """
    Vytáhne z textu jako "5 990 Kč" celé číslo 5990.

    Používáme regex [^\\d] ("cokoliv, co NENÍ číslice") a smažeme to -
    zbydou jen číslice, které pak spojíme zpátky do jednoho čísla.
    Funguje to bez ohledu na to, jestli je oddělovač mezera, tvrdá
    mezera (non-breaking space) nebo něco jiného.
    """
    digits = re.sub(r"[^\d]", "", text)
    return int(digits) if digits else None


def extract_products_from_html(html: str) -> list[dict]:
    """
    Najde všechny produktové karty na stránce a vrátí seznam slovníků
    s daty o produktu (z GTM JSON atributu).
    """
    soup = BeautifulSoup(html, "html.parser")

    # Najdeme VŠECHNY elementy, které mají atribut data-gtm-data-product,
    # bez ohledu na jejich CSS třídu (top-product-box, product-box, ...).
    # To nás chrání před tím, aby nám kód "spadl", když web bude mít
    # na jiné stránce trochu jinak pojmenovaný wrapper.
    product_elements = soup.find_all(attrs={"data-gtm-data-product": True})

    products = []
    for element in product_elements:
        raw_json = element["data-gtm-data-product"]
        try:
            product_data = json.loads(raw_json)
        except json.JSONDecodeError:
            # Pokud by byl JSON poškozený/neúplný, tenhle produkt přeskočíme,
            # ale neshodíme celý běh scraperu kvůli jedné vadné kartě.
            continue

        # URL produktu vezmeme z <a href="..."> uvnitř karty.
        link_tag = element.find("a", href=True)
        product_url = link_tag["href"] if link_tag else None

        # Pokud je produkt zlevněný, Datart vypisuje původní cenu
        # přeškrtnutou v <span class="cut-price">. U produktů bez akce
        # je tenhle span v HTML přítomný, ale prázdný - proto kontrolujeme
        # i to, že text po vyčištění skutečně obsahuje nějaké číslice.
        cut_price_tag = element.find(class_="cut-price")
        original_price_czk = (
            _parse_czk_price(cut_price_tag.get_text()) if cut_price_tag else None
        )
        current_price_czk = product_data.get("price")
        is_on_sale = bool(original_price_czk and original_price_czk > (current_price_czk or 0))

        products.append({
            "product_id": product_data.get("item_id"),
            "name": product_data.get("item_name"),
            "brand": product_data.get("item_brand"),
            "price_czk": current_price_czk,
            "original_price_czk": original_price_czk if is_on_sale else None,
            "is_on_sale": is_on_sale,
            "price_type": product_data.get("type_price"),
            "availability_state": product_data.get("item_availability_state"),
            "availability_store": product_data.get("item_availability_store"),
            "rating": product_data.get("item_rating"),
            "rating_count": product_data.get("item_rating_quantity"),
            "url": urljoin(BASE_URL, product_url) if product_url else None,
            "scraped_at": datetime.now(timezone.utc).isoformat(),
        })

    return products


def get_next_page_url(html: str, current_url: str) -> str | None:
    """
    Vrátí absolutní URL další stránky, pokud existuje, jinak None.

    Proč hledáme podle třídy "next-page" místo posledního čísla stránky:
    Datart u dlouhých výpisů schovává prostřední čísla za "..." (viz HTML:
    stránky 1, 2, 3, "...", 7). Poslední VIDITELNÉ číslo (7) tedy nemusí
    být poslední SKUTEČNÁ stránka - ta trojtečka může skrývat další.
    Spolehlivější je jít podle odkazu "Další", dokud existuje - to je
    to samé, co by dělal člověk klikající myší.
    """
    soup = BeautifulSoup(html, "html.parser")

    # Když je "Další" ještě aktivní odkaz (<a>), má třídu "next-page".
    # Když jsme na poslední stránce, tenhle odkaz v HTML vůbec nebude
    # (nebo bude jako neaktivní <span>, ne <a> s href).
    next_link = soup.select_one("a.next-page")
    if next_link and next_link.get("href"):
        return urljoin(current_url, next_link["href"])
    return None


def scrape_category(start_url: str, max_pages: int = 50) -> pd.DataFrame:
    """
    Projde celou kategorii (všechny stránky) a vrátí DataFrame s produkty.

    max_pages je pojistka proti nekonečné smyčce - kdyby web měl chybu
    a odkaz "Další" pořád ukazoval na sebe sama, po 50 stránkách skript
    stejně skončí, místo aby běžel navěky.
    """
    all_products = []
    current_url = start_url
    page_number = 1

    while current_url and page_number <= max_pages:
        print(f"Stahuji stránku {page_number}: {current_url}")
        html = fetch_page(current_url)

        products = extract_products_from_html(html)
        all_products.extend(products)

        next_url = get_next_page_url(html, current_url)

        # Pojistka: kdyby "další" odkaz náhodou ukazoval na stejnou URL
        # (chyba na webu), radši smyčku ukončíme, než abychom se zacyklili.
        if next_url == current_url:
            break

        current_url = next_url
        page_number += 1

        if current_url:
            # Zpoždění DÁVÁME AŽ SEM (ne na začátek smyčky) - šetříme čas,
            # protože po poslední stránce už žádné čekání není potřeba.
            time.sleep(REQUEST_DELAY_SECONDS)

    df = pd.DataFrame(all_products)

    # Jeden společný časový otisk pro celý běh. Dřív měl každý produkt
    # vlastní timestamp (rozdíly v řádu sekund/mikrosekund), takže by se
    # "jeden běh scraperu" v databázi nedal snadno identifikovat.
    # Se společným run_ts můžeme později jednoduše dělat GROUP BY scraped_at
    # nebo porovnávat "dnešní snapshot" s "včerejším".
    if not df.empty:
        df["scraped_at"] = datetime.now(timezone.utc).isoformat()

    # Na první stránce kategorie bývá navíc widget "Nejprodávanější",
    # jehož produkty se pak znovu objeví i v hlavním výpisu na stejné
    # stránce -> bez tohohle bychom měli duplicity. product_id je
    # jednoznačný identifikátor, takže podle něj bezpečně odduplikujeme.
    if not df.empty:
        before = len(df)
        df = df.drop_duplicates(subset="product_id", keep="first").reset_index(drop=True)
        removed = before - len(df)
        if removed:
            print(f"Odstraněno {removed} duplicitních záznamů (bestseller widget).")

    return df


if __name__ == "__main__":
    # TODO: sem vlož skutečnou URL kategorie, kterou budeme sledovat
    CATEGORY_URL = "https://www.datart.cz/NAHRAD-SKUTECNOU-URL-KATEGORIE.html"

    df = scrape_category(CATEGORY_URL)

    print(f"Nalezeno produktů: {len(df)}")
    print(df.head())

    # Zatím ukládáme do CSV - v dalším kroku přesuneme do cloudové DB.
    output_filename = f"datart_prices_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
    df.to_csv(output_filename, index=False, encoding="utf-8-sig")
    print(f"Uloženo do: {output_filename}")
