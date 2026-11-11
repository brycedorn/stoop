# stoop

A data-driven neighborhood finder for New York City. It scores all ~260 NYC
neighborhoods on what matters to you, and you tune the weights live on a map.

| Factor | Source |
|---|---|
| Running | OpenStreetMap paths, NYC Parks, your own GPS runs |
| Runner traffic | A runner-hex file (0-5 per hex) made by a separate tool; format in `stoop/sources/runner_hexes.py` |
| 5K routes | Walk to the nearest car-free route long enough for a 5K: park loops, greenways, waterfront paths (OpenStreetMap) |
| Airports | Routed transit time to JFK, LaGuardia, Newark |
| Your bars & restaurants | Shown on the map (geocoded with OSM Nominatim); not scored |
| Commute | r5py routing on MTA GTFS + OSM (estimated fallback) |
| Rent | Census ACS median rent by bedroom count, sharpened by listing rents if you supply them |
| Safety | NYPD complaint data, last 12 months, per resident |
| Quiet | 311 noise complaints, per resident |
| Green space | NYC Parks properties, 2015 street tree census |
| Daily errands | OSM supermarkets, pharmacies, laundromats |
| Gyms | OSM full-size gyms (Equinox, Planet Fitness, Blink, YMCA, Parks rec centers…), not boutique studios |
| Citi Bike | Citi Bike GBFS station feed |
| Flood safety | NYC stormwater flood map, Sandy inundation zone |
| Breathing room | Census population density |

It runs on your laptop and costs nothing: a Python pipeline writes one data
file, and a static page (`web/index.html`) shows it.

## Quick start

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows  (macOS/Linux: source .venv/bin/activate)
pip install -e ".[dev,activities]"

python -m stoop demo              # fake data, to preview the map
start web\index.html              # Windows; or just double-click it
```

## Real data

1. **Edit `config.yaml`**: commute destinations and `commute_to` (the one you're scored on), budget, bedrooms.
2. **Get a free Census API key** at https://api.census.gov/data/key_signup.html
   and `set CENSUS_API_KEY=...` (or put it in `config.yaml`).
3. **Optional inputs** (each one makes a factor personal):
   - `inputs/places.csv`: your bars and restaurants (see `places.example.csv`)
   - `inputs/activities/`: GPS files of your own runs, from any app (see the README there)
   - `inputs/runner_hexes.json`: runner traffic by hex (0-5), from a separate tool
   - `inputs/rents/`: optional listing rent CSVs (see the README there); local only, never published
4. **Run it:**
   ```bash
   python -m stoop run               # everything (first run ~20-40 min, mostly downloads)
   python -m stoop run --steps rent,favorites   # just some steps
   python -m stoop score             # re-score from cache after editing config (seconds)
   python -m stoop status            # what's cached
   ```
5. Open `web/index.html`. Check `data/interim/qa_report.md` for anything odd.

### Real commute times (recommended)

Without this, commute is estimated as walk + straight-line subway ride.

1. Install a Java 21 JDK (e.g. Eclipse Temurin 21). It doesn't have to be your default Java.
2. Point `config.local.yaml` at it, under `transit:` (`java_home`, plus `max_memory`, the JVM heap; 8G works).
3. `pip install -e ".[transit]"`
4. `python -m stoop run --steps commute` (about 75 minutes for the whole city), then `python -m stoop score`.

The map then shows routed times. Switching a destination off keeps them exact. A moved or new pin
is estimated (shown with "~"), adjusted per neighborhood by how far the estimate was off for your
configured destinations: typically within 3 minutes. Add a new office to `config.yaml` and rerun
the commute step for exact times.

### Monthly refresh

```bash
python -m stoop run --steps rent,safety,quiet,citibike --refresh rent,safety,quiet,citibike
```

## How scoring works

- Analysis runs on a grid of 150 m hexes (about 260 m across). Each hex measures what's reachable from it
  (paths within 1 km, the nearest supermarket, and so on). Hexes are then
  averaged into neighborhoods, weighted by how many people live in each one.
- Select a neighborhood and the map shows its hexes, so you can see how it varies inside (near the subway vs the
  far edge). Rent, apartment size, safety and quiet are only known for the whole neighborhood.
- Most factors are **percentiles** among residential neighborhoods (100 = best in the city).
- Rent, commute and flood use **absolute curves**: rent against your budget,
  minutes of commute, and the share of land that floods.
- Crime and noise are counted **per 1,000 residents**. Amenities are counted within **walking distance**.
- The map's overall match is the weighted average of the factors you turn on.

## Layout

```
config.yaml          your settings and data-source IDs
stoop/               pipeline (python -m stoop)
  sources/           one module per factor
  scoring.py         raw metrics -> 0-100 scores
  export.py          web payload + QA report
web/                 static map (open index.html)
inputs/              your personal data
data/                downloads + intermediate results (gitignored)
```

## Publishing (optional, free)

The data is built on your machine (transit routing takes about an hour, and optional inputs are local, so it
doesn't run in CI). Then:

```
python -m stoop publish --commit    # builds site/ from cached results and commits it to the gh-pages branch
git push origin gh-pages
```

On GitHub: Settings → Pages → Deploy from a branch → `gh-pages`, folder `/ (root)`.

What gets published is what stoop derives, never a source's own records: factor scores for neighborhoods and
hexes, commute and walking times stoop routed, per-person figures computed from open data, and rent only as Census
estimates in $500 bands (listing rents never leave your machine). Nothing personal: `publish` reads `config.yaml`
only (never `config.local.yaml`) and leaves out your places, liked areas, destination labels, GPS runs and runner
hexes. It refuses to finish if any of those show up.
