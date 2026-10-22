"""Unit tests for the cold_case_md_shared helper package."""

from __future__ import annotations

from casesignal.etl.adapters.cold_case_md_shared import constants


def test_constants_defines_md_state() -> None:
    assert constants.MD_STATE == "MD"


def test_constants_defines_known_county_fips() -> None:
    assert constants.MD_COUNTY_FIPS["baltimore_county"] == "24005"
    assert constants.MD_COUNTY_FIPS["anne_arundel"] == "24003"
    assert constants.MD_COUNTY_FIPS["howard"] == "24027"
    assert constants.MD_COUNTY_FIPS["harford"] == "24025"


def test_constants_defines_county_display_names() -> None:
    assert constants.MD_COUNTY_DISPLAY["baltimore_county"] == "Baltimore County"
    assert constants.MD_COUNTY_DISPLAY["anne_arundel"] == "Anne Arundel County"
    assert constants.MD_COUNTY_DISPLAY["howard"] == "Howard County"
    assert constants.MD_COUNTY_DISPLAY["harford"] == "Harford County"


def test_photo_helpers_detects_known_placeholders() -> None:
    from casesignal.etl.adapters.cold_case_md_shared.photo_helpers import (
        is_placeholder_image_url,
    )

    assert is_placeholder_image_url("https://example.com/files/no-image.png") is True
    assert (
        is_placeholder_image_url("https://example.com/sites/default/placeholder-no-photo.jpg")
        is True
    )
    assert is_placeholder_image_url("https://example.com/files/2008/andre-gay.jpg") is False


def test_placeholder_detection_handles_no_hyphen_variant() -> None:
    """The no-?image pattern should also catch noimage without hyphen."""
    from casesignal.etl.adapters.cold_case_md_shared.photo_helpers import (
        is_placeholder_image_url,
    )

    assert is_placeholder_image_url("https://example.com/files/noimage.png") is True


def test_placeholder_detection_handles_jpeg_extension() -> None:
    """The (?:png|jpe?g) alternation should match .jpeg too."""
    from casesignal.etl.adapters.cold_case_md_shared.photo_helpers import (
        is_placeholder_image_url,
    )

    assert is_placeholder_image_url("https://example.com/files/no-image.jpeg") is True


def test_placeholder_detection_handles_drupal_query_string() -> None:
    """Drupal image-style URLs append `?itok=<hash>`; the path-based
    matcher must still detect the placeholder underneath the query."""
    from casesignal.etl.adapters.cold_case_md_shared.photo_helpers import (
        is_placeholder_image_url,
    )

    assert (
        is_placeholder_image_url(
            "https://www.aacounty.org/sites/default/files/styles/large/public/2023-04/no-image.png?itok=FoiVQqMn"
        )
        is True
    )
    # Real photos with query strings stay non-placeholder
    assert (
        is_placeholder_image_url(
            "https://www.aacounty.org/sites/default/files/styles/large/public/2023-04/stewart-garfield.png?itok=nrGlDd5F"
        )
        is False
    )


def test_placeholder_detection_handles_underscore_variant() -> None:
    """Match the no_image / no_photo underscore variants used by some
    county PD sites (e.g. Harford Sheriff)."""
    from casesignal.etl.adapters.cold_case_md_shared.photo_helpers import (
        is_placeholder_image_url,
    )

    assert is_placeholder_image_url("https://example.com/files/no_image.png") is True


def test_placeholder_detection_handles_no_photo_filename() -> None:
    """Some county sites use the literal 'no_photo' filename for placeholder
    images (Harford Sheriff observed pattern)."""
    from casesignal.etl.adapters.cold_case_md_shared.photo_helpers import (
        is_placeholder_image_url,
    )

    assert is_placeholder_image_url("https://example.com/files/no_photo.png") is True
    assert is_placeholder_image_url("https://example.com/sites/default/no-photo.jpg") is True


def test_placeholder_detection_handles_wordpress_suffixed_no_photo() -> None:
    """WordPress generates duplicate-upload suffixes like
    no_photo-1.jpg, no_photo-1-2.jpg. Harford Sheriff's WordPress
    site uses these heavily."""
    from casesignal.etl.adapters.cold_case_md_shared.photo_helpers import (
        is_placeholder_image_url,
    )

    assert is_placeholder_image_url("https://example.com/wp-content/uploads/no_photo-1.jpg") is True
    assert (
        is_placeholder_image_url("https://example.com/wp-content/uploads/no_photo-1-2.jpg") is True
    )
    assert is_placeholder_image_url("https://example.com/wp-content/uploads/no-photo-3.png") is True


def test_placeholder_detection_handles_wordpress_suffixed_no_image() -> None:
    """Same WordPress suffix pattern for no_image variants."""
    from casesignal.etl.adapters.cold_case_md_shared.photo_helpers import (
        is_placeholder_image_url,
    )

    assert is_placeholder_image_url("https://example.com/wp-content/uploads/no_image-1.jpg") is True
    assert (
        is_placeholder_image_url("https://example.com/wp-content/uploads/no-image-2-1.png") is True
    )


def test_placeholder_detection_does_not_match_unrelated_suffixed_files() -> None:
    """Make sure the suffix-tolerance doesn't accidentally match real
    victim photo filenames that happen to contain numeric suffixes."""
    from casesignal.etl.adapters.cold_case_md_shared.photo_helpers import (
        is_placeholder_image_url,
    )

    assert is_placeholder_image_url("https://example.com/files/john-doe-2008-1.jpg") is False
    assert is_placeholder_image_url("https://example.com/files/photo-of-someone-1.jpg") is False
