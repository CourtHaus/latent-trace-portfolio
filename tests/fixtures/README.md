# Test data in the portfolio snapshot

This repository distributes synthetic examples only under this directory.
The four `scout/` files model discovery catalogs, a search result, and a classifier
verdict. Their counts and field values are test inputs, not published coverage
measurements; the verdict uses an invented person. Agency endpoints identify
parser formats and are not fetched by these fixture tests.

Additional synthetic HTML, JSON, CSV, and PDF examples are constructed in tests.
They exercise parser boundaries, mapping, queues, API behavior, and generated
adapter verification without requiring a production corpus or hosted model.
Names and dates in these examples do not describe a real case.

Agency HTML/PDF captures, photographs, bulk exports, original extraction labels,
and recorded model narratives are intentionally absent. The corresponding
capture-dependent regression modules are retained only in the private working
repository. No missing-fixture skip mechanism substitutes for these tests here.
The public synthetic suite does not measure live-source drift or model accuracy.

Add only minimal invented records. Use reserved example domains for invented
URLs, `555-01xx` numbers for fictional North American contacts, and explicit
synthetic identifiers. If a source-specific selector requires an agency host,
keep the path fictional and stub all HTTP access. Do not fetch images in tests.

Census reference tables are documented [separately](../../data/static/README.md).
The project [rights notice](../../LICENSE) does not relicense external material.
