#!/usr/bin/env python3
"""Builds beer.db: craft beer database.

Sources:
  - Beer_data.xlsx (BeerAdvocate, 3,197 craft beers, 934 breweries,
    111 styles, 0-100 sensory profile + reviews)
  - bjcp_styleguide-2021.json (BJCP 2021 taxonomy, 110 styles with aroma,
    flavor, IBU/OG/FG/ABV/SRM ranges)
  - PunkAPI v3 (415 BrewDog beers with hops, malts and yeast)

Output: beer.db (SQLite) + beers_fts (full-text search)
"""
import json
import re
import sqlite3
import urllib.request
from pathlib import Path

import openpyxl

ROOT = Path(__file__).parent
DATA = ROOT / "data"
DB_PATH = ROOT / "beer.db"
PUNKAPI_DIR = DATA / "punkapi"

PUNKAPI_BASE = "https://punkapi.dev/api/v3/beers?page="

# ---------------------------------------------------------------- mojibake ---
def fix_mojibake(s):
    """Repairs UTF-8 wrongly decoded as MacRoman (K√∂lsch -> Kölsch)."""
    if not s or not isinstance(s, str):
        return s
    if "√" not in s and "Œ" not in s and "√" not in s:
        return s
    try:
        return s.encode("mac_roman").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return s

