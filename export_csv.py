#!/usr/bin/env python3
"""Exports beer.db to CSV.

Generates beers.csv: one row per beer with the schema fields (v_beers view)
plus hops and malts aggregated into text columns
(e.g. 'Simcoe|Citra (dry hop, aroma)').

Usage:  .venv/bin/python export_csv.py           -> data/beers.csv
        .venv/bin/python export_csv.py path.csv  -> path.csv
"""
import csv
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).parent
DB_PATH = ROOT / "beer.db"

QUERY = """
SELECT v.id, v.name, v.full_name, v.brewery, v.style_label, v.style_bjcp,
       v.style_category, v.abv, v.ibu_min, v.ibu_max, v.tagline, v.description,
       v.yeast,
       v.astringency, v.body, v.alcohol, v.bitter, v.sweet, v.sour, v.salty,
       v.fruits, v.hoppy, v.spices, v.malty,
       v.review_aroma, v.review_appearance, v.review_palate, v.review_taste,
       v.review_overall, v.n_reviews, v.cluster_name, v.source,
       v.style_ibu_min, v.style_ibu_max, v.style_abv_min, v.style_abv_max,
       v.style_aroma, v.style_flavor, v.style_mouthfeel, v.style_overall,
       hops, malts
FROM v_beers v
LEFT JOIN (
    SELECT beer_id,
           GROUP_CONCAT(hop || CASE WHEN use IS NOT NULL AND use != ''
                                    THEN ' (' || use || ')' ELSE '' END, ' | ')
           AS hops
    FROM beer_hops GROUP BY beer_id
) h ON h.beer_id = v.id
LEFT JOIN (
    SELECT beer_id, GROUP_CONCAT(malt, ' | ') AS malts
    FROM beer_malts GROUP BY beer_id
) m ON m.beer_id = v.id
ORDER BY v.id
"""

FIELDS = [
    "id", "name", "full_name", "brewery", "style_label", "style_bjcp",
    "style_category", "abv", "ibu_min", "ibu_max", "tagline", "description",
    "yeast",
    "astringency", "body", "alcohol", "bitter", "sweet", "sour", "salty",
    "fruits", "hoppy", "spices", "malty",
    "review_aroma", "review_appearance", "review_palate", "review_taste",
    "review_overall", "n_reviews", "cluster_name", "source",
    "style_ibu_min", "style_ibu_max", "style_abv_min", "style_abv_max",
    "style_aroma", "style_flavor", "style_mouthfeel", "style_overall",
    "hops", "malts",
]


def main():
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data" / "beers.csv"
    if not DB_PATH.exists():
        sys.exit("beer.db not found; run first: .venv/bin/python build_db.py")
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    rows = con.execute(QUERY)
    out.parent.mkdir(parents=True, exist_ok=True)
    # utf-8-sig so Excel opens it correctly; commas and quotes per RFC 4180
    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, quoting=csv.QUOTE_MINIMAL)
        w.writerow(FIELDS)
        n = 0
        for r in rows:
            w.writerow([r[k] for k in FIELDS])
            n += 1
    print(f"{out} written: {n} beers, {len(FIELDS)} columns")


if __name__ == "__main__":
    main()
