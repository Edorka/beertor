# beertor — beer + vector, craft beer database

> ⚠️ **Alcohol notice**: alcohol consumption is **discouraged**; in particular
> during pregnancy, breastfeeding, while on medication and when driving. This
> project is intended exclusively for **adults** (18+ / legal drinking age
> depending on jurisdiction) and aims to be an informative, responsible
> recommendation tool. Drink in moderation and safely; when in doubt, consult
> a healthcare professional.

SQLite database of **3,612 beers** (3,197 craft from BeerAdvocate + 415 from
BrewDog) with type, IBUs, aroma profile and BJCP 2021 style taxonomy, plus a
Weaviate vector store for similarity, designed as the knowledge source for a
recommender agent.

## Files

| File | Description |
|---|---|
| `beer.db` | The database (SQLite + FTS5) |
| `build_db.py` | Build script (idempotent: deletes and regenerates `beer.db`) |
| `export_csv.py` | Exports `beer.db` to CSV (default `data/beers.csv`; accepts an alternative path as argument) |
| `import_weaviate.py` | Creates the `Beer` collection in Weaviate and imports the sensory vectors |
| `query_similar.py` | Vector similarity query in Weaviate (by reference beer or by preferences) |
| `docker-compose.yml` | Local Weaviate server (ports 8080 HTTP + 50051 gRPC) |
| `requirements.txt` | Python dependencies |
| `data/Beer_data.xlsx` | *Beer Profile & Ratings* dataset (3,197 craft beers) |
| `data/bjcp_styleguide-2021.json` | BJCP 2021: 110 styles with aroma, flavor and ranges |
| `data/punkapi/beers_p*.json` | Cache of 415 BrewDog beers with ingredients (downloaded by `build_db.py`; not versioned) |

## Setup

```sh
docker compose up -d                       # Weaviate server
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python build_db.py               # (re)builds beer.db
.venv/bin/python import_weaviate.py        # creates the Beer collection and imports
```

## beers.csv

One file, one row per beer (3,612 rows, 42 columns), generated from the
`v_beers` view with hops and malts aggregated as text into the `hops` and
`malts` columns (e.g. `Simcoe (dry hop) | Citra (dry hop)`). UTF-8 with BOM
encoding so it opens directly in Excel; comma separator and quoting per
RFC 4180.

## Sources and licenses

- **Beer Profile & Ratings** (BeerAdvocate via Kaggle / douglasslab.com):
  3,197 beers from 934 breweries, 111 styles. Includes sensory profile (0-100)
  and user ratings (0-5). ⚠️ IBUs are **per-style ranges**, not measured per
  beer.
- **BJCP 2021** (`beerjson/bjcp-json`, MIT): style taxonomy with aroma,
  appearance, flavor, body and IBU/OG/FG/ABV/SRM ranges.
- **PunkAPI v3** (`punkapi.dev`, MIT data): 415 BrewDog beers with individual
  IBU and specific hops (with use and attribute: bitter / flavour / aroma).

## Schema

```
styles_bjcp     110 BJCP styles (aroma, flavor, body, IBU/ABV/SRM ranges, tags)
breweries       breweries
beers           beers (name, style, IBU, ABV, description, sensory profile, reviews)
beer_hops       hops per beer (amount in g, use: start/middle/end/dry hop, attribute)
beer_malts      malts per beer (PunkAPI only)
beers_fts       full-text index (name, description, style, style aroma)
v_beers         view: beer + BJCP style + brewery in a single row (for the agent)
```

Key columns of `beers`:

- Identity: `name`, `full_name`, `brewery_id`, `style_label` (original
  BeerAdvocate label), `style_id` (normalized to BJCP; may be NULL),
  `source` (`beeradvocate` | `punkapi`).
- Characteristics: `abv`, `ibu_min`, `ibu_max`, `description`, `yeast`.
- Sensory profile 0-100 (from BeerAdvocate): `astringency`, `body`, `alcohol`,
  `bitter`, `sweet`, `sour`, `salty`, `fruits`, `hoppy`, `spices`, `malty`.
- Ratings 0-5: `review_aroma`, `review_appearance`, `review_palate`,
  `review_taste`, `review_overall`, `n_reviews`.

## Using it in the recommender agent

1. **Preferences → numeric filters**: use the 0-100 sensory profile
   (`hoppy`, `fruits`, `malty`…) and the `ibu_min`/`ibu_max` ranges.
2. **Free-text search**: FTS5 (`beers_fts MATCH ...`), accent-insensitive
   (`remove_diacritics 2`).
3. **By style**: `style_id`/`style_label` in `beers` or the narrative
   descriptors in `styles_bjcp.aroma`/`flavor`.
