"""Consolidate Wyoming DCI cold-case exports into a single canonical CSV.

Inputs: main.csv, locations.csv, synopses.csv, synopses_and_photos.zip
under WYOMING_SOURCE_DIR (default: ignored data/raw/wyoming-source-exports).
Acquire source exports separately; they are not distributed with the code.
Set WYOMING_OUTPUT_DIR to override the ignored default output directory.

Join key: Reported Date. The 1982-09-14 date appears twice in the main CSV
(Heberling + Gath at the same Wamsutter scene); both victims inherit the
single 1982-09-14 row from the locations CSV.

Image-to-case mapping is positional: Sheet1.html renders each case as a
single <tr> at row index 2, 4, 6, ... 88. 14 of those rows carry an
<img src="resources/cellImage_0_N.jpg">. case_index = (row_idx - 2) / 2.

Output:
  data/raw/cold_case_wy_dci/2026-05-13/wyoming_dci_cold_cases.csv
  data/raw/cold_case_wy_dci/2026-05-13/photos/<source_case_id>.jpg
"""

from __future__ import annotations

import csv
import os
import re
import shutil
import zipfile
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT_DIR = Path(
    os.environ.get("WYOMING_OUTPUT_DIR", str(REPO / "data/raw/cold_case_wy_dci/2026-05-13"))
)
OUT_CSV = OUT_DIR / "wyoming_dci_cold_cases.csv"
PHOTO_DIR = OUT_DIR / "photos"

SOURCE_DIR = Path(
    os.environ.get("WYOMING_SOURCE_DIR", str(REPO / "data/raw/wyoming-source-exports"))
)
MAIN = SOURCE_DIR / "main.csv"
LOCS = SOURCE_DIR / "locations.csv"
SYNS = SOURCE_DIR / "synopses.csv"
ZIP = SOURCE_DIR / "synopses_and_photos.zip"


def parse_date(s: str) -> str:
    """`Feb 3, 2018` -> `2018-02-03`."""
    return datetime.strptime(s.strip(), "%b %d, %Y").strftime("%Y-%m-%d")


def slug(s: str | None) -> str:
    """Lowercase + ascii-only + hyphenated."""
    if not s:
        return ""
    out = re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-").lower()
    return out


def build_source_case_id(reported_date_iso: str, victim_name: str) -> str:
    """Stable per-case slug.

    `wy-2018-02-03-bruegger` for named victims.
    `wy-YYYY-MM-DD-unidentified` when victim_name is blank.
    Lastname-based — disambiguates the 1982-09-14 collision (heberling vs gath).
    """
    if not victim_name.strip():
        return f"wy-{reported_date_iso}-unidentified"
    last = victim_name.strip().split()[-1]
    return f"wy-{reported_date_iso}-{slug(last)}"


def load_main() -> list[dict[str, str]]:
    rows = list(csv.DictReader(MAIN.open(encoding="utf-8-sig")))
    # Preserve display order (desc by date) — synopsis CSV positions follow this.
    out = []
    for r in rows:
        date_iso = parse_date(r["Reported Date"])
        out.append(
            {
                "_reported_date_raw": r["Reported Date"],
                "reported_date": date_iso,
                "crime_types": r["Crime"].strip(),
                "weapon": r["Weapon - Instrument"].strip(),
                "victim_name": r["Homicide Victim Name"].strip(),
                "victim_age": r["Victim Age"].strip(),
                "victim_sex": r["Victim Sex"].strip(),
                "victim_race": r["Victim Race"].strip(),
                "scene_type": r["Scene Type"].strip(),
                "scene_city": r["Scene City"].strip(),
                "scene_county": r["Scene County"].strip(),
            }
        )
    return out


def load_locations() -> dict[str, dict[str, str]]:
    """Indexed by raw date string (matches main CSV's `Reported Date` exactly).

    The Wyoming DCI sheet uses bare `-` as the placeholder for unrecorded
    fields in both Address and Business/Name. Normalize to empty string at
    load time so downstream geocoding sees an honest NULL rather than the
    sentinel.
    """

    def _clean(v: str) -> str:
        v = v.strip()
        return "" if v == "-" else v

    out = {}
    for r in csv.DictReader(LOCS.open(encoding="utf-8-sig")):
        key = r["Reported Date"]
        out[key] = {
            "scene_address": _clean(r["Address"]),
            "scene_business_name": _clean(r["Business/Name"]),
        }
    return out


def load_synopses() -> list[str]:
    """Returns 44 synopses in main-CSV display order (non-empty rows only)."""
    out = []
    for r in csv.reader(SYNS.open(encoding="utf-8-sig")):
        if len(r) >= 1 and r[0].strip():
            if r[0].strip().lower() == "synopsis":
                continue  # header
            out.append(r[0].strip())
    return out


