"""Cold-case slug generation + collision resolution.

Slugs live in `cold_case.cases.slug` as a NOT NULL UNIQUE column. They're
recomputed at INSERT and UPDATE time from case_name, city, state, and year.
Stale slugs in shared URLs are handled by a canonical-form 308 redirect
in the frontend RSC — see `app/cold-cases/[id]/[slug]/page.tsx`.
"""

from __future__ import annotations

from slugify import slugify
from sqlalchemy import text
from sqlalchemy.orm import Session

_MAX_SLUG_LENGTH = 80


def build_case_slug(
    case_name: str,
    city: str | None,
    state: str,
    year: int | None,
) -> str:
    """Build the base slug (pre-uniqueness-suffix) for a cold case.

    Composition: {case_name}-{city}-{state}-{year}, with nullable segments
    (city, year) omitted entirely rather than leaving an empty `-` gap.

    The suffix (city/state/year) is preserved when the total slug would
    exceed _MAX_SLUG_LENGTH — only the case_name segment is truncated.
    State is the most disambiguating short token; losing it on long
    case_names produced unrecognizable slugs.
    """
    if not case_name or not case_name.strip():
        raise ValueError(f"case_name must be a non-empty string, got {case_name!r}")

    suffix_parts: list[str] = []
    if city:
        suffix_parts.append(city)
    suffix_parts.append(state)
    if year is not None:
        suffix_parts.append(str(year))
    suffix = slugify(" ".join(suffix_parts), lowercase=True, separator="-")

    # Reserve room for suffix + the connecting hyphen between case-name and suffix.
    available = _MAX_SLUG_LENGTH - len(suffix) - 1
    if available < 1:
        # Pathological: suffix alone fills the budget. Fall back to the
        # original "everything together" behavior so we never produce
        # a name-less slug.
        return slugify(
            f"{case_name} {' '.join(suffix_parts)}",
            lowercase=True,
            separator="-",
            max_length=_MAX_SLUG_LENGTH,
        )

    case_part = slugify(
        case_name,
        lowercase=True,
        separator="-",
        max_length=available,
    )
    return f"{case_part}-{suffix}" if suffix else case_part


def resolve_slug_collision(
    session: Session,
    base: str,
    exclude_case_id: int | None = None,
) -> str:
    """Return `base`, or `base-2` / `base-3` / etc. if `base` is taken.

    Checks `cold_case.cases.slug` for existing rows matching `base` or
    `base-<N>`. When updating an existing case (slug recomputed after a
    field change), pass the current case_id as `exclude_case_id` so its
    own row doesn't block reuse of its current slug.
    """
    pattern = f"{base}-%"
    query = text("""
        SELECT slug FROM cold_case.cases
         WHERE (slug = :base OR slug LIKE :pattern)
           AND (:exclude IS NULL OR case_id != :exclude)
    """)
    existing = set(
        session.execute(
            query,
            {"base": base, "pattern": pattern, "exclude": exclude_case_id},
        )
        .scalars()
        .all()
    )

    if base not in existing:
        return base

    n = 2
    while f"{base}-{n}" in existing:
        n += 1
    return f"{base}-{n}"