# --------------------------------------------- BeerAdvocate -> BJCP mapping ---
STYLE_MAP = {
    "Altbier": "Altbier",
    "Barleywine - American": "American Barleywine",
    "Barleywine - English": "English Barley Wine",
    "Bitter - English": "Best Bitter",
    "Bitter - English Extra Special / Strong Bitter (ESB)": "Strong Bitter",
    "Bière de Champagne / Bière Brut": None,
    "Bi√®re de Champagne / Bi√®re Brut": None,  # mojibake of 'Bière de Champagne'
    "Blonde Ale - American": "Blonde Ale",
    "Blonde Ale - Belgian": "Belgian Blond Ale",
    "Bock - Doppelbock": "Doppelbock",
    "Bock - Eisbock": "Eisbock",
    "Bock - Maibock": "Helles Bock",
    "Bock - Traditional": "Dunkles Bock",
    "Bock - Weizenbock": "Weizenbock",
    "Braggot": "Mixed-Style Beer",
    "Brett Beer": "Brett Beer",
    "Brown Ale - American": "American Brown Ale",
    "Brown Ale - Belgian Dark": None,
    "Brown Ale - English": "British Brown Ale",
    "California Common / Steam Beer": "California Common",
    "Chile Beer": "Spice, Herb, or Vegetable Beer",
    "Cream Ale": "Cream Ale",
    "Dubbel": "Belgian Dubbel",
    "Farmhouse Ale - Bière de Garde": "Bière de Garde",
    "Farmhouse Ale - Bi√®re de Garde": "Bière de Garde",  # mojibake of 'Bière de Garde'
    "Farmhouse Ale - Sahti": None,
    "Farmhouse Ale - Saison": "Saison",
    "Fruit and Field Beer": "Fruit Beer",
    "Gruit / Ancient Herbed Ale": "Spice, Herb, or Vegetable Beer",
    "Happoshu": None,
    "Herb and Spice Beer": "Spice, Herb, or Vegetable Beer",
    "IPA - American": "American IPA",
    "IPA - Belgian": "Specialty IPA",
    "IPA - Black / Cascadian Dark Ale": "Specialty IPA",
    "IPA - English": "English IPA",
    "IPA - Imperial": "Double IPA",
    "IPA - New England": "Hazy IPA",
    "Kvass": None,
    "Kölsch": "Kölsch",
    "K√∂lsch": "Kölsch",  # mojibake of 'Kölsch'
    "Lager - Adjunct": "International Pale Lager",
    "Lager - American": "American Lager",
    "Lager - American Amber / Red": "International Amber Lager",
    "Lager - European / Dortmunder Export": "German Helles Exportbier",
    "Lager - European Dark": "International Dark Lager",
    "Lager - European Pale": "International Pale Lager",
    "Lager - European Strong": None,
    "Lager - Helles": "Munich Helles",
    "Lager - India Pale Lager (IPL)": "Specialty IPA",
    "Lager - Japanese Rice": "International Pale Lager",
    "Lager - Kellerbier / Zwickelbier": None,
    "Lager - Light": "American Light Lager",
    "Lager - Malt Liquor": None,
    "Lager - Munich Dunkel": "Munich Dunkel",
    "Lager - Märzen / Oktoberfest": "Märzen",
    "Lager - M√§rzen / Oktoberfest": "Märzen",  # mojibake of 'Märzen / Oktoberfest'
    "Lager - Rauchbier": "Rauchbier",
    "Lager - Schwarzbier": "Schwarzbier",
    "Lager - Vienna": "Vienna Lager",
    "Lambic - Faro": None,
    "Lambic - Fruit": "Fruit Lambic",
    "Lambic - Gueuze": "Gueuze",
    "Lambic - Traditional": "Lambic",
    "Low Alcohol Beer": None,
    "Mild Ale - English Dark": "Dark Mild",
    "Mild Ale - English Pale": "Dark Mild",
    "Old Ale": "Old Ale",
    "Pale Ale - American": "American Pale Ale",
    "Pale Ale - Belgian": "Belgian Pale Ale",
    "Pale Ale - English": "Best Bitter",
    "Pilsner - Bohemian / Czech": "Czech Premium Pale Lager",
    "Pilsner - German": "German Pils",
    "Pilsner - Imperial": None,
    "Porter - American": "American Porter",
    "Porter - Baltic": "Baltic Porter",
    "Porter - English": "English Porter",
    "Porter - Imperial": None,
    "Porter - Robust": "American Porter",
    "Porter - Smoked": "Specialty Smoked Beer",
    "Pumpkin Beer": "Autumn Seasonal Beer",
    "Quadrupel (Quad)": "Belgian Dark Strong Ale",
    "Red Ale - American Amber / Red": "American Amber Ale",
    "Red Ale - Imperial": "American Strong Ale",
    "Red Ale - Irish": "Irish Red Ale",
    "Rye Beer": None,
    "Rye Beer - Roggenbier": None,
    "Scotch Ale / Wee Heavy": "Wee Heavy",
    "Scottish Ale": "Scottish Export",
    "Smoked Beer": "Specialty Smoked Beer",
    "Sour - Berliner Weisse": "Berliner Weisse",
    "Sour - Flanders Oud Bruin": "Oud Bruin",
    "Sour - Flanders Red Ale": "Flanders Red Ale",
    "Sour - Gose": "Gose",
    "Stout - American": "American Stout",
    "Stout - American Imperial": "Imperial Stout",
    "Stout - English": None,
    "Stout - Foreign / Export": "Foreign Extra Stout",
    "Stout - Irish Dry": "Irish Stout",
    "Stout - Oatmeal": "Oatmeal Stout",
    "Stout - Russian Imperial": "Imperial Stout",
    "Stout - Sweet / Milk": "Sweet Stout",
    "Strong Ale - American": "American Strong Ale",
    "Strong Ale - Belgian Dark": "Belgian Dark Strong Ale",
    "Strong Ale - Belgian Pale": "Belgian Pale Ale",
    "Strong Ale - English": "British Strong Ale",
    "Tripel": "Belgian Tripel",
    "Wheat Beer - American Dark": "American Wheat Beer",
    "Wheat Beer - American Pale": "American Wheat Beer",
    "Wheat Beer - Dunkelweizen": "Dunkles Weissbier",
    "Wheat Beer - Hefeweizen": "Weissbier",
    "Wheat Beer - Kristallweizen": "Weissbier",
    "Wheat Beer - Wheatwine": "Wheatwine",
    "Wheat Beer - Witbier": "Witbier",
    "Wild Ale": "Wild Specialty Beer",
    "Winter Warmer": "Winter Seasonal Beer",
}

