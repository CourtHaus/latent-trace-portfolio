"""User-supplied ?q= must not inject LIKE wildcards (SEC-B05).

The search wraps q in %...% and matches with ILIKE. Without escaping, a user can
inject `%`/`_` wildcards (changing match semantics and enabling expensive
scans). q is parameterized so there is no SQL injection; this is about treating
the search term as a literal.
"""

from __future__ import annotations

from casesignal.api.services.cold_cases.filters import build_filter_params


def test_plain_query_is_wrapped_unchanged() -> None:
    assert build_filter_params(q="smith")["q_like"] == "%smith%"


def test_none_query_stays_none() -> None:
    assert build_filter_params(q=None)["q_like"] is None


def test_like_metacharacters_are_escaped() -> None:
    # %, _ and backslash must be escaped so they match literally.
    # input:  50%_x\y   -> escape \ first, then % and _, then wrap in %...%
    assert build_filter_params(q="50%_x\\y")["q_like"] == "%50\\%\\_x\\\\y%"


def test_wildcard_only_query_cannot_match_everything() -> None:
    # A bare "%" must become a literal percent search, not a match-all wildcard.
    assert build_filter_params(q="%")["q_like"] == "%\\%%"
