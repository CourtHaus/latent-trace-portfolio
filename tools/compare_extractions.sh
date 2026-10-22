#!/bin/bash
# Side-by-side comparison of two extraction model runs on the same NH cases.
#
# Usage:
#   tools/compare_extractions.sh <state> <model_a> <model_b>
#   tools/compare_extractions.sh NH 'qwen2.5:7b' 'gpt-4o-mini'
#
# Compares case_extractions rows for state=<state>, joining each case's
# pair of (model_a, model_b) rows at each tier, and reports:
#   - Coverage per model (rows present)
#   - Per-field agreement rates (Tier-1: weapon, location_type;
#     Tier-2: incident_date_text, address_text, victim_age_text,
#     victim_gender_text, victim_race_text)
#   - 10 sample disagreements per field for manual inspection.

set -u
export PGPASSWORD=casesignal
DB_HOST=localhost
DB_PORT=5433
DB_USER=casesignal
DB_NAME=casesignal

STATE="${1:-NH}"
MODEL_A="${2:-qwen2.5:7b}"
MODEL_B="${3:-gpt-4o-mini}"

PSQL="psql -h $DB_HOST -p $DB_PORT -U $DB_USER -d $DB_NAME -tAF|"

echo
echo "=== Compare ${STATE} extractions: ${MODEL_A}  vs  ${MODEL_B} ==="
echo

echo "--- Coverage (rows per model) ---"
$PSQL -c "
SELECT e.model_id, e.prompt_tier, COUNT(*) AS rows
  FROM cold_case.case_extractions e
  JOIN cold_case.cases c USING(case_id)
 WHERE c.state = '${STATE}'
   AND e.model_id IN ('${MODEL_A}', '${MODEL_B}')
 GROUP BY e.model_id, e.prompt_tier
 ORDER BY e.prompt_tier, e.model_id;" | column -t -s'|'

echo
echo "--- Tier-1 field agreement (weapon, location_type) ---"
$PSQL -c "
WITH paired AS (
    SELECT
        a.case_id,
        a.weapon         AS a_weapon,        b.weapon         AS b_weapon,
        a.location_type  AS a_location_type, b.location_type  AS b_location_type
      FROM cold_case.case_extractions a
      JOIN cold_case.case_extractions b
        ON a.case_id = b.case_id AND a.prompt_tier = b.prompt_tier
      JOIN cold_case.cases c ON c.case_id = a.case_id
     WHERE c.state = '${STATE}'
       AND a.model_id = '${MODEL_A}' AND b.model_id = '${MODEL_B}'
       AND a.prompt_tier = 1
)
SELECT
    'weapon'        AS field,
    COUNT(*)        AS pairs,
    COUNT(*) FILTER (WHERE a_weapon IS NOT DISTINCT FROM b_weapon)        AS agree,
    ROUND(100.0 * COUNT(*) FILTER (WHERE a_weapon IS NOT DISTINCT FROM b_weapon) / NULLIF(COUNT(*),0), 1) AS pct
  FROM paired
UNION ALL
SELECT 'location_type', COUNT(*),
    COUNT(*) FILTER (WHERE a_location_type IS NOT DISTINCT FROM b_location_type),
    ROUND(100.0 * COUNT(*) FILTER (WHERE a_location_type IS NOT DISTINCT FROM b_location_type) / NULLIF(COUNT(*),0), 1)
  FROM paired;" | column -t -s'|'

echo
echo "--- Tier-2 field agreement (incident_date / address / victim_age / victim_gender / victim_race) ---"
$PSQL -c "
WITH paired AS (
    SELECT
        a.case_id,
        a.incident_date_text  AS a_date,    b.incident_date_text  AS b_date,
        a.address_text        AS a_addr,    b.address_text        AS b_addr,
        a.victim_age_text     AS a_age,     b.victim_age_text     AS b_age,
        a.victim_gender_text  AS a_gender,  b.victim_gender_text  AS b_gender,
        a.victim_race_text    AS a_race,    b.victim_race_text    AS b_race
      FROM cold_case.case_extractions a
      JOIN cold_case.case_extractions b
        ON a.case_id = b.case_id AND a.prompt_tier = b.prompt_tier
      JOIN cold_case.cases c ON c.case_id = a.case_id
     WHERE c.state = '${STATE}'
       AND a.model_id = '${MODEL_A}' AND b.model_id = '${MODEL_B}'
       AND a.prompt_tier = 2
)
SELECT 'incident_date_text', COUNT(*),
       COUNT(*) FILTER (WHERE a_date IS NOT DISTINCT FROM b_date),
       ROUND(100.0 * COUNT(*) FILTER (WHERE a_date IS NOT DISTINCT FROM b_date) / NULLIF(COUNT(*),0), 1)
  FROM paired
