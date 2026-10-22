"""download_case_photo must keep the destination under the photos root even if
a source-derived path segment is hostile (SEC-E02), without changing the path
for normal slugs.
"""

from __future__ import annotations

from pathlib import Path

from casesignal.etl.adapters.cold_case_md_shared.photo_helpers import (
    download_case_photo,
)


class _FakePolite:
    """Records the destination passed to fetch_to_file and writes a byte so the
    downstream sha256 read succeeds."""

    def __init__(self) -> None:
        self.dest: Path | None = None

    def fetch_to_file(self, url: str, dest: Path) -> Path:
        self.dest = dest
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"img")
        return dest


def test_malicious_source_case_id_cannot_escape_photos_root(tmp_path: Path) -> None:
    polite = _FakePolite()
    result = download_case_photo(
        polite,  # type: ignore[arg-type]
        "https://www.baltimorecountymd.gov/photo.jpg",
        source_key="bcounty",
        source_case_id="../../../../etc/passwd",
        sanitized_filename="photo.jpg",
        photos_root=tmp_path,
    )

    assert result is not None
    assert polite.dest is not None
    resolved = polite.dest.resolve()
    root = tmp_path.resolve()
    # Stays under the photos root; relative_to() raising would mean it escaped.
    assert root in resolved.parents
    rel = resolved.relative_to(root)
    assert ".." not in rel.parts


def test_normal_slug_path_is_unchanged(tmp_path: Path) -> None:
    polite = _FakePolite()
    download_case_photo(
        polite,  # type: ignore[arg-type]
        "https://www.baltimorecountymd.gov/p.jpg",
        source_key="bcounty",
        source_case_id="john-doe-2008",
        sanitized_filename="p.jpg",
        photos_root=tmp_path,
    )
    assert polite.dest == tmp_path / "bcounty" / "john-doe-2008" / "p.jpg"