# ------------------------------------------------------------------ schema ---
SCHEMA = """
PRAGMA journal_mode = WAL;

CREATE TABLE styles_bjcp (
    style_id            TEXT PRIMARY KEY,          -- '18B'
    name                TEXT NOT NULL,             -- 'American Pale Ale'
    category            TEXT,
    category_id         TEXT,
    category_description TEXT,
    type                TEXT,                      -- ale / lager / mixed
    overall_impression  TEXT,
    aroma               TEXT,
    appearance          TEXT,
    flavor              TEXT,
    mouthfeel           TEXT,
    comments            TEXT,
    history             TEXT,
    style_comparison    TEXT,
    tags                TEXT,                      -- JSON array
    ibu_min             REAL,
    ibu_max             REAL,
    og_min              REAL,
    og_max              REAL,
    fg_min              REAL,
    fg_max              REAL,
    abv_min             REAL,
    abv_max             REAL,
    srm_min             REAL,
    srm_max             REAL,
    examples            TEXT,                      -- JSON array
    style_guide         TEXT
);

CREATE TABLE breweries (
    id   INTEGER PRIMARY KEY,
    name TEXT UNIQUE NOT NULL
);

CREATE TABLE beers (
    id                INTEGER PRIMARY KEY,
    name              TEXT NOT NULL,
    full_name         TEXT,                        -- 'Brewery Beer'
    style_label       TEXT,                        -- original BeerAdvocate label
    style_id          TEXT REFERENCES styles_bjcp(style_id),
    brewery_id        INTEGER REFERENCES breweries(id),
    abv               REAL,
    ibu_min           REAL,
    ibu_max           REAL,
    tagline           TEXT,
    description       TEXT,
    yeast             TEXT,
    -- sensory profile 0-100 (higher = more present)
    astringency       INTEGER,
    body              INTEGER,
    alcohol           INTEGER,
    bitter            INTEGER,
    sweet             INTEGER,
    sour              INTEGER,
    salty             INTEGER,
    fruits            INTEGER,
    hoppy             INTEGER,
    spices            INTEGER,
    malty             INTEGER,
    -- BeerAdvocate ratings 0-5
    review_aroma      REAL,
    review_appearance REAL,
    review_palate     REAL,
    review_taste      REAL,
    review_overall    REAL,
    n_reviews         INTEGER,
    cluster_name      TEXT,                        -- study cluster (e.g. 'Hoppy / Dry')
    first_brewed      TEXT,
    image             TEXT,
    source            TEXT NOT NULL                -- 'beeradvocate' | 'punkapi'
);

CREATE TABLE beer_hops (
    beer_id  INTEGER NOT NULL REFERENCES beers(id) ON DELETE CASCADE,
    hop      TEXT NOT NULL,
    amount_g REAL,
    use      TEXT,                                 -- bittering / flavour / aroma
    purpose  TEXT
);
CREATE INDEX idx_hops_hop     ON beer_hops(hop);
CREATE INDEX idx_hops_beer    ON beer_hops(beer_id);

CREATE TABLE beer_malts (
    beer_id  INTEGER NOT NULL REFERENCES beers(id) ON DELETE CASCADE,
    malt     TEXT NOT NULL,
    amount_g REAL
);
CREATE INDEX idx_malts_beer ON beer_malts(beer_id);

CREATE INDEX idx_beers_style   ON beers(style_id);
CREATE INDEX idx_beers_brewery ON beers(brewery_id);
CREATE INDEX idx_beers_source  ON beers(source);

CREATE VIRTUAL TABLE beers_fts USING fts5(
    name, tagline, description, style_label, aroma,
    content='',                                    -- no external table; populated manually
    tokenize='unicode61 remove_diacritics 2'
);

-- View ready for the recommender agent: one row per beer with everything joined
CREATE VIEW v_beers AS
SELECT
    b.id, b.name, b.full_name, b.brewery_id, br.name AS brewery,
    b.style_label, b.style_id, s.name AS style_bjcp, s.category AS style_category,
    b.abv, b.ibu_min, b.ibu_max, b.tagline, b.description, b.yeast,
    b.astringency, b.body, b.alcohol, b.bitter, b.sweet, b.sour, b.salty,
    b.fruits, b.hoppy, b.spices, b.malty,
    b.review_aroma, b.review_appearance, b.review_palate, b.review_taste,
    b.review_overall, b.n_reviews, b.cluster_name, b.source,
    s.ibu_min AS style_ibu_min, s.ibu_max AS style_ibu_max,
    s.abv_min AS style_abv_min, s.abv_max AS style_abv_max,
    s.aroma AS style_aroma, s.flavor AS style_flavor,
    s.mouthfeel AS style_mouthfeel, s.overall_impression AS style_overall
FROM beers b
LEFT JOIN styles_bjcp s ON s.style_id = b.style_id
LEFT JOIN breweries br ON br.id = b.brewery_id;
"""


