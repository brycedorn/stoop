# Listing rent CSVs (optional)

Median asking rents by neighborhood make the Rent factor sharper than Census estimates alone. Supply them in
either of two ways:

1. Put the CSV files here: one per bedroom count (file names containing `studio`, `onebd`, `twobd`,
   `threeplus`, or `all`), with columns `areaName`, `Borough`, `areaType`, then one column per month (`YYYY-MM`).
2. Or set `sources.rent_csv_url` in your `config.local.yaml` to a URL template with `{b}` for the bedroom code
   (`Studio`, `OneBd`, `TwoBd`, `ThreePlusBd`, `All`) that serves those CSVs zipped.

Check that your source's terms allow your use. Listing rents stay on your machine: the public site
(`python -m stoop publish`) uses Census estimates only.

Without listing rents, every neighborhood uses the Census ACS median rent for its bedroom count, scaled toward
asking rents. If a neighborhood is matched to the wrong area (or not at all), add a row to
`inputs/rent_crosswalk.csv`:

```
nta2020,listing_area
MN0604,Murray Hill
```

Rerun: `python -m stoop run --steps rent`. Everything in this folder except this README is gitignored.
