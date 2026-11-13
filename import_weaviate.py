#!/usr/bin/env python3
"""Creates the Beer collection in Weaviate and fills it from beer.db.

The collection uses client-provided vectors of 11 dimensions (sensory profile
normalized to 0-1) with cosine metric and HNSW; no Weaviate vectorizer is
used (Vectors.self_provided).

Requires the server to be running: docker compose up -d

Usage: .venv/bin/python import_weaviate.py
"""
import sqlite3
from pathlib import Path

import weaviate
from weaviate.classes.config import Configure, DataType, Property, VectorDistances
from weaviate.util import generate_uuid5

ROOT = Path(__file__).parent
DB_PATH = ROOT / "beer.db"

COLLECTION = "Beer"

DIMS = ["astringency", "body", "alcohol", "bitter", "sweet", "sour",
        "salty", "fruits", "hoppy", "spices", "malty"]

# properties of the Beer document; the 11 sensory dimensions are stored as
# numbers too, so they can be filtered on in addition to vector search
PROPERTIES = (
    [Property(name=d, data_type=DataType.NUMBER) for d in DIMS]
    + [
        Property(name="name", data_type=DataType.TEXT),
        Property(name="full_name", data_type=DataType.TEXT),
        Property(name="brewery", data_type=DataType.TEXT),
        Property(name="style_label", data_type=DataType.TEXT),
        Property(name="style_bjcp", data_type=DataType.TEXT),
        Property(name="style_category", data_type=DataType.TEXT),
        Property(name="abv", data_type=DataType.NUMBER),
        Property(name="ibu_min", data_type=DataType.NUMBER),
        Property(name="ibu_max", data_type=DataType.NUMBER),
        Property(name="tagline", data_type=DataType.TEXT),
        Property(name="description", data_type=DataType.TEXT),
        Property(name="yeast", data_type=DataType.TEXT),
        Property(name="review_overall", data_type=DataType.NUMBER),
        Property(name="n_reviews", data_type=DataType.INT),
        Property(name="source", data_type=DataType.TEXT),
    ]
)

SQL = f"""
SELECT id, name, full_name, brewery, style_label, style_bjcp, style_category,
       abv, ibu_min, ibu_max, tagline, description, yeast,
       {", ".join(DIMS)}, review_overall, n_reviews, source
FROM v_beers
WHERE astringency IS NOT NULL AND hoppy IS NOT NULL
"""


def main():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    rows = con.execute(SQL).fetchall()
    con.close()

    client = weaviate.connect_to_local()

    # drop and recreate, same style as build_db.py
    if client.collections.exists(COLLECTION):
        client.collections.delete(COLLECTION)

    beers = client.collections.create(
        name=COLLECTION,
        properties=PROPERTIES,
        vector_config=Configure.Vectors.self_provided(
            vector_index_config=Configure.VectorIndex.hnsw(
                distance_metric=VectorDistances.COSINE
            )
        ),
    )

    with client.batch.dynamic() as batch:
        for r in rows:
            props = {k: r[k] for k in r.keys() if k != "id"}
            props = {k: v for k, v in props.items() if v is not None}
            vec = [r[d] / 100 for d in DIMS]
            batch.add_object(
                properties=props,
                collection=COLLECTION,
                vector=vec,
                uuid=generate_uuid5(r["id"]),   # idempotent on re-import
            )

    if client.batch.failed_objects:
        print(f"Failed objects: {len(client.batch.failed_objects)}")
        for o in client.batch.failed_objects[:5]:
            print(" ", o.message)

    n = beers.aggregate.over_all(total_count=True).total_count
    print(f"Collection {COLLECTION} created and imported: {n} objects "
          f"out of {len(rows)} rows, vectors of {len(DIMS)} dims (cosine)")

    client.close()


if __name__ == "__main__":
    main()
