"""Raw-load behavior for the OK OSBI adapter."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from casesignal.etl.adapters.cold_case_ok_osbi import raw_load


class FakePoliteHTTP:
    def __init__(self) -> None:
        self.fetch_dest: Path | None = None

    def head(self, url: str) -> SimpleNamespace:
        return SimpleNamespace(headers={"Content-Type": "image/jpeg"})

    def fetch_to_file(self, url: str, dest_path: Path) -> Path:
        self.fetch_dest = dest_path
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        dest_path.write_bytes(b"jpeg-bytes")
        return dest_path

    def get(self, url: str) -> None:
        raise AssertionError("_download_photo must stream through fetch_to_file")


def test_raw_table_name() -> None:
    assert raw_load._raw_table_name(9) == "raw_cold_case.cold_case_ok_osbi_dv9"


def test_download_photo_streams(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(raw_load, "_PHOTO_DIR_ROOT", tmp_path)
    polite = FakePoliteHTTP()
    record = raw_load._download_photo(
        polite=polite,
        source_case_id="james-middle-example-1984-11-15",
        idx=0,
        photo={"source_url": "https://oklahoma.gov/x.jpg", "filename_hint": "ADAMS_JAMES.jpg", "alt": "ADAMS_JAMES"},
    )
    assert polite.fetch_dest is not None and polite.fetch_dest.exists()
    assert record is not None
    assert record["filename"] == "00_ADAMS_JAMES.jpg"
    assert record["content_type"] == "image/jpeg"


def test_missing_entries_raises() -> None:
    class FakeContext:
        dataset_version_id = 1

        @staticmethod
        def get_metadata(key: str, default: object = None) -> object:
            return default

    with pytest.raises(RuntimeError, match="ok_entries missing"):
        raw_load.load_ok_raw(FakeContext())  # type: ignore[arg-type]
