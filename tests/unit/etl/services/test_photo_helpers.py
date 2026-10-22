"""Tests for shared photo helpers (etl/services/photo_helpers.py)."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from casesignal.etl.services.photo_helpers import (
    PHOTO_EXT_BY_CONTENT_TYPE,
    safe_filename,
    sha256_of_bytes,
    sha256_of_file,
)

# --- PHOTO_EXT_BY_CONTENT_TYPE ---


def test_content_type_map_covers_known_image_types() -> None:
    assert PHOTO_EXT_BY_CONTENT_TYPE["image/jpeg"] == "jpg"
    assert PHOTO_EXT_BY_CONTENT_TYPE["image/pjpeg"] == "jpg"
    assert PHOTO_EXT_BY_CONTENT_TYPE["image/png"] == "png"
    assert PHOTO_EXT_BY_CONTENT_TYPE["image/gif"] == "gif"
    assert PHOTO_EXT_BY_CONTENT_TYPE["image/webp"] == "webp"
    assert PHOTO_EXT_BY_CONTENT_TYPE["image/bmp"] == "bmp"


def test_content_type_map_returns_none_for_unknown() -> None:
    assert PHOTO_EXT_BY_CONTENT_TYPE.get("application/pdf") is None
    assert PHOTO_EXT_BY_CONTENT_TYPE.get("text/html") is None
    assert PHOTO_EXT_BY_CONTENT_TYPE.get("") is None


# --- safe_filename ---


def test_safe_filename_passes_through_clean_names() -> None:
    assert safe_filename("victim_photo.jpg") == "victim_photo.jpg"
    assert safe_filename("exampleton-alex.png") == "exampleton-alex.png"


def test_safe_filename_substitutes_unsafe_chars() -> None:
    assert safe_filename("foo bar.jpg") == "foo_bar.jpg"
    assert safe_filename("photo (1).jpg") == "photo__1_.jpg"
    assert safe_filename("/etc/passwd") == "_etc_passwd"
    # Traversal attempt: slash becomes _, then lstrip eats the leading dots
    assert safe_filename("../parent.jpg") == "_parent.jpg"


def test_safe_filename_strips_leading_dot() -> None:
    # Hidden-file leading dot stripped to prevent dotfile creation
    assert safe_filename(".hidden") == "hidden"
    assert safe_filename("...weird") == "weird"


def test_safe_filename_truncates_to_100_chars() -> None:
    result = safe_filename("a" * 200)
    assert len(result) == 100
    assert result == "a" * 100


def test_safe_filename_fallback_on_empty_result() -> None:
    # If sanitization eats everything, fall back to 'photo'
    assert safe_filename("") == "photo"
    assert safe_filename(".") == "photo"
    assert safe_filename("...") == "photo"


# --- sha256_of_file ---


def test_sha256_of_file_matches_python_hashlib(tmp_path: Path) -> None:
    content = b"victim photo bytes" * 100
    f = tmp_path / "photo.bin"
    f.write_bytes(content)
    assert sha256_of_file(f) == hashlib.sha256(content).hexdigest()


def test_sha256_of_file_handles_empty_file(tmp_path: Path) -> None:
    f = tmp_path / "empty.bin"
    f.write_bytes(b"")
    assert sha256_of_file(f) == hashlib.sha256(b"").hexdigest()


def test_sha256_of_file_chunks_correctly_on_large_file(tmp_path: Path) -> None:
    # > 64KB chunk size to exercise the chunked-read path
    content = b"x" * (200 * 1024)
    f = tmp_path / "big.bin"
    f.write_bytes(content)
    assert sha256_of_file(f) == hashlib.sha256(content).hexdigest()


def test_sha256_of_file_raises_on_missing(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        sha256_of_file(tmp_path / "nope.bin")


# --- sha256_of_bytes ---


def test_sha256_of_bytes_matches_python_hashlib() -> None:
    content = b"victim photo bytes from a PDF"
    assert sha256_of_bytes(content) == hashlib.sha256(content).hexdigest()


def test_sha256_of_bytes_handles_empty() -> None:
    assert sha256_of_bytes(b"") == hashlib.sha256(b"").hexdigest()


def test_sha256_of_bytes_matches_file_hash(tmp_path: Path) -> None:
    # sha256_of_bytes(b) and sha256_of_file(f) where f contains b must agree
    content = b"the same bytes either way"
    f = tmp_path / "same.bin"
    f.write_bytes(content)
    assert sha256_of_bytes(content) == sha256_of_file(f)