4. **By specific hop**: `beer_hops.hop` + `purpose`/`use` (aroma vs bitter).
5. **Similarity**: compare the 11-dimensional sensory profile vector (cosine,
   `Beer` collection in Weaviate) with the beers the user likes; numeric
   filters go into the KNN itself (pre-filter).

### Examples

```sql
-- Fruity American IPAs with good aroma and well rated
SELECT name, brewery, ibu_min, ibu_max, abv, review_aroma
FROM v_beers
WHERE style_bjcp = 'American IPA' AND fruits > 60 AND review_aroma > 4
ORDER BY review_aroma DESC;

-- Beers with coffee aroma (FTS, accent-insensitive)
SELECT name, style_label FROM beers_fts f JOIN beers b ON b.id = f.rowid
WHERE beers_fts MATCH 'aroma cafe';

-- Which hops give aroma to a specific beer
SELECT hop, use, purpose FROM beer_hops
WHERE beer_id = (SELECT id FROM beers WHERE name = 'Dead Pony Club');

-- BJCP style sheet for the agent's reasoning
SELECT name, ibu_min, ibu_max, aroma, overall_impression
FROM styles_bjcp WHERE style_id = '21A';
```

## Vector store (Weaviate)

Vectors live in the **`Beer`** collection of a local Weaviate server
(`docker compose up -d`; data persists in the `beertor_weaviate_data` Docker
volume). It contains **3,197 objects** (beers with a complete sensory profile;
the 415 PunkAPI ones do not include it), HNSW with cosine metric and the
vectorizer disabled: vectors are provided by the client.

Vector dimensions, normalized to 0-1 (same order in every script):

```
astringency, body, alcohol, bitter, sweet, sour, salty, fruits, hoppy, spices, malty
```

The 11 dimensions are also stored as numeric properties, so the agent can
combine filter + similarity in a single query (pre-filter): e.g. "wheat but
hoppy" is `style ~ Wheat` + `near_vector`, and Weaviate constrains the KNN
traversal itself to the filtered subset.

Example with the Python client (v4):

```python
import weaviate
from weaviate.classes.query import Filter

client = weaviate.connect_to_local()
beers = client.collections.get("Beer")
res = beers.query.near_vector(
    near_vector=[0.1, 0.3, 0.1, 0.5, 0.2, 0.3, 0.0, 0.6, 0.9, 0.1, 0.2],
    limit=10,
    filters=Filter.by_property("n_reviews").greater_or_equal(50),
    return_metadata=["distance"],
)
```

### Direct query

```sh
.venv/bin/python query_similar.py --like "Big Eye" -k 6 --min-reviews 50
.venv/bin/python query_similar.py --prefs '{"hoppy":0.95,"fruits":0.8,"sweet":0.1}' -k 6
.venv/bin/python query_similar.py --prefs '{"hoppy":0.9,"fruits":0.7}' -k 5 --by-rating
```

- `--like`: nearest neighbors to an existing beer (the sensory profile is read
  from `beer.db`; the beer itself is excluded by UUID).
- `--prefs`: beers close to an ideal taste (dimensions not given = 0.5).
- `--min-reviews`: filter applied inside Weaviate's KNN.
- `--by-rating`: re-sorts by `rating_adj` (Bayes: `WA = (R·n + 3.5·100)/(n + 100)`,
  to avoid overrating beers with few reviews).
- Rebuild after recreating the DB: `build_db.py` and then `import_weaviate.py`.

## Notes and warnings

- **IBUs**: in the BeerAdvocate dataset they are per-style ranges (`Min.IBU` /
  `Max.IBU`); in PunkAPI they are individual. BJCP styles also carry the
  official per-style ranges (`styles_bjcp.ibu_min/ibu_max`).
- **Styles with no BJCP 2021 equivalent** (319 beers): Sahti, Kvass, Faro,
  Imperial Pilsner, Imperial Porter, Kellerbier, Euro Strong Lager, Malt
  Liquor, Rye Beer, Happoshu, Low Alcohol, English Stout, Belgian Dark Brown,
  Bière de Champagne. They keep `style_label` but `style_id` is NULL.
- The mapping of 111 BeerAdvocate labels → BJCP 2021 is in `STYLE_MAP` inside
  `build_db.py`, manually correctable if any error is found.
- Texts are in English (descriptions and BJCP profiles). If the agent must
  answer in another language, translate at the presentation layer, not in the
  data.
- The original Excel had mojibake (UTF-8 read as MacRoman: `K√∂lsch`);
  `fix_mojibake()` repairs it during the build.
