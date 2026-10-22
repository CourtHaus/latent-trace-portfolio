import hashlib
import json
import os
import re
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from casesignal.drafter import session as sess


def test_start_writes_a_manifest_with_a_session_id(tmp_path: Path) -> None:
    s = sess.start(tmp_path, "html", now="2026-08-31T14:02:11Z", nonce="a3f9")
    assert s.session_id == "20260831T140211Z-a3f9"
    assert (tmp_path / "manifest.json").exists()
    assert sess.load(tmp_path) == s


def test_record_hashes_the_body_and_appends_to_the_manifest(tmp_path: Path) -> None:
    s = sess.start(tmp_path, "html", now="2026-08-31T14:02:11Z", nonce="a3f9")
    rec = sess.record(
        s, tmp_path, path="listing_1.html", url="https://x/1", status=200, body=b"<html>"
    )
    assert rec.sha256 == hashlib.sha256(b"<html>").hexdigest()
    assert len(rec.sha256) == 64
    loaded = sess.load(tmp_path)
    assert loaded is not None
    assert loaded.fixtures[0].url == "https://x/1"


def test_already_fetched_is_true_only_for_recorded_urls(tmp_path: Path) -> None:
    s = sess.start(tmp_path, "html", now="2026-08-31T14:02:11Z", nonce="a3f9")
    sess.record(s, tmp_path, path="a.html", url="https://x/1", status=200, body=b"a")
    assert sess.already_fetched(s, "https://x/1") is True
    assert sess.already_fetched(s, "https://x/2") is False


def test_resume_with_the_same_session_id_returns_the_session(tmp_path: Path) -> None:
    s = sess.start(tmp_path, "html", now="2026-08-31T14:02:11Z", nonce="a3f9")
    assert sess.resume(tmp_path, s.session_id).session_id == s.session_id


def test_resume_with_a_different_session_id_refuses_and_names_both(tmp_path: Path) -> None:
    s = sess.start(tmp_path, "html", now="2026-08-31T14:02:11Z", nonce="a3f9")
    with pytest.raises(sess.SessionMismatch) as exc:
        sess.resume(tmp_path, "20260901T000000Z-bbbb")
    assert s.session_id in str(exc.value)
    assert "20260901T000000Z-bbbb" in str(exc.value)


# --- the manifest is written atomically, because it is rewritten per fetch ---


def test_start_leaves_nothing_beside_the_manifest(tmp_path: Path) -> None:
    # The write goes through a temp path and os.replace; no .tmp is left behind.
    sess.start(tmp_path, "html", now="2026-08-31T14:02:11Z", nonce="a3f9")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["manifest.json"]


def test_record_leaves_nothing_beside_the_manifest(tmp_path: Path) -> None:
    s = sess.start(tmp_path, "html", now="2026-08-31T14:02:11Z", nonce="a3f9")
    sess.record(s, tmp_path, path="a.html", url="https://x/1", status=200, body=b"a")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["manifest.json"]


def test_a_crash_during_the_manifest_write_leaves_the_previous_one_intact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The manifest is rewritten after every single fetch, so a torn write is a
    # live risk over a long crawl, not a theoretical one. Standing in for the
    # crash: os.replace fails, and the manifest still holds the last good state.
    s = sess.start(tmp_path, "html", now="2026-08-31T14:02:11Z", nonce="a3f9")
    sess.record(s, tmp_path, path="a.html", url="https://x/1", status=200, body=b"a")
    before = (tmp_path / "manifest.json").read_bytes()

    def boom(src: object, dst: object) -> None:
        raise OSError("killed mid-write")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        sess.record(s, tmp_path, path="b.html", url="https://x/2", status=200, body=b"b")
    assert (tmp_path / "manifest.json").read_bytes() == before


def test_start_creates_a_missing_draft_dir(tmp_path: Path) -> None:
    nested = tmp_path / "drafts" / "cold_case_ok_osbi"
    s = sess.start(nested, "html", now="2026-08-31T14:02:11Z", nonce="a3f9")
    assert (nested / "manifest.json").exists()
    assert sess.load(nested) == s


