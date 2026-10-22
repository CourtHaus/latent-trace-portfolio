"""Small helpers for typing BeautifulSoup4 results.

BS4's `.get("href")` is typed `str | AttributeValueList | None` because some
HTML attributes are multi-valued (class, rel). For attributes that are
single-valued in practice (href, src, alt), this is overly pessimistic and
forces every caller to do isinstance gymnastics. These helpers normalize
the type so call sites stay readable.
"""

from __future__ import annotations

from bs4 import Tag


def attr_str(tag: Tag, name: str) -> str | None:
    """Read a single-valued HTML attr as `str | None`.

    Returns None when the attribute is absent OR when BS4 hands back an
    empty list (rare but allowed by the type). When the attr value is a
    list (multi-valued), returns the first element — these callers always
    treat href/src/alt as single-valued.
    """
    val = tag.get(name)
    if val is None:
        return None
    if isinstance(val, list):
        return val[0] if val else None
    return val