def load_photos_from_zip(target_dir: Path) -> dict[int, str]:
    """Returns {case_index: original_image_filename} mapping.

    Parses Sheet1.html for <tr> rows that contain <img src="resources/cellImage_0_N.jpg">.
    case_index = (html_row_index - 2) / 2, derived from the rendered sheet layout.
    Extracts the JPGs to a temp dir; caller decides final naming.
    """
    target_dir.mkdir(parents=True, exist_ok=True)
    extracted = {}
    with zipfile.ZipFile(ZIP) as zf:
        html = zf.read("Sheet1.html").decode("utf-8", errors="ignore")
        # Walk <tr> tags in document order
        tr_iter = re.finditer(r"<tr[^>]*>(.*?)</tr>", html, flags=re.S)
        for html_row_idx, m in enumerate(tr_iter):
            body = m.group(1)
            img_match = re.search(r"cellImage_0_(\d+)\.jpg", body)
            if not img_match:
                continue
            case_idx = (html_row_idx - 2) // 2  # 0-based; row 2 -> case 0
            if case_idx < 0:
                continue
            img_filename = f"cellImage_0_{img_match.group(1)}.jpg"
            extracted[case_idx] = img_filename

        # Extract the actual JPG bytes
        for img_filename in extracted.values():
            with (
                zf.open(f"resources/{img_filename}") as src,
                open(target_dir / img_filename, "wb") as dst,
            ):
                shutil.copyfileobj(src, dst)
    return extracted


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    PHOTO_DIR.mkdir(parents=True, exist_ok=True)
    tmp_photos = OUT_DIR / "_tmp_photos"

    main_rows = load_main()
    print(f"main: {len(main_rows)} cases")
    locations = load_locations()
    print(f"locations: {len(locations)} entries")
    synopses = load_synopses()
    print(f"synopses: {len(synopses)} non-empty")
    photos_by_case_idx = load_photos_from_zip(tmp_photos)
    print(
        f"photos: {len(photos_by_case_idx)} mapped to case_index "
        f"{sorted(photos_by_case_idx.keys())}"
    )

    if len(main_rows) != len(synopses):
        raise RuntimeError(
            f"main rows ({len(main_rows)}) != synopses ({len(synopses)}) — order mismatch"
        )

    # Stable source_case_id assignment + final photo rename
    output_rows = []
    photo_renames = {}
    for case_idx, row in enumerate(main_rows):
        date_raw = row.pop("_reported_date_raw")
        loc = locations.get(date_raw, {"scene_address": "", "scene_business_name": ""})
        synopsis = synopses[case_idx]
        scid = build_source_case_id(row["reported_date"], row["victim_name"])

        original = photos_by_case_idx.get(case_idx)
        photo_filename = ""
        if original is not None:
            photo_filename = f"{scid}.jpg"
            photo_renames[original] = photo_filename

        output_rows.append(
            {
                "source_case_id": scid,
                "reported_date": row["reported_date"],
                "crime_types": row["crime_types"],
                "weapon": row["weapon"],
                "victim_name": row["victim_name"],
                "victim_age": row["victim_age"],
                "victim_sex": row["victim_sex"],
                "victim_race": row["victim_race"],
                "scene_type": row["scene_type"],
                "scene_address": loc["scene_address"],
                "scene_business_name": loc["scene_business_name"],
                "scene_city": row["scene_city"],
                "scene_county": row["scene_county"],
                "synopsis": synopsis,
                "photo_filename": photo_filename,
            }
        )

    # Homicide-only filter — drop 12 standalone "Sexual Assault" rows.
    # Wyoming DCI's public registry lumps unidentified-remains sexual-assault
    # cases into the same dataset; CaseSignal is cold-case-homicide scoped
    # (post-Phase-0 pivot). Filtering here is the canonical normalization layer.
    before = len(output_rows)
    output_rows = [r for r in output_rows if "homicide" in r["crime_types"].lower()]
    print(f"homicide filter: {before} -> {len(output_rows)} rows kept")

    # Drop any photo rename whose target source_case_id was filtered out.
    # All 14 current photos belong to homicide rows so this is a no-op now,
    # but the guard is correct for future re-runs against updated source data.
    retained_scids = {r["source_case_id"] for r in output_rows}
    photo_renames = {
        orig: new for orig, new in photo_renames.items() if new[: -len(".jpg")] in retained_scids
    }

    # Ensure source_case_id is unique (defensive)
    seen = {}
    for r in output_rows:
        s = r["source_case_id"]
        seen[s] = seen.get(s, 0) + 1
    dupes = {k: v for k, v in seen.items() if v > 1}
    if dupes:
        raise RuntimeError(f"duplicate source_case_id values: {dupes}")

    # Write CSV
    with OUT_CSV.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(output_rows[0].keys()))
        w.writeheader()
        w.writerows(output_rows)
    print(f"wrote: {OUT_CSV}")

    # Move photos with renamed filenames
    for old, new in photo_renames.items():
        shutil.move(str(tmp_photos / old), str(PHOTO_DIR / new))
    # Clean up tmp dir
    if tmp_photos.exists():
        for stray in tmp_photos.iterdir():
            stray.unlink()
        tmp_photos.rmdir()
    print(f"photos in: {PHOTO_DIR}  ({len(photo_renames)} renamed)")


if __name__ == "__main__":
    main()