# --- the hash means "what the server sent", not "what is on disk now" ---


def test_record_hashes_the_body_not_the_file_on_disk(tmp_path: Path) -> None:
    # A global core.autocrlf=true (set on at least one dev box here) means a file
    # written and read back can differ from the bytes that arrived over the wire.
    # Hashing the response body is what keeps sha256 meaning "what the server sent".
    # The decoy sits where fixtures really land -- under fixtures_root, not beside
    # the manifest -- so a disk-reading implementation would actually find it.
    s = sess.start(tmp_path, "html", now="2026-08-31T14:02:11Z", nonce="a3f9", fixtures_root="fx")
    (tmp_path / "fx").mkdir()
    (tmp_path / "fx" / "a.html").write_bytes(b"something else entirely")
    rec = sess.record(s, tmp_path, path="a.html", url="https://x/1", status=200, body=b"<html>\n")
    assert rec.sha256 == hashlib.sha256(b"<html>\n").hexdigest()


# --- fixtures accumulate in order and survive a reload ---


def test_fixtures_reload_in_the_order_they_were_recorded(tmp_path: Path) -> None:
    s = sess.start(tmp_path, "html", now="2026-08-31T14:02:11Z", nonce="a3f9")
    sess.record(s, tmp_path, path="a.html", url="https://x/1", status=200, body=b"a")
    sess.record(s, tmp_path, path="b.html", url="https://x/2", status=404, body=b"b")
    loaded = sess.load(tmp_path)
    assert loaded is not None
    assert [(f.path, f.url, f.status) for f in loaded.fixtures] == [
        ("a.html", "https://x/1", 200),
        ("b.html", "https://x/2", 404),
    ]
    assert loaded == s


def test_fetched_at_defaults_to_the_session_start_and_is_kept_when_given(tmp_path: Path) -> None:
    s = sess.start(tmp_path, "html", now="2026-08-31T14:02:11Z", nonce="a3f9")
    default = sess.record(s, tmp_path, path="a.html", url="https://x/1", status=200, body=b"a")
    assert default.fetched_at == "2026-08-31T14:02:11Z"
    explicit = sess.record(
        s,
        tmp_path,
        path="b.html",
        url="https://x/2",
        status=200,
        body=b"b",
        fetched_at="2026-08-31T15:30:00Z",
    )
    assert explicit.fetched_at == "2026-08-31T15:30:00Z"


def test_a_fixture_record_is_immutable(tmp_path: Path) -> None:
    # Later tasks measure coverage over these records; nothing downstream may edit
    # what the capture observed.
    s = sess.start(tmp_path, "html", now="2026-08-31T14:02:11Z", nonce="a3f9")
    rec = sess.record(s, tmp_path, path="a.html", url="https://x/1", status=200, body=b"a")
    with pytest.raises(FrozenInstanceError):
        rec.url = "https://x/2"  # type: ignore[misc]


# --- an unreadable manifest refuses; it never degrades to "no session" ---


def test_load_returns_none_when_there_is_no_manifest(tmp_path: Path) -> None:
    assert sess.load(tmp_path) is None


def test_a_truncated_manifest_refuses_rather_than_reading_as_no_session(tmp_path: Path) -> None:
    # Unlike the lease, silence here is not safe: reading a damaged manifest as
    # "no session" would let a fresh session start over fixtures already on disk,
    # which is exactly the blending sessions exist to prevent.
    (tmp_path / "manifest.json").write_text("")
    with pytest.raises(sess.ManifestUnreadable):
        sess.load(tmp_path)
    with pytest.raises(sess.ManifestUnreadable):
        sess.resume(tmp_path, "20260831T140211Z-a3f9")


def test_a_manifest_missing_a_fixture_field_refuses(tmp_path: Path) -> None:
    # Schema drift: a manifest written before FixtureRecord gained a field cannot
    # be measured, so it must not be silently loaded either.
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {
                "session_id": "20260831T140211Z-a3f9",
                "shape": "html",
                "started_at": "2026-08-31T14:02:11Z",
                "fixtures_root": "fx",
                "fixtures": [{"path": "a.html", "url": "https://x/1"}],
            }
        )
    )
    with pytest.raises(sess.ManifestUnreadable):
        sess.load(tmp_path)


