from typing import Any

import pytest

from casesignal.etl.services.db import create_session_factory
from tests.integration._audit_harness import RawRow, audit_corpus
from tests.integration._seed import CaseSpec, ContactSpec, ExtractionSpec, VictimSpec
from tools.audit import rules_fl


@pytest.fixture
def sf(db_engine: Any) -> Any:
    return create_session_factory(db_engine)


def ctx_case_id(ctx: Any, sf: Any, source_case_id: str) -> int:
    from sqlalchemy import text
    with sf() as s:
        return int(
            s.execute(
                text("SELECT case_id FROM cold_case.cases "
                     "WHERE dataset_version_id=:dv AND source_case_id=:scid"),
                {"dv": ctx.dataset_version_id, "scid": source_case_id},
            ).scalar_one()
        )


def test_r1_title_as_narrative(sf: Any) -> None:
    cases = [
        CaseSpec(source_case_id="A", case_name="Real Title Case", state="FL"),
        CaseSpec(source_case_id="B", case_name="trapped sentence here.", state="FL"),
    ]
    raws = [
        RawRow(source_case_id="A", case_title="Real Title Case",
               narrative="A proper narrative paragraph that is long enough to be prose."),
        RawRow(source_case_id="B",
               case_title="victim's nude body was discovered deceased in a road side ditch by passerby.",
               narrative=""),
    ]
    with audit_corpus(sf, cases=cases, raw_rows=raws) as ctx:
        with sf() as s:
            f = rules_fl.r1_title_as_narrative(s, ctx)
        assert f.count == 1
        assert f.verify_items and f.verify_items[0]["case_id"] == ctx_case_id(ctx, sf, "B")


def test_r3_sentinel_address(sf: Any) -> None:
    cases = [CaseSpec(source_case_id="A", case_name="C", state="FL"),
             CaseSpec(source_case_id="B", case_name="C", state="FL")]
    raws = [RawRow(source_case_id="A", incident_address="501 E Bay St"),
            RawRow(source_case_id="B", incident_address=",")]
    with audit_corpus(sf, cases=cases, raw_rows=raws) as ctx:
        with sf() as s:
            f = rules_fl.r3_sentinel_address(s, ctx)
        assert f.count == 1


def test_r4_agency_cluster(sf: Any) -> None:
    cases = [CaseSpec(source_case_id=str(i), case_name="C", state="FL") for i in range(6)]
    raws = [RawRow(source_case_id=str(i), incident_address="501 E Bay St") for i in range(6)]
    with audit_corpus(sf, cases=cases, raw_rows=raws) as ctx:
        with sf() as s:
            f = rules_fl.r4_agency_cluster(s, ctx)
        assert f.count == 6
        assert f.verify_items


def test_r5_name_no_comma(sf: Any) -> None:
    cases = [CaseSpec(source_case_id="A", case_name="C", state="FL"),
             CaseSpec(source_case_id="B", case_name="C", state="FL")]
    raws = [RawRow(source_case_id="A", victim_name="Daniluk, Andrea Denise"),
            RawRow(source_case_id="B", victim_name="Woolsoncroft Carol")]
    with audit_corpus(sf, cases=cases, raw_rows=raws) as ctx:
        with sf() as s:
            f = rules_fl.r5_name_no_comma(s, ctx)
        assert f.count == 1


def test_r6_unnamed_victim(sf: Any) -> None:
    cases = [CaseSpec(source_case_id="A", case_name="C", state="FL"),
             CaseSpec(source_case_id="B", case_name="C", state="FL")]
    raws = [RawRow(source_case_id="A", victim_name="Smith, John"),
            RawRow(source_case_id="B", victim_name="")]
    with audit_corpus(sf, cases=cases, raw_rows=raws) as ctx:
        with sf() as s:
            f = rules_fl.r6_unnamed_victim(s, ctx)
        assert f.count == 1


def test_r8_missing_date(sf: Any) -> None:
    cases = [CaseSpec(source_case_id="A", case_name="C", state="FL"),
             CaseSpec(source_case_id="B", case_name="C", state="FL")]
    raws = [RawRow(source_case_id="A", incident_date="01-24-2006"),
            RawRow(source_case_id="B", incident_date="",
                   narrative="On January 24, 2006 she went missing")]
    with audit_corpus(sf, cases=cases, raw_rows=raws) as ctx:
        with sf() as s:
            f = rules_fl.r8_missing_date(s, ctx)
        assert f.count == 1
        assert "recoverable" in f.detail.lower()