def load_bjcp():
    data = json.load(open(DATA / "bjcp_styleguide-2021.json"))["beerjson"]["styles"]
    return data


def range_of(x):
    if not isinstance(x, dict):
        return (None, None)
    lo = x.get("minimum") or {}
    hi = x.get("maximum") or {}
    return (lo.get("value"), hi.get("value"))


def num(x):
    return float(x) if x is not None else None


def build_styles(cur, bjcp):
    for s in bjcp:
        ibu_lo, ibu_hi = range_of(s.get("international_bitterness_units"))
        og_lo, og_hi = range_of(s.get("original_gravity"))
        fg_lo, fg_hi = range_of(s.get("final_gravity"))
        abv_lo, abv_hi = range_of(s.get("alcohol_by_volume"))
        srm_lo, srm_hi = range_of(s.get("color"))
        cur.execute(
            """INSERT INTO styles_bjcp VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                s["style_id"], s["name"], s.get("category"), s.get("category_id"),
                s.get("category_description"), s.get("type"),
                s.get("overall_impression"), s.get("aroma"), s.get("appearance"),
                s.get("flavor"), s.get("mouthfeel"), s.get("comments"),
                s.get("history"), s.get("style_comparison"),
                json.dumps(s.get("tags", []), ensure_ascii=False),
                ibu_lo, ibu_hi, og_lo, og_hi, fg_lo, fg_hi,
                abv_lo, abv_hi, srm_lo, srm_hi,
                json.dumps(s.get("examples", []), ensure_ascii=False),
                s.get("style_guide"),
            ),
        )


def build_beeradvocate(cur):
    wb = openpyxl.load_workbook(DATA / "Beer_data.xlsx", read_only=True)
    ws = wb[wb.sheetnames[0]]
    rows = ws.iter_rows(values_only=True)
    header = [fix_mojibake(str(h)) for h in next(rows)]
    idx = {h: i for i, h in enumerate(header)}
    bjcp_names = {r[1]: r[0] for r in cur.execute("SELECT style_id, name FROM styles_bjcp")}

    brewery_ids = {}
    unmatched = {}

    def brewery_id(name):
        if name not in brewery_ids:
            cur.execute("INSERT INTO breweries(name) VALUES (?)", (name,))
            brewery_ids[name] = cur.lastrowid
        return brewery_ids[name]

    count = 0
    for r in rows:
        name = fix_mojibake(r[idx["Name"]])
        if not name:
            continue
        style_label = fix_mojibake(r[idx["Style"]])
        mapped = STYLE_MAP.get(style_label, None)
        style_id = bjcp_names.get(mapped) if mapped else None
        if style_label and style_label not in STYLE_MAP:
            unmatched[style_label] = unmatched.get(style_label, 0) + 1
        brewery = fix_mojibake(r[idx["Brewery"]])
        cur.execute(
            """INSERT INTO beers (name, full_name, style_label, style_id, brewery_id,
                 abv, ibu_min, ibu_max, description,
                 astringency, body, alcohol, bitter, sweet, sour, salty,
                 fruits, hoppy, spices, malty,
                 review_aroma, review_appearance, review_palate,
                 review_taste, review_overall, n_reviews, cluster_name, source)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                name,
                fix_mojibake(r[idx["Beer.Name..Full."]]),
                style_label,
                style_id,
                brewery_id(brewery) if brewery else None,
                num(r[idx["ABV"]]),
                num(r[idx["Min.IBU"]]),
                num(r[idx["Max.IBU"]]),
                r[idx["Description"]],
                r[idx["Astringency"]], r[idx["Body"]], r[idx["Alcohol"]],
                r[idx["Bitter"]], r[idx["Sweet"]], r[idx["Sour"]], r[idx["Salty"]],
                r[idx["Fruits"]], r[idx["Hoppy"]], r[idx["Spices"]], r[idx["Malty"]],
                num(r[idx["review_aroma"]]), num(r[idx["review_appearance"]]),
                num(r[idx["review_palate"]]), num(r[idx["review_taste"]]),
                num(r[idx["review_overall"]]), r[idx["number_of_reviews"]],
                fix_mojibake(r[idx["clus_name"]]),
                "beeradvocate",
            ),
        )
        count += 1
    return count, unmatched