def test_a_manifest_missing_a_session_field_refuses(tmp_path: Path) -> None:
    (tmp_path / "manifest.json").write_text(json.dumps({"session_id": "20260831T140211Z-a3f9"}))
    with pytest.raises(sess.ManifestUnreadable):
        sess.load(tmp_path)


def test_the_unreadable_manifest_message_names_the_file(tmp_path: Path) -> None:
    (tmp_path / "manifest.json").write_text("{ not json")
    with pytest.raises(sess.ManifestUnreadable) as exc:
        sess.load(tmp_path)
    assert "manifest.json" in str(exc.value)


def test_a_manifest_holding_non_ascii_utf8_loads(tmp_path: Path) -> None:
    # Hand-edited manifests happen. The file is read as UTF-8 regardless of the
    # ambient locale, so a non-ASCII URL is not mistaken for a damaged manifest.
    (tmp_path / "manifest.json").write_bytes(
        json.dumps(
            {
                "session_id": "20260831T140211Z-a3f9",
                "shape": "html",
                "started_at": "2026-08-31T14:02:11Z",
                "fixtures_root": "fx",
                "fixtures": [
                    {
                        "path": "a.html",
                        "url": "https://x/naïve",
                        "status": 200,
                        "sha256": "0" * 64,
                        "fetched_at": "2026-08-31T14:02:11Z",
                    }
                ],
            },
            ensure_ascii=False,
        ).encode("utf-8")
    )
    loaded = sess.load(tmp_path)
    assert loaded is not None
    assert loaded.fixtures[0].url == "https://x/naïve"


# --- resume is the only way back into a session ---


def test_resume_without_a_manifest_names_the_requested_session(tmp_path: Path) -> None:
    with pytest.raises(sess.SessionMismatch) as exc:
        sess.resume(tmp_path, "20260831T140211Z-a3f9")
    assert "20260831T140211Z-a3f9" in str(exc.value)


def test_resume_returns_the_fixtures_already_captured(tmp_path: Path) -> None:
    s = sess.start(tmp_path, "html", now="2026-08-31T14:02:11Z", nonce="a3f9")
    sess.record(s, tmp_path, path="a.html", url="https://x/1", status=200, body=b"a")
    resumed = sess.resume(tmp_path, s.session_id)
    assert sess.already_fetched(resumed, "https://x/1") is True
    assert sess.already_fetched(resumed, "https://x/2") is False


def test_the_mismatch_message_points_at_the_escape_hatch(tmp_path: Path) -> None:
    # Task 15 surfaces this message verbatim, so the whole contract is asserted.
    sess.start(tmp_path, "html", now="2026-08-31T14:02:11Z", nonce="a3f9")
    with pytest.raises(sess.SessionMismatch) as exc:
        sess.resume(tmp_path, "20260901T000000Z-bbbb")
    assert "--refresh" in str(exc.value)


def test_start_replaces_an_earlier_session_in_the_same_directory(tmp_path: Path) -> None:
    # start() is the deliberate --refresh path. The manifest, not the directory
    # listing, is the record of what belongs to a session, so leftover files from
    # the previous one are never measured as part of the new one.
    first = sess.start(tmp_path, "html", now="2026-08-31T14:02:11Z", nonce="a3f9")
    sess.record(first, tmp_path, path="a.html", url="https://x/1", status=200, body=b"a")
    second = sess.start(tmp_path, "html", now="2026-09-02T09:00:00Z", nonce="bbbb")
    assert second.session_id == "20260902T090000Z-bbbb"
    assert second.fixtures == []
    assert sess.load(tmp_path) == second
    with pytest.raises(sess.SessionMismatch):
        sess.resume(tmp_path, first.session_id)


# --- the manifest locates its own fixtures ---


