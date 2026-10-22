"""Filter-input normalization + sort-order SQL fragments.

Shared by list_service + map_service. Kept separate so the SQL ORDER BY
catalog doesn't repeat between the two endpoints, and so the gender/race
canonicalization (which has to mediate between API-visible canonical
forms and historical raw storage) lives in one place.
"""

from __future__ import annotations

from typing import Any

from casesignal.api.schemas.cold_cases import SortOrder
from casesignal.normalization import RACE_CANONICAL_MAP as RACE_CANONICAL_MAP
from casesignal.normalization import RACE_CANONICAL_TO_SOURCES as RACE_CANONICAL_TO_SOURCES
from casesignal.normalization import RACE_FALLBACK_CANONICAL as RACE_FALLBACK_CANONICAL
from casesignal.normalization import RACE_NON_OTHER_SOURCES as RACE_NON_OTHER_SOURCES
from casesignal.normalization import canonical_race as canonical_race

# Gender stored values (verified 2026-05-13 against cold_case.victim):
# {'F', 'M', 'female', 'male', 'unknown'}. The canonical form exposed to
# the API is {M, F, unknown}; both the abbreviation and the lowercase
# word are stored historically, so any filter input maps to BOTH source
# forms before SQL match.
GENDER_CANONICAL_MAP: dict[str, str] = {
    "m": "M",
    "male": "M",
    "f": "F",
    "female": "F",
    "unknown": "unknown",
}

# Reverse: canonical -> all source forms actually present in storage.
GENDER_CANONICAL_TO_SOURCES: dict[str, list[str]] = {
    "M": ["M", "male"],
    "F": ["F", "female"],
    "unknown": ["unknown"],
}


def expand_gender_filter(values: list[str] | None) -> list[str] | None:
    """Map any input form to ALL source forms for SQL match.

    Stored data has both 'M' and 'male' as valid; the filter must match
    either. Input 'M' or 'male' both expand to ['M', 'male']. Unknown
    garbage values are silently dropped; if all values drop, returns
    None so the IS NULL branch fires (no filter applied).
    """
    if values is None:
        return None
    canonical_set: set[str] = set()
    for v in values:
        canon = GENDER_CANONICAL_MAP.get(v.lower())
        if canon is not None:
            canonical_set.add(canon)
    out: set[str] = set()
    for canon in canonical_set:
        out.update(GENDER_CANONICAL_TO_SOURCES[canon])
    return sorted(out) or None


def _is_other_bucket(value: str) -> bool:
    return value == RACE_FALLBACK_CANONICAL or value.strip().lower() == RACE_FALLBACK_CANONICAL.lower()


def expand_race_filter(values: list[str] | None) -> list[str] | None:
    """Expand SPECIFIC canonical race buckets to all lowercased source forms for
    the positive SQL match (``LOWER(v.race) = ANY(...)``).

    The facet exposes canonical buckets; a selected bucket (e.g. "Black or
    African American") must match every raw spelling that folds into it ("black",
    "BLACK or AFRICAN AMERICAN", ...). "Other" is deliberately NOT expanded here —
    it is the complement of every specific bucket and is matched separately via
    `race_exclude_filter`, so it also catches unmapped/new spellings. A raw source
    value passed directly (e.g. a legacy shared link) is tolerated. Unknown inputs
    drop; returns None when the positive set is empty so the IS NULL branch fires.
    """
    if values is None:
        return None
    out: set[str] = set()
    for v in values:
        if _is_other_bucket(v):
            continue  # complement match — see race_exclude_filter
        sources = RACE_CANONICAL_TO_SOURCES.get(v)
        if sources is not None:
            out.update(sources)
        elif v.strip().lower() in RACE_CANONICAL_MAP:
            out.add(v.strip().lower())
    return sorted(out) or None


def race_exclude_filter(values: list[str] | None) -> list[str] | None:
    """When "Other" is selected, return the known non-Other source spellings to
    EXCLUDE — the SQL then matches any present race NOT among them (the explicit
    Other spellings plus any unmapped/new spelling). None otherwise.
    """
    if values is None:
        return None
    if any(_is_other_bucket(v) for v in values):
        return RACE_NON_OTHER_SOURCES
    return None


# Public visibility gate. A dataset_version is served to anonymous users ONLY
# while ingestion_status = 'published'. The admin unpublish control flips it to
# 'archived' (and draft/validated/failed are mid-pipeline) WITHOUT deleting the
# cases, so every public read path must constrain on this — see SEC-2026-05-31-A.
# Placed in the dv JOIN's ON clause (not WHERE) so a query physically cannot use
# FILTER_FROM without the gate. Mirrors operator_snapshot.py's published filter.
PUBLISHED_ONLY = "dv.ingestion_status = 'published'"