def test_r2_empty_narrative(sf: Any) -> None:
    cases = [CaseSpec(source_case_id="A", case_name="C", state="FL"),
             CaseSpec(source_case_id="B", case_name="C", state="FL")]
    raws = [RawRow(source_case_id="A", narrative="A real narrative paragraph here."),
            RawRow(source_case_id="B", narrative="")]
    with audit_corpus(sf, cases=cases, raw_rows=raws) as ctx:
        with sf() as s:
            f = rules_fl.r2_empty_narrative(s, ctx)
        assert f.count == 1


def test_r7_dob_shape(sf: Any) -> None:
    cases = [CaseSpec(source_case_id="A", case_name="C", state="FL"),
             CaseSpec(source_case_id="B", case_name="C", state="FL"),
             CaseSpec(source_case_id="C", case_name="C", state="FL")]
    raws = [RawRow(source_case_id="A", dob="05-20-1981"),   # plausible -> not flagged
            RawRow(source_case_id="B", dob="01-01-1850"),   # pre-1900 -> flagged
            RawRow(source_case_id="C", dob="13-45-9999")]   # unparseable -> flagged
    with audit_corpus(sf, cases=cases, raw_rows=raws) as ctx:
        with sf() as s:
            f = rules_fl.r7_dob_shape(s, ctx)
        assert f.count == 2


def test_r9_row_count_match(sf: Any) -> None:
    cases = [CaseSpec(source_case_id="A", case_name="C", state="FL")]
    raws = [RawRow(source_case_id="A")]
    with audit_corpus(sf, cases=cases, raw_rows=raws) as ctx:
        with sf() as s:
            f = rules_fl.r9_row_count(s, ctx)
        assert f.count == 0  # aligned -> no finding


def test_r10_contact_address_mismap(sf: Any) -> None:
    cases = [CaseSpec(source_case_id="A", case_name="C", state="FL",
                      contact=ContactSpec(last_name="Orlando PD"))]
    raws = [RawRow(source_case_id="A", reporting_agency="Orlando PD",
                   agency_address="500 W Sampleton St")]
    with audit_corpus(sf, cases=cases, raw_rows=raws) as ctx:
        with sf() as s:
            f = rules_fl.r10_contact_address_mismap(s, ctx)
        # contact.address is NULL (seed sets only last_name) while raw has an
        # agency_address -> the mismap rule fires.
        assert f.count >= 1


def test_r10_clean_when_contact_carries_agency_address(sf: Any) -> None:
    # The rewritten transform puts the agency address into contact.address, so
    # R10 must NOT fire — regression against the stale-rule false positive.
    from sqlalchemy import text
    cases = [CaseSpec(source_case_id="A", case_name="C", state="FL",
                      contact=ContactSpec(last_name="Orlando PD"))]
    raws = [RawRow(source_case_id="A", reporting_agency="Orlando PD",
                   agency_address="500 W Sampleton St")]
    with audit_corpus(sf, cases=cases, raw_rows=raws) as ctx:
        with sf() as s:
            s.execute(
                text("UPDATE cold_case.contact SET address='500 W Sampleton St' "
                     "WHERE case_id IN (SELECT case_id FROM cold_case.cases "
                     "WHERE dataset_version_id=:dv)"),
                {"dv": ctx.dataset_version_id},
            )
            s.commit()
        with sf() as s:
            f = rules_fl.r10_contact_address_mismap(s, ctx)
        assert f.count == 0


def test_r10_skips_sentinel_agency_address(sf: Any) -> None:
    # A sentinel raw agency_address ("Unknown"/"N/A"/",") is clean_sentinel'd to
    # NULL contact.address by the transform, so R10 must NOT flag it (false
    # positive guard — Codex review on PR #150).
    cases = [CaseSpec(source_case_id="A", case_name="C", state="FL",
                      contact=ContactSpec(last_name="Orlando PD"))]
    raws = [RawRow(source_case_id="A", reporting_agency="Orlando PD",
                   agency_address="Unknown")]
    with audit_corpus(sf, cases=cases, raw_rows=raws) as ctx:
        with sf() as s:
            f = rules_fl.r10_contact_address_mismap(s, ctx)
        assert f.count == 0