def test_the_manifest_records_the_fixtures_root(tmp_path: Path) -> None:
    # Fixtures do not live beside the manifest: Task 7 writes them to draft_dir/"fx".
    # Without the root on the session, "path": "listing_1.html" names a file the
    # manifest cannot find, and the sha256 cannot be re-checked against disk.
    s = sess.start(tmp_path, "html", now="2026-08-31T14:02:11Z", nonce="a3f9", fixtures_root="fx")
    assert s.fixtures_root == "fx"
    written = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert written["fixtures_root"] == "fx"
    loaded = sess.load(tmp_path)
    assert loaded is not None
    assert loaded.fixtures_root == "fx"


def test_the_fixtures_root_locates_the_file_a_record_names(tmp_path: Path) -> None:
    # The integrity check the sha256 exists for: re-hash the fixture on disk from
    # the manifest alone and confirm it is still the page the floors came from.
    s = sess.start(tmp_path, "html", now="2026-08-31T14:02:11Z", nonce="a3f9", fixtures_root="fx")
    (tmp_path / "fx").mkdir()
    (tmp_path / "fx" / "listing_1.html").write_bytes(b"<html>")
    sess.record(s, tmp_path, path="listing_1.html", url="https://x/1", status=200, body=b"<html>")
    loaded = sess.load(tmp_path)
    assert loaded is not None
    rec = loaded.fixtures[0]
    on_disk = (tmp_path / loaded.fixtures_root / rec.path).read_bytes()
    assert hashlib.sha256(on_disk).hexdigest() == rec.sha256


def test_the_fixtures_root_defaults_to_the_draft_directory(tmp_path: Path) -> None:
    s = sess.start(tmp_path, "html", now="2026-08-31T14:02:11Z", nonce="a3f9")
    assert s.fixtures_root == ""


def test_start_does_not_create_the_fixtures_root(tmp_path: Path) -> None:
    # Creating it belongs to the crawl, which is also what decides whether a
    # pre-existing directory is a resume or a collision.
    sess.start(tmp_path, "html", now="2026-08-31T14:02:11Z", nonce="a3f9", fixtures_root="fx")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["manifest.json"]


def test_a_manifest_missing_the_fixtures_root_refuses(tmp_path: Path) -> None:
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {
                "session_id": "20260831T140211Z-a3f9",
                "shape": "html",
                "started_at": "2026-08-31T14:02:11Z",
                "fixtures": [],
            }
        )
    )
    with pytest.raises(sess.ManifestUnreadable):
        sess.load(tmp_path)


def test_a_manifest_missing_the_fixtures_key_refuses(tmp_path: Path) -> None:
    # _save always writes the key, so its absence is damage, not an older shape.
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {
                "session_id": "20260831T140211Z-a3f9",
                "shape": "html",
                "started_at": "2026-08-31T14:02:11Z",
                "fixtures_root": "fx",
            }
        )
    )
    with pytest.raises(sess.ManifestUnreadable):
        sess.load(tmp_path)


# --- resume must answer "where is it?", not only "do I have it?" ---


def test_fetched_path_returns_the_recorded_path(tmp_path: Path) -> None:
    s = sess.start(tmp_path, "html", now="2026-08-31T14:02:11Z", nonce="a3f9", fixtures_root="fx")
    sess.record(s, tmp_path, path="detail_3.html", url="https://x/1", status=200, body=b"a")
    assert sess.fetched_path(s, "https://x/1") == "detail_3.html"
    assert sess.fetched_path(s, "https://x/2") is None


def test_fetched_path_maps_each_url_to_its_own_file(tmp_path: Path) -> None:
    s = sess.start(tmp_path, "html", now="2026-08-31T14:02:11Z", nonce="a3f9", fixtures_root="fx")
    sess.record(s, tmp_path, path="detail_1.html", url="https://x/1", status=200, body=b"a")
    sess.record(s, tmp_path, path="detail_2.html", url="https://x/2", status=200, body=b"b")
    assert sess.fetched_path(s, "https://x/1") == "detail_1.html"
    assert sess.fetched_path(s, "https://x/2") == "detail_2.html"