def ext_needed(
    weapon: list[str] | None, location_type: list[str] | None
) -> bool:
    """Whether a query must join cold_case.case_extractions_current.

    The Tier-1 extraction overlay (weapon, location_type) is only needed when a
    query filters on or selects those columns. Joining the DISTINCT ON view
    otherwise forces a full materialization on every count/facet query — ~13x
    the buffers on a corpus-wide COUNT — for a join whose 1:1 rows never affect
    the result. Callers that select ext columns (the list rows, the weapon /
    location_type facets) pass include_ext=True directly.
    """
    return weapon is not None or location_type is not None


# Shared FROM + JOIN block for the list / total / facet-count queries. Aliases:
# cases, ext (Tier-1 extraction overlay, LEFT so un-extracted cases survive;
# omitted when not needed — see ext_needed), dv (dataset_version, gated to
# published), ss (source_system). All joins are 1:1 with a case, so a bare
# COUNT(*) over this block counts distinct cases (no victim fan-out here).
def filter_from(include_ext: bool = True) -> str:
    ext_join = (
        " LEFT JOIN cold_case.case_extractions_current ext"
        " ON ext.case_id = cases.case_id AND ext.prompt_tier = 1"
        if include_ext
        else ""
    )
    return (
        " FROM cold_case.cases AS cases"
        + ext_join
        + " JOIN etl.dataset_version dv ON dv.dataset_version_id = cases.dataset_version_id"
        + f" AND {PUBLISHED_ONLY}"
        + " JOIN etl.source_system ss ON ss.source_system_id = dv.source_system_id"
    )


# Shared WHERE clause. Every condition is `:param IS NULL OR <cond>`, so a
# caller disables any single dimension by binding NULL for its param. The list
# applies all of them; the faceted-count service exploits this to exclude a
# facet's OWN selection while keeping the others (standard faceted-nav counts,
# so toggling one value in a multi-select doesn't zero out its siblings).
#
# Year filters are written as sargable date ranges (incident_date is a DATE), not
# EXTRACT(YEAR FROM ...): EXTRACT is non-sargable and, more importantly, blinds
# the planner's row estimate (a 48x under-estimate was driving a bad Nested Loop
# join), whereas the range form gives accurate estimates and can use
# ix_cases_incident_date. The two forms are result-equivalent for a DATE column.
#
# The ext.weapon / ext.location_type conditions are emitted only when
# include_ext is True; they are no-ops when weapon/location_type are NULL, so a
# caller with neither filter set omits both the conditions and the ext join.
def filter_where(include_ext: bool = True) -> str:
    ext_conditions = (
        "    AND (:weapon        IS NULL OR ext.weapon = ANY(:weapon))\n"
        "    AND (:location_type IS NULL OR ext.location_type = ANY(:location_type))\n"
        if include_ext
        else ""
    )
    return f"""
  WHERE (:case_type IS NULL OR cases.case_type = ANY(:case_type))
    AND (:year_min  IS NULL OR cases.incident_date >= make_date(:year_min, 1, 1))
    AND (:year_max  IS NULL OR cases.incident_date <= make_date(:year_max, 12, 31))
    AND (:city      IS NULL OR cases.city = :city)
    AND (:state     IS NULL OR cases.state = :state)
{ext_conditions}    AND (:source_codes  IS NULL OR ss.source_code = ANY(:source_codes))
    AND (:precision     IS NULL OR cases.geocode_precision = ANY(:precision))
    AND (
      (:gender IS NULL AND :race IS NULL AND :race_other_exclude IS NULL)
      OR EXISTS (
        SELECT 1 FROM cold_case.victim v
         WHERE v.case_id = cases.case_id
           AND (:gender IS NULL OR v.gender = ANY(:gender))
           AND (
             (:race IS NULL AND :race_other_exclude IS NULL)
             OR (:race IS NOT NULL AND LOWER(v.race) = ANY(:race))
             OR (:race_other_exclude IS NOT NULL
                 AND v.race IS NOT NULL
                 AND LOWER(v.race) <> ALL(:race_other_exclude))
           )
      )
    )
    AND (:q IS NULL OR (
      cases.case_name ILIKE :q_like OR
      cases.source_case_id ILIKE :q_like OR
      EXISTS (
        SELECT 1 FROM cold_case.victim v
         WHERE v.case_id = cases.case_id
           AND (v.first_name ILIKE :q_like OR v.last_name ILIKE :q_like)
      )
    ))
"""


