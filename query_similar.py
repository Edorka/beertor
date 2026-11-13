#!/usr/bin/env python3
"""Similarity query over the Beer collection in Weaviate.

Modes:
  --like "Beer name"           beers most similar to that one
  --prefs '{"hoppy":0.9,"fruits":0.6,...}'   closest to that ideal taste
Options:
  -k N        number of results (default 10)
  --min-reviews N   filter out beers with fewer reviews (default 0)
  --by-rating  sort by adjusted rating instead of proximity
              (Bayes: prior 3.5 with 100 pseudo-count reviews)

Requires the server to be running: docker compose up -d
The 0-100 sensory profile lives in beer.db; the vector (0-1) and the filter
are applied together in Weaviate's KNN (pre-filter, cosine metric).

Examples:
  .venv/bin/python query_similar.py --like "Dead Pony Club" -k 5
  .venv/bin/python query_similar.py --prefs '{"hoppy":0.9,"fruits":0.7,"sweet":0.2}' -k 5 --min-reviews 100
"""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

import weaviate
from weaviate.classes.query import Filter
from weaviate.util import generate_uuid5

ROOT = Path(__file__).parent
DB_PATH = ROOT / "beer.db"
COLLECTION = "Beer"

DIMS = ["astringency", "body", "alcohol", "bitter", "sweet", "sour",
        "salty", "fruits", "hoppy", "spices", "malty"]

# adjusted rating (Bayes): WA = (R*n + 3.5*m) / (n + m), prior m=100
BAYES_M = 100.0
BAYES_C = 3.5


def open_db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def vec_of_row(con, beer_id):
    cols = ", ".join(DIMS)
    vals = con.execute(
        f"SELECT {cols} FROM beers WHERE id = ?", (beer_id,)
    ).fetchone()
    if vals is None or vals[0] is None or vals["hoppy"] is None:
        sys.exit("That beer has no vectorized sensory profile.")
    return [vals[d] / 100 for d in DIMS]


def rating_adj(r):
    n = r["n_reviews"] or 0
    return (r["review_overall"] * n + BAYES_C * BAYES_M) / (n + BAYES_M)


def print_table(rows, ref):
    print(f"Results similar to: {ref}\n")
    print(f"{'beer':42s} {'style':32s} {'IBU':9s} {'ABV':5s} "
          f"{'rate':5s} {'adj':5s} {'revs':6s} {'dist':6s}")
    print("-" * 118)
    for r in rows:
        ibu = (f"{r['ibu_min']:.0f}-{r['ibu_max']:.0f}"
               if r["ibu_min"] is not None else "  ?  ")
        print(f"{r['name'][:41]:42s} "
              f"{(r['style_bjcp'] or r['style_label'] or '?')[:31]:32s} "
              f"{ibu:9s} {(r['abv'] or 0):5.1f} {(r['review_overall'] or 0):5.2f} "
              f"{rating_adj(r):5.2f} {r['n_reviews'] or 0:6d} "
              f"{r['distance']:6.3f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--like")
    ap.add_argument("--prefs")
    ap.add_argument("-k", type=int, default=10)
    ap.add_argument("--min-reviews", type=int, default=0)
    ap.add_argument("--by-rating", action="store_true")
    args = ap.parse_args()

    con = open_db()
    filters = None
    if args.like:
        hit = con.execute(
            "SELECT id, name FROM beers WHERE name LIKE ? LIMIT 1",
            (f"%{args.like}%",),
        ).fetchone()
        if hit is None:
            sys.exit(f"Beer not found: {args.like}")
        vec = vec_of_row(con, hit["id"])
        ref = args.like
        filters = Filter.by_id().not_equal(generate_uuid5(hit["id"]))
    elif args.prefs:
        prefs = json.loads(args.prefs)
        unknown = set(prefs) - set(DIMS)
        if unknown:
            sys.exit(f"Invalid dimensions: {unknown}. Valid ones: {DIMS}")
        vec = [prefs.get(d, 0.5) for d in DIMS]
        ref = f"preferences {args.prefs}"
    else:
        sys.exit("Use --like 'Name' or --prefs '{json}'")
    con.close()

    if args.min_reviews > 0:
        by_reviews = Filter.by_property("n_reviews").greater_or_equal(
            args.min_reviews)
        filters = by_reviews if filters is None else filters & by_reviews

    # fetch more candidates if they will be re-sorted here
    k_fetch = max(args.k * 3, 40) if args.by_rating else args.k

    client = weaviate.connect_to_local()
    res = client.collections.get(COLLECTION).query.near_vector(
        near_vector=vec, limit=k_fetch, filters=filters,
        return_metadata=["distance"],
        return_properties=["name", "style_label", "style_bjcp", "abv",
                           "ibu_min", "ibu_max", "review_overall",
                           "n_reviews"],
    )
    client.close()

    rows = [dict(o.properties, distance=o.metadata.distance)
            for o in res.objects]
    if args.by_rating:
        rows = sorted(rows, key=rating_adj, reverse=True)
    rows = rows[:args.k]
    if not rows:
        sys.exit("No results with those filters.")

    print_table(rows, ref)


if __name__ == "__main__":
    main()