def test_a_resume_with_a_wider_sample_reads_the_originally_recorded_file(tmp_path: Path) -> None:
    # Run 1: --detail-sample 12 assigns this URL detail_3.html and then dies.
    first = sess.start(
        tmp_path, "html", now="2026-08-31T14:02:11Z", nonce="a3f9", fixtures_root="fx"
    )
    (tmp_path / "fx").mkdir()
    (tmp_path / "fx" / "detail_3.html").write_bytes(b"<html>page one</html>")
    sess.record(
        first,
        tmp_path,
        path="detail_3.html",
        url="https://x/case/1",
        status=200,
        body=b"<html>page one</html>",
    )

    # Run 2: --detail-sample 20 reshuffles the sampler, so the same URL comes round
    # as detail_7.html. Skipping the fetch is right; reading detail_7.html is not --
    # that file either does not exist or holds a different page entirely.
    resumed = sess.resume(tmp_path, first.session_id)
    assigned_this_run = "detail_7.html"
    assert sess.already_fetched(resumed, "https://x/case/1") is True
    recorded = sess.fetched_path(resumed, "https://x/case/1")
    assert recorded == "detail_3.html"
    assert recorded != assigned_this_run
    assert (
        tmp_path / resumed.fixtures_root / str(recorded)
    ).read_bytes() == b"<html>page one</html>"


def test_already_fetched_agrees_with_fetched_path(tmp_path: Path) -> None:
    s = sess.start(tmp_path, "html", now="2026-08-31T14:02:11Z", nonce="a3f9")
    sess.record(s, tmp_path, path="a.html", url="https://x/1", status=200, body=b"a")
    for url in ("https://x/1", "https://x/2"):
        assert sess.already_fetched(s, url) is (sess.fetched_path(s, url) is not None)


# --- one record per URL per session ---


def test_recording_a_url_twice_replaces_rather_than_appends(tmp_path: Path) -> None:
    # The double-call shape: a buggy caller must not double-count a page into the
    # coverage floors derived from this manifest.
    s = sess.start(tmp_path, "html", now="2026-08-31T14:02:11Z", nonce="a3f9")
    sess.record(s, tmp_path, path="a.html", url="https://x/1", status=200, body=b"a")
    sess.record(s, tmp_path, path="a.html", url="https://x/1", status=200, body=b"a")
    assert len(s.fixtures) == 1
    loaded = sess.load(tmp_path)
    assert loaded is not None
    assert len(loaded.fixtures) == 1


def test_a_retry_supersedes_the_response_it_replaces(tmp_path: Path) -> None:
    # The retry shape: a 502 recorded, then the response that finally arrived.
    s = sess.start(tmp_path, "html", now="2026-08-31T14:02:11Z", nonce="a3f9")
    sess.record(s, tmp_path, path="a.html", url="https://x/1", status=502, body=b"bad gateway")
    rec = sess.record(s, tmp_path, path="a.html", url="https://x/1", status=200, body=b"<html>")
    assert (rec.status, rec.sha256) == (200, hashlib.sha256(b"<html>").hexdigest())
    loaded = sess.load(tmp_path)
    assert loaded is not None
    assert [(f.status, f.sha256) for f in loaded.fixtures] == [
        (200, hashlib.sha256(b"<html>").hexdigest())
    ]


def test_a_replaced_record_keeps_its_position(tmp_path: Path) -> None:
    s = sess.start(tmp_path, "html", now="2026-08-31T14:02:11Z", nonce="a3f9")
    sess.record(s, tmp_path, path="a.html", url="https://x/1", status=502, body=b"a")
    sess.record(s, tmp_path, path="b.html", url="https://x/2", status=200, body=b"b")
    sess.record(s, tmp_path, path="a.html", url="https://x/1", status=200, body=b"a2")
    loaded = sess.load(tmp_path)
    assert loaded is not None
    assert [(f.url, f.status) for f in loaded.fixtures] == [
        ("https://x/1", 200),
        ("https://x/2", 200),
    ]


def test_a_replacement_keeps_fetched_path_pointing_at_one_file(tmp_path: Path) -> None:
    s = sess.start(tmp_path, "html", now="2026-08-31T14:02:11Z", nonce="a3f9")
    sess.record(s, tmp_path, path="a.html", url="https://x/1", status=502, body=b"a")
    sess.record(s, tmp_path, path="a_retry.html", url="https://x/1", status=200, body=b"b")
    assert sess.fetched_path(s, "https://x/1") == "a_retry.html"