def fetch_punkapi():
    PUNKAPI_DIR.mkdir(exist_ok=True)
    all_beers, page = [], 1
    while True:
        f = PUNKAPI_DIR / f"beers_p{page}.json"
        if not f.exists():
            with urllib.request.urlopen(PUNKAPI_BASE + str(page), timeout=30) as resp:
                data = json.load(resp)
            if not data:
                break
            f.write_text(json.dumps(data, ensure_ascii=False))
        else:
            data = json.loads(f.read_text())
        if not data:
            break
        all_beers.extend(data)
        page += 1
    return all_beers


def g(amount):
    """Converts a PunkAPI amount to grams."""
    if not isinstance(amount, dict):
        return None
    v = amount.get("value")
    if v is None:
        return None
    unit = (amount.get("unit") or "").lower()
    if "kilo" in unit:
        return float(v) * 1000
    if "oz" in unit or "ounce" in unit:
        return float(v) * 28.3495
    if "lb" in unit or "pound" in unit:
        return float(v) * 453.592
    return float(v)


def build_punkapi(cur):
    beers = fetch_punkapi()
    n = 0
    for b in beers:
        ibu = num(b.get("ibu"))
        cur.execute(
            """INSERT INTO beers (name, style_label, style_id, abv, ibu_min, ibu_max,
                 tagline, description, yeast, first_brewed, image, source)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                b.get("name"), None, None, num(b.get("abv")),
                ibu, ibu, b.get("tagline"), b.get("description"),
                b.get("ingredients", {}).get("yeast"),
                b.get("first_brewed"), b.get("image"), "punkapi",
            ),
        )
        beer_id = cur.lastrowid
        ing = b.get("ingredients", {}) or {}
        for h in ing.get("hops", []) or []:
            cur.execute(
                "INSERT INTO beer_hops VALUES (?,?,?,?,?)",
                (beer_id, h.get("name"), g(h.get("amount")), h.get("add"), h.get("attribute")),
            )
        for m in ing.get("malt", []) or []:
            cur.execute(
                "INSERT INTO beer_malts VALUES (?,?,?)",
                (beer_id, m.get("name"), g(m.get("amount"))),
            )
        n += 1
    return n


def build_fts(cur):
    cur.execute(
        """INSERT INTO beers_fts(rowid, name, tagline, description, style_label, aroma)
           SELECT b.id, b.name, COALESCE(b.tagline,''), COALESCE(b.description,''),
                  COALESCE(b.style_label,''), COALESCE(s.aroma,'')
           FROM beers b LEFT JOIN styles_bjcp s ON s.style_id = b.style_id"""
    )


def main():
    if DB_PATH.exists():
        DB_PATH.unlink()
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.executescript(SCHEMA)

    build_styles(cur, load_bjcp())
    n_ba, unmatched = build_beeradvocate(cur)
    n_pk = build_punkapi(cur)
    build_fts(cur)
    con.commit()

    n_styles = cur.execute("SELECT COUNT(*) FROM styles_bjcp").fetchone()[0]
    n_hops = cur.execute("SELECT COUNT(*) FROM beer_hops").fetchone()[0]
    print(f"beer.db built:")
    print(f"  BJCP styles:            {n_styles}")
    print(f"  beeradvocate beers:     {n_ba}")
    print(f"  punkapi beers:          {n_pk}")
    print(f"  hops:                   {n_hops}")
    mapped = cur.execute("SELECT COUNT(*) FROM beers WHERE source='beeradvocate' AND style_id IS NOT NULL").fetchone()[0]
    print(f"  styles mapped to BJCP:  {mapped}/{n_ba}")
    if unmatched:
        print("  labels without manual mapping (style_id NULL):", ", ".join(sorted(unmatched)) or "none")
    con.close()


if __name__ == "__main__":
    main()
