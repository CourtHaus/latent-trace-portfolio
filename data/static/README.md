# Static geocoding reference data

Centroid lookup tables used by the geocoding worker as fallbacks when the
Census Bureau street-level geocoder doesn't return a hit.

## `zip_centroids.csv`

ZIP Code Tabulation Area (ZCTA) centroids — one row per ZIP, three columns:

```
zip_code,latitude,longitude
00601,18.180555,-66.749961
...
```

**Source:** U.S. Census Bureau 2020 Gazetteer Files, ZCTA national file
([https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2020_Gazetteer/2020_Gaz_zcta_national.zip](https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2020_Gazetteer/2020_Gaz_zcta_national.zip))

**Retrieved:** 2026-05-08

**Transformation:** kept `GEOID` (renamed `zip_code`), `INTPTLAT` (renamed
`latitude`), `INTPTLONG` (renamed `longitude`). All other columns dropped.

**Row count:** 33,144

## `county_centroids.csv`

County centroids by 5-digit FIPS code — one row per U.S. county / county
equivalent:

```
state_code,county_fips,state_fips,county_name,latitude,longitude
MD,24005,24,Baltimore County,39.443167,-76.616569
...
```

**Source:** U.S. Census Bureau 2020 Gazetteer Files, Counties national file
([https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2020_Gazetteer/2020_Gaz_counties_national.zip](https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2020_Gazetteer/2020_Gaz_counties_national.zip))

**Retrieved:** 2026-05-08

**Transformation:** kept `USPS` (renamed `state_code`), `GEOID` (renamed
`county_fips` — full 5-digit FIPS including state prefix), derived
`state_fips` from `GEOID[:2]`, kept `NAME` (renamed `county_name`),
`INTPTLAT`/`INTPTLONG` (renamed `latitude`/`longitude`). All other columns
dropped.

**Row count:** 3,221

## Refresh procedure

When updating reference data, use the intended Census Gazetteer vintage and
record it explicitly. To refresh:

1. Download the relevant national `*.zip` from the Census Bureau URL above.
2. Extract the TSV.
3. Run the same column-projection transformation (kept fields are listed
   above).
4. Replace the CSV in this directory.
5. Update the "Retrieved" date in this README.
6. Commit.

These files are public domain (U.S. government work, 17 USC §105).