# --- the session id is filename-safe for any ISO-8601 instant ---


def test_a_utc_offset_timestamp_yields_a_filename_safe_id(tmp_path: Path) -> None:
    # lease.py builds timestamps with isoformat(timespec="seconds"), which yields
    # "+00:00", not "Z". Stripping only "-" and ":" would leave the "+" in the id.
    s = sess.start(tmp_path, "html", now="2026-08-31T14:02:11+00:00", nonce="a3f9")
    assert s.session_id == "20260831T1402110000-a3f9"


def test_a_fractional_second_timestamp_yields_a_filename_safe_id(tmp_path: Path) -> None:
    s = sess.start(tmp_path, "html", now="2026-08-31T14:02:11.123456Z", nonce="a3f9")
    assert s.session_id == "20260831T140211123456Z-a3f9"


def test_every_session_id_is_filename_safe(tmp_path: Path) -> None:
    stamps = [
        "2026-08-31T14:02:11Z",
        "2026-08-31T14:02:11+00:00",
        "2026-08-31T14:02:11-04:00",
        "2026-08-31T14:02:11.123456+00:00",
        "2026-08-31 14:02:11",
        "2026-08-31T14:02:11,5Z",
    ]
    for stamp in stamps:
        session_id = sess.start(tmp_path, "html", now=stamp, nonce="a3f9").session_id
        assert re.fullmatch(r"[0-9A-Za-z]+-[0-9A-Za-z]+", session_id), session_id


def test_an_unsafe_nonce_cannot_smuggle_a_separator_into_the_id(tmp_path: Path) -> None:
    s = sess.start(tmp_path, "html", now="2026-08-31T14:02:11Z", nonce="a3/f9")
    assert s.session_id == "20260831T140211Z-a3f9"


# --- keep_only: the manifest describes the corpus the crawl actually walked ---


def test_keep_only_drops_records_for_urls_the_crawl_no_longer_reaches(tmp_path: Path) -> None:
    s = sess.start(tmp_path, "html", now="2026-08-31T14:02:11Z", nonce="a3f9")
    sess.record(s, tmp_path, path="a.html", url="https://x/1", status=200, body=b"a")
    sess.record(s, tmp_path, path="b.html", url="https://x/2", status=200, body=b"b")
    sess.record(s, tmp_path, path="c.html", url="https://x/3", status=200, body=b"c")

    dropped = sess.keep_only(s, tmp_path, urls={"https://x/1", "https://x/3"})

    assert [d.url for d in dropped] == ["https://x/2"]
    assert [f.path for f in s.fixtures] == ["a.html", "c.html"]
    loaded = sess.load(tmp_path)
    assert loaded is not None
    assert [f.url for f in loaded.fixtures] == ["https://x/1", "https://x/3"]


def test_keep_only_leaves_the_fixture_file_on_disk(tmp_path: Path) -> None:
    # Same posture as start(): the manifest stops naming the file, nothing deletes it.
    s = sess.start(tmp_path, "html", now="2026-08-31T14:02:11Z", nonce="a3f9")
    stale = tmp_path / "b.html"
    stale.write_bytes(b"b")
    sess.record(s, tmp_path, path="b.html", url="https://x/2", status=200, body=b"b")

    sess.keep_only(s, tmp_path, urls=set())

    assert stale.read_bytes() == b"b"
    assert s.fixtures == []


def test_keep_only_leaves_the_manifest_content_unchanged_when_nothing_is_dropped(
    tmp_path: Path,
) -> None:
    s = sess.start(tmp_path, "html", now="2026-08-31T14:02:11Z", nonce="a3f9")
    sess.record(s, tmp_path, path="a.html", url="https://x/1", status=200, body=b"a")
    before = (tmp_path / "manifest.json").read_bytes()

    assert sess.keep_only(s, tmp_path, urls={"https://x/1", "https://x/9"}) == []
    assert (tmp_path / "manifest.json").read_bytes() == before