def build_filter_params(
    *,
    case_type: list[str] | None = None,
    year_min: int | None = None,
    year_max: int | None = None,
    city: str | None = None,
    state: str | None = None,
    gender: list[str] | None = None,
    race: list[str] | None = None,
    weapon: list[str] | None = None,
    location_type: list[str] | None = None,
    source_system: list[str] | None = None,
    precision: list[str] | None = None,
    q: str | None = None,
) -> dict[str, Any]:
    """Bind params for FILTER_WHERE.

    Expands gender and race to all stored source forms so the SQL match works
    regardless of which case/abbreviation the client sends (and so a canonical
    race bucket matches every raw spelling that folds into it). Keyed to match the
    `:param` names in FILTER_WHERE (note source_system → source_codes).
    """
    return {
        "case_type": case_type,
        "year_min": year_min,
        "year_max": year_max,
        "city": city,
        "state": state,
        "gender": expand_gender_filter(gender),
        "race": expand_race_filter(race),
        "race_other_exclude": race_exclude_filter(race),
        "weapon": weapon,
        "location_type": location_type,
        "source_codes": source_system,
        "precision": precision,
        "q": q,
        "q_like": f"%{_escape_like(q)}%" if q else None,
    }


def _escape_like(value: str) -> str:
    """Escape LIKE/ILIKE metacharacters so ``q`` is matched literally (SEC-B05).

    Postgres' default LIKE escape character is backslash, so escaping the
    backslash first, then ``%`` and ``_``, makes the wrapped ``%term%`` treat
    user wildcards as literal text. The value is already passed as a bound
    parameter, so this is about match semantics / scan cost, not SQL injection.
    """
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


# ORDER BY clause per SortOrder enum value. Every clause includes
# cases.case_id as a stable tiebreaker so pagination stays consistent
# across pages when many rows share a sort key. NULLS LAST is explicit
# on both ASC and DESC for keys that may be NULL — Postgres' default
# (NULLS FIRST on ASC) would otherwise dump null-name rows at the top.
# `primary_victim.first_name` / `last_name` references resolve via the
# LEFT JOIN LATERAL added in the list_cold_cases query below.
#
# COLLATE "C" on text sorts forces bytewise (ASCII) ordering. Without
# it, the database's en_US.utf8 default treats e.g. "WC98-..." and
# "alex-..." as equivalent on case, then secondary-sorts — producing
# results inconsistent with what users see in the rendered column.
# Bytewise sort matches the display string the user sees in the table
# header click, which is the UX contract for sortable column headers.
SORT_CLAUSES: dict[SortOrder, str] = {
    SortOrder.incident_date_desc: "cases.incident_date DESC NULLS LAST, cases.case_id DESC",
    SortOrder.incident_date_asc: "cases.incident_date ASC NULLS LAST, cases.case_id ASC",
    SortOrder.victim_name_asc: (
        "NULLIF(TRIM("
        "  COALESCE(primary_victim.first_name, '')"
        "  || ' '"
        "  || COALESCE(primary_victim.last_name, '')"
        "), '') COLLATE \"C\" ASC NULLS LAST,"
        " cases.case_id ASC"
    ),
    SortOrder.victim_name_desc: (
        "NULLIF(TRIM("
        "  COALESCE(primary_victim.first_name, '')"
        "  || ' '"
        "  || COALESCE(primary_victim.last_name, '')"
        "), '') COLLATE \"C\" DESC NULLS LAST,"
        " cases.case_id DESC"
    ),
    SortOrder.source_case_id_asc: ('cases.source_case_id COLLATE "C" ASC, cases.case_id ASC'),
    SortOrder.source_case_id_desc: ('cases.source_case_id COLLATE "C" DESC, cases.case_id DESC'),
    SortOrder.case_type_asc: 'cases.case_type COLLATE "C" ASC, cases.case_id ASC',
    SortOrder.case_type_desc: 'cases.case_type COLLATE "C" DESC, cases.case_id DESC',
    SortOrder.location_asc: (
        'cases.state COLLATE "C" ASC NULLS LAST,'
        ' cases.city COLLATE "C" ASC NULLS LAST,'
        " cases.case_id ASC"
    ),
    SortOrder.location_desc: (
        'cases.state COLLATE "C" DESC NULLS LAST,'
        ' cases.city COLLATE "C" DESC NULLS LAST,'
        " cases.case_id DESC"
    ),
    SortOrder.state_asc: 'cases.state COLLATE "C" ASC NULLS LAST, cases.case_id ASC',
    SortOrder.state_desc: 'cases.state COLLATE "C" DESC NULLS LAST, cases.case_id DESC',
}