UNION ALL
SELECT 'address_text', COUNT(*),
       COUNT(*) FILTER (WHERE a_addr IS NOT DISTINCT FROM b_addr),
       ROUND(100.0 * COUNT(*) FILTER (WHERE a_addr IS NOT DISTINCT FROM b_addr) / NULLIF(COUNT(*),0), 1)
  FROM paired
UNION ALL
SELECT 'victim_age_text', COUNT(*),
       COUNT(*) FILTER (WHERE a_age IS NOT DISTINCT FROM b_age),
       ROUND(100.0 * COUNT(*) FILTER (WHERE a_age IS NOT DISTINCT FROM b_age) / NULLIF(COUNT(*),0), 1)
  FROM paired
UNION ALL
SELECT 'victim_gender_text', COUNT(*),
       COUNT(*) FILTER (WHERE a_gender IS NOT DISTINCT FROM b_gender),
       ROUND(100.0 * COUNT(*) FILTER (WHERE a_gender IS NOT DISTINCT FROM b_gender) / NULLIF(COUNT(*),0), 1)
  FROM paired
UNION ALL
SELECT 'victim_race_text', COUNT(*),
       COUNT(*) FILTER (WHERE a_race IS NOT DISTINCT FROM b_race),
       ROUND(100.0 * COUNT(*) FILTER (WHERE a_race IS NOT DISTINCT FROM b_race) / NULLIF(COUNT(*),0), 1)
  FROM paired;" | column -t -s'|'

echo
echo "--- 10 sample Tier-1 disagreements (weapon OR location_type) ---"
$PSQL -c "
SELECT
    c.source_case_id,
    a.weapon || ' / ' || COALESCE(a.location_type,'-') AS a_t1,
    b.weapon || ' / ' || COALESCE(b.location_type,'-') AS b_t1
  FROM cold_case.case_extractions a
  JOIN cold_case.case_extractions b
    ON a.case_id = b.case_id AND a.prompt_tier = b.prompt_tier
  JOIN cold_case.cases c ON c.case_id = a.case_id
 WHERE c.state = '${STATE}'
   AND a.model_id = '${MODEL_A}' AND b.model_id = '${MODEL_B}'
   AND a.prompt_tier = 1
   AND (a.weapon IS DISTINCT FROM b.weapon OR a.location_type IS DISTINCT FROM b.location_type)
 ORDER BY c.source_case_id
 LIMIT 10;" | column -t -s'|'

echo
echo "--- 10 sample Tier-2 disagreements (any field) ---"
$PSQL -c "
SELECT
    c.source_case_id,
    'A: ' || COALESCE(a.incident_date_text,'-') || ' | ' || COALESCE(a.address_text,'-') || ' | ' ||
        COALESCE(a.victim_gender_text,'-') || ' | ' || COALESCE(a.victim_race_text,'-')  AS a_t2,
    'B: ' || COALESCE(b.incident_date_text,'-') || ' | ' || COALESCE(b.address_text,'-') || ' | ' ||
        COALESCE(b.victim_gender_text,'-') || ' | ' || COALESCE(b.victim_race_text,'-')  AS b_t2
  FROM cold_case.case_extractions a
  JOIN cold_case.case_extractions b
    ON a.case_id = b.case_id AND a.prompt_tier = b.prompt_tier
  JOIN cold_case.cases c ON c.case_id = a.case_id
 WHERE c.state = '${STATE}'
   AND a.model_id = '${MODEL_A}' AND b.model_id = '${MODEL_B}'
   AND a.prompt_tier = 2
   AND (a.incident_date_text IS DISTINCT FROM b.incident_date_text
     OR a.address_text       IS DISTINCT FROM b.address_text
     OR a.victim_age_text    IS DISTINCT FROM b.victim_age_text
     OR a.victim_gender_text IS DISTINCT FROM b.victim_gender_text
     OR a.victim_race_text   IS DISTINCT FROM b.victim_race_text)
 ORDER BY c.source_case_id
 LIMIT 10;" | column -t -s'|'

echo
echo "--- Cost summary (sum of cost_usd per model, where set) ---"
$PSQL -c "
SELECT e.model_id, COUNT(*) AS rows,
       ROUND(SUM(COALESCE(cost_usd, 0))::numeric, 4) AS total_usd
  FROM cold_case.case_extractions e
  JOIN cold_case.cases c USING(case_id)
 WHERE c.state = '${STATE}'
   AND e.model_id IN ('${MODEL_A}', '${MODEL_B}')
 GROUP BY e.model_id;" | column -t -s'|'

echo
echo "Done."