def test_r12_source_label_honesty(sf: Any) -> None:
    from sqlalchemy import text
    cases = [CaseSpec(source_case_id=str(i), case_name="C", state="FL",
                      address="501 E Bay St") for i in range(6)]
    raws = [RawRow(source_case_id=str(i), incident_address="501 E Bay St") for i in range(6)]
    with audit_corpus(sf, cases=cases, raw_rows=raws) as ctx:
        # seed_corpus does not set address_source; set it so the rule has something
        # to flag (mirrors the live transform which writes address_source='source').
        with sf() as s:
            s.execute(
                text("UPDATE cold_case.cases SET address_source='source' "
                     "WHERE dataset_version_id=:dv"),
                {"dv": ctx.dataset_version_id},
            )
            s.commit()
        with sf() as s:
            f = rules_fl.r12_source_label_honesty(s, ctx)
        assert f.count == 6  # all 6 share a clustered address AND are source-labelled


def test_r14_city_null_rate(sf: Any) -> None:
    cases = [CaseSpec(source_case_id="A", case_name="C", state="FL", city=None),
             CaseSpec(source_case_id="B", case_name="C", state="FL", city="Tampa")]
    raws = [RawRow(source_case_id="A"), RawRow(source_case_id="B")]
    with audit_corpus(sf, cases=cases, raw_rows=raws) as ctx:
        with sf() as s:
            f = rules_fl.r14_city_null_rate(s, ctx)
        assert f.count == 1


def test_r15_extraction_coverage(sf: Any) -> None:
    cases = [
        CaseSpec(source_case_id="A", case_name="C", state="FL",
                 extractions=[ExtractionSpec(prompt_tier=1, weapon="firearm")]),
        CaseSpec(source_case_id="B", case_name="C", state="FL"),  # no extraction
    ]
    raws = [RawRow(source_case_id="A"), RawRow(source_case_id="B", narrative="")]
    with audit_corpus(sf, cases=cases, raw_rows=raws) as ctx:
        with sf() as s:
            f = rules_fl.r15_extraction_coverage(s, ctx)
        assert f.count == 1


def test_r18_victim_age_gap(sf: Any) -> None:
    cases = [CaseSpec(source_case_id="A", case_name="C", state="FL",
                      victims=[VictimSpec(first_name="J", last_name="K")])]
    raws = [RawRow(source_case_id="A", dob="05-20-1981")]
    with audit_corpus(sf, cases=cases, raw_rows=raws) as ctx:
        with sf() as s:
            f = rules_fl.r18_victim_age_gap(s, ctx)
        assert isinstance(f.count, int)


def test_r20_duplicate_victim(sf: Any) -> None:
    cases = [CaseSpec(source_case_id="A", case_name="C", state="FL",
                      victims=[VictimSpec(first_name="Jane", last_name="Doe")]),
             CaseSpec(source_case_id="B", case_name="C", state="FL",
                      victims=[VictimSpec(first_name="Jane", last_name="Doe")])]
    raws = [RawRow(source_case_id="A"), RawRow(source_case_id="B")]
    with audit_corpus(sf, cases=cases, raw_rows=raws) as ctx:
        with sf() as s:
            f = rules_fl.r20_duplicate_victim(s, ctx)
        assert f.count >= 2


def test_r20_skips_unidentified_victims(sf: Any) -> None:
    # Two distinct unidentified decedents (first_name "Unknown", NULL dob) must
    # NOT be flagged as duplicates of each other.
    cases = [CaseSpec(source_case_id="A", case_name="C", state="FL",
                      victims=[VictimSpec(first_name="Unknown", last_name="")]),
             CaseSpec(source_case_id="B", case_name="C", state="FL",
                      victims=[VictimSpec(first_name="Unknown", last_name="")])]
    raws = [RawRow(source_case_id="A"), RawRow(source_case_id="B")]
    with audit_corpus(sf, cases=cases, raw_rows=raws) as ctx:
        with sf() as s:
            f = rules_fl.r20_duplicate_victim(s, ctx)
        assert f.count == 0
