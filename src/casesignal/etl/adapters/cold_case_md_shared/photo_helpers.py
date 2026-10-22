"""Shared photo-download helpers for MD-county adapters.

Detects known "no photo" placeholder URLs from county sites, downloads
real photos to data/photos/<source_key>/<source_case_id>/<filename>,
and computes SHA256.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from urllib.parse import urlparse

from casesignal.etl.services.photo_helpers import safe_filename
from casesignal.etl.services.photo_helpers import sha256_of_file as _sha256_of_file
from casesignal.etl.services.polite_http import PoliteHTTPClient

logger = logging.getLogger(__name__)


# Anchors match against the URL's PATH component (no query string).
# Drupal's image-style URLs append `?itok=<hash>` for cache invalidation;
# matching the raw URL would let those slip through.
# WordPress duplicate uploads append suffixes like -1, -1-2, -2-1 to filenames.
_PLACEHOLDER_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"/no[-_]?image(?:-\d+(?:-\d+)?)?\.(?:png|jpe?g)$", re.IGNORECASE),
    re.compile(r"/no[-_]?photo(?:-\d+(?:-\d+)?)?\.(?:png|jpe?g)$", re.IGNORECASE),
    re.compile(r"/placeholder[^/]*\.(?:png|jpe?g)$", re.IGNORECASE),
    re.compile(r"/blank[^/]*\.(?:png|jpe?g)$", re.IGNORECASE),
)


def _default_photos_root() -> Path:
    """Resolve the photos root from CASESIGNAL_PHOTOS_ROOT env var,
    falling back to "data/photos" relative to CWD."""
    return Path(os.getenv("CASESIGNAL_PHOTOS_ROOT", "data/photos"))


def is_placeholder_image_url(url: str) -> bool:
    """Return True if `url` matches a known no-photo placeholder pattern.

    Strips the query string before matching so Drupal-style URLs like
    `.../no-image.png?itok=FoiVQqMn` are correctly identified.
    """
    path = urlparse(url).path
    return any(p.search(path) for p in _PLACEHOLDER_PATTERNS)


def download_case_photo(
    polite: PoliteHTTPClient,
    image_url: str,
    *,
    source_key: str,
    source_case_id: str,
    sanitized_filename: str,
    photos_root: Path | None = None,
) -> tuple[Path, str] | None:
    """Download a case photo to data/photos/<source_key>/<source_case_id>/.

    Returns (local_path, sha256_hex) on success.
    Returns None if the URL matches a placeholder pattern (no real photo).
    Raises on actual download failure (FetchTooLarge, network error) so
    the caller can decide whether to skip-with-log or propagate.
    """
    if is_placeholder_image_url(image_url):
        logger.info(
            "Skipping placeholder photo for %s/%s: %s",
            source_key,
            source_case_id,
            image_url,
        )
        return None

    root = photos_root if photos_root is not None else _default_photos_root()
    # SEC-E02: sanitize the source-derived path segments inside the helper so a
    # future caller whose source_case_id/source_key isn't slug-constrained can't
    # traverse outside the photos root. safe_filename strips '/' and leading
    # dots, so it's a no-op on today's well-formed slugs (no path drift) while
    # neutralizing '..' / separators. sanitized_filename is already sanitized by
    # callers and is left untouched to avoid changing existing photo paths.
    dest = (
        root
        / safe_filename(source_key)
        / safe_filename(source_case_id)
        / sanitized_filename
    )
    polite.fetch_to_file(image_url, dest)
    sha = _sha256_of_file(dest)
    return (dest, sha)
