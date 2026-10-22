/**
 * Per-source descriptive metadata that doesn't live in the database.
 *
 * Counts, year ranges, and state come from the API
 * (`/api/v1/cold-cases/sources-summary`); the methodology copy below — method
 * label, URL, geocoding strategy, per-source caveats, completeness profile —
 * is editorial content keyed by `code`. Add a new entry here when ingesting
 * a new source; the methodology page picks it up automatically.
 */

/** A single field's representation by a source. */
export type CompletenessKind =
  | "structural" // provided directly by the source (best)
  | "extracted" // narrative-extracted by local LLM (anchored)
  | "county-level" // present but only at county granularity
  | "missing" // not in source at all
  | "none"; // not collected by Latent Trace

/**
 * Fields tracked in the completeness matrix. Order matters — it's the column
 * order on the methodology page.
 */
export const COMPLETENESS_FIELDS = [
  "case_name",
  "incident_date",
  "address",
  "city",
  "state",
  "gender",
  "race",
  "age",
  "weapon",
  "location_type",
  "narrative",
  "photograph",
] as const;

export type CompletenessField = (typeof COMPLETENESS_FIELDS)[number];

export type CompletenessProfile = Readonly<Record<CompletenessField, CompletenessKind>>;

export interface SourceCaveat {
  /** Short title, e.g. "Race not in narratives" */
  title: string;
  /** One- or two-sentence body. */
  body: string;
}

export interface SourceMetadata {
  /** Matches `etl.source_system.source_code`. */
  code: string;
  /** Short display label, e.g. "VSPCCD". Used in monospace eyebrows. */
  shortLabel: string;
  /** Display name; falls back to API `name` if absent. */
  displayName?: string;
  /** Public-facing publisher type, e.g. "State police", "County PD". */
  agencyType: string;
  /** Human jurisdiction label, e.g. "Statewide", "Baltimore County". */
  jurisdiction: string;
  /** Publisher URL. */
  url: string;
  /** Compact method label, e.g. "CSV · manual refresh", "web scrape · polite". */
  method: string;
  /**
   * One-line geocoding strategy summary. Sources that bypass the ladder
   * (because coordinates are supplied) should say so directly.
   */
  geocodingStrategy: string;
  /** Optional county FIPS for sub-state sources. */
  countyFips?: string;
  /** What each field looks like in this source. */
  completeness: CompletenessProfile;
  /** Optional caveats surfaced inline with this source's expanded row. */
  caveats?: ReadonlyArray<SourceCaveat>;
  /** Free-form notes for the expanded row. Kept short. */
  notes?: string;
}

const ALL_STRUCTURAL_FROM_VA: CompletenessProfile = {
  case_name: "structural",
  incident_date: "structural",
  address: "structural",
  city: "structural",
  state: "structural",
  gender: "structural",
  race: "structural",
  age: "structural",
  weapon: "extracted",
  location_type: "extracted",
  narrative: "structural",
  photograph: "none",
};

const MD_COUNTY_PROFILE: CompletenessProfile = {
  case_name: "structural",
  incident_date: "extracted",
  address: "extracted",
  city: "county-level",
  state: "structural",
  gender: "extracted",
  race: "missing",
  age: "extracted",
  weapon: "extracted",
  location_type: "extracted",
  narrative: "structural",
  photograph: "structural",
};

const STRUCTURAL_DEMOGRAPHICS_PROFILE: CompletenessProfile = {
  case_name: "structural",
  incident_date: "structural",
  address: "structural",
  city: "structural",
  state: "structural",
  gender: "structural",
  race: "structural",
  age: "structural",
  weapon: "extracted",
  location_type: "extracted",
  narrative: "structural",
  photograph: "structural",
};

const NO_LLM_NEEDED_PROFILE: CompletenessProfile = {
  ...STRUCTURAL_DEMOGRAPHICS_PROFILE,
  weapon: "structural",
  location_type: "structural",
};

const DC_PROFILE: CompletenessProfile = {
  case_name: "structural",
  incident_date: "structural",
  address: "structural",
  city: "structural",
  state: "structural",
  gender: "extracted",
  race: "missing",
  age: "missing",
  weapon: "extracted",
  location_type: "extracted",
  narrative: "structural",
  photograph: "structural",
};

const NH_PROFILE: CompletenessProfile = {
  case_name: "structural",
  incident_date: "extracted",
  address: "extracted",
  city: "structural",
  state: "structural",
  gender: "extracted",
  race: "missing",
  age: "structural",
  weapon: "extracted",
  location_type: "extracted",
  narrative: "structural",
  photograph: "none",
};

const MN_BCA_PROFILE: CompletenessProfile = {
  case_name: "structural",
  incident_date: "structural",
  address: "extracted",
  city: "structural",
  state: "structural",
  gender: "extracted",
  race: "extracted",
  age: "structural",
  weapon: "extracted",
  location_type: "extracted",
  narrative: "structural",
  photograph: "structural",
};

export const SOURCE_METADATA: Record<string, SourceMetadata> = {
  VSPCCD_VA: {
    code: "VSPCCD_VA",
    shortLabel: "VSPCCD",
    agencyType: "State police",
    jurisdiction: "Statewide",
    url: "https://vspccd.dcjs.virginia.gov/",
    method: "CSV · manual refresh",
    geocodingStrategy: "Source-provided coordinates (geocoding ladder skipped).",
    completeness: ALL_STRUCTURAL_FROM_VA,
  },
  BCOUNTY_MD_PD: {
    code: "BCOUNTY_MD_PD",
    shortLabel: "Baltimore County",
    agencyType: "County police",
    jurisdiction: "Baltimore County",
    url: "https://www.baltimorecountymd.gov/departments/police/unsolved/homicides",
    method: "web scrape · polite",
    geocodingStrategy: "Census street → ZIP centroid → county centroid.",
    countyFips: "24005",
    completeness: MD_COUNTY_PROFILE,
    caveats: [
      {
        title: "Race not in narratives",
        body:
          "Baltimore County narratives never state race. Cases show race as 'not provided' rather than imputing from photographs or names.",
      },
    ],
  },
  AACO_MD_PD: {
    code: "AACO_MD_PD",
    shortLabel: "Anne Arundel",
    agencyType: "County police",
    jurisdiction: "Anne Arundel County",
    url: "https://www.aacounty.org/police-department/crime-information/cold-cases",
    method: "web scrape · polite",
    geocodingStrategy: "Census street → ZIP centroid → county centroid (FIPS 24003).",
    countyFips: "24003",
    completeness: MD_COUNTY_PROFILE,
    notes:
      "Co-killed victims modeled as separate cases with a victim-name suffix to keep IDs unique.",
  },
  HOWARD_MD_PD: {
    code: "HOWARD_MD_PD",
    shortLabel: "Howard",
    agencyType: "County police",
    jurisdiction: "Howard County",
    url: "https://www.howardcountymd.gov/police/cold-cases",
    method: "web scrape · polite",
    geocodingStrategy: "Census street → ZIP centroid → county centroid (FIPS 24027).",
    countyFips: "24027",
    completeness: MD_COUNTY_PROFILE,
    notes:
      "Includes IDENTIFIED-prefix cases (unsolved homicides where the previously-unknown victim has been DNA-named).",
  },
  HARFORD_MD_SO: {
    code: "HARFORD_MD_SO",
    shortLabel: "Harford",
    agencyType: "Sheriff's office",
    jurisdiction: "Harford County",
    url: "https://harfordsheriff.org/wanted/cold-cases/",
    method: "web scrape · polite",
    geocodingStrategy: "Census street → ZIP centroid → county centroid (FIPS 24025).",
    countyFips: "24025",
    completeness: MD_COUNTY_PROFILE,
  },
  CCSO_MD_PD: {
    code: "CCSO_MD_PD",
    shortLabel: "Charles",
    agencyType: "Sheriff's office",
    jurisdiction: "Charles County",
    url: "https://www.ccso.us/crime/cold-cases/",
    method: "web scrape · polite",
    geocodingStrategy: "Census street → ZIP centroid → county centroid (FIPS 24017).",
    countyFips: "24017",
    completeness: MD_COUNTY_PROFILE,
    notes:
      "Index page groups cases by category; we ingest only the Homicides section. ARREST MADE entries are filtered out.",
  },
  WICO_MD_SO: {
    code: "WICO_MD_SO",
    shortLabel: "Wicomico",
    agencyType: "Sheriff's office",
    jurisdiction: "Wicomico County",
    url: "https://www.wicomicosheriff.com/coldCases",
    method: "web scrape · polite",
    geocodingStrategy: "Census street → ZIP centroid → county centroid (FIPS 24045).",
    countyFips: "24045",
    completeness: MD_COUNTY_PROFILE,
    notes:
      "Paginated card-tile index. Cases titled 'Missing Person -' are filtered; homicides only.",
  },
  MPDC_DC_PD: {
    code: "MPDC_DC_PD",
    shortLabel: "MPDC",
    agencyType: "Metropolitan police",
    jurisdiction: "Washington, D.C.",
    url: "https://mpdc.dc.gov/page/unsolved-homicides",
    method: "web scrape · PDF parsing · polite",
    geocodingStrategy: "Census street → ZIP centroid → DC-district centroid (FIPS 11001).",
    countyFips: "11001",
    completeness: DC_PROFILE,
    caveats: [
      {
        title: "Gender from honorifics only",
        body:
          "MPDC bulletins consistently use Mr./Mrs./Ms./Miss; gender is extracted only from these explicit narrative signals, never from photos or first names.",
      },
      {
        title: "DC is a federal district, not a state",
        body:
          "Latent Trace treats DC alongside states for filtering and display; the badge reads 'DC' and FIPS 11001 is the federal-district code.",
      },
    ],
  },
  CBI_CO_PD: {
    code: "CBI_CO_PD",
    shortLabel: "CBI",
    agencyType: "Bureau of Investigation",
    jurisdiction: "Statewide",
    url: "https://apps.colorado.gov/apps/coldcase/search.html",
    method: "web scrape · structured fields · polite",
    geocodingStrategy: "Census street → ZIP centroid → county centroid.",
    completeness: STRUCTURAL_DEMOGRAPHICS_PROFILE,
    notes:
      "State compendium from 86 county and municipal agencies. Detail pages publish structured first-party demographics plus federal cross-references to NamUs + NCMEC. Re-runs reflect current state (cases solved between runs drop out automatically).",
  },
  BCI_UT_PD: {
    code: "BCI_UT_PD",
    shortLabel: "BCI",
    agencyType: "Bureau of Criminal Identification",
    jurisdiction: "Statewide",
    url: "https://bci.utah.gov/coldcases/",
    method: "web scrape · structured fields · polite",
    geocodingStrategy: "Census street → ZIP centroid → county centroid.",
    completeness: STRUCTURAL_DEMOGRAPHICS_PROFILE,
    notes:
      "Statutory compendium. Utah SB 160 (2018) mandates agency submission, making this a stronger model than voluntary programs.",
  },
  BCI_OH_AG: {
    code: "BCI_OH_AG",
    shortLabel: "BCI",
    agencyType: "Attorney General's BCI",
    jurisdiction: "Statewide",
    url: "https://www.ohioattorneygeneral.gov/ColdCase",
    method: "browser-assisted index · web scrape · polite",
    geocodingStrategy: "Census street → ZIP centroid → county centroid.",
    completeness: STRUCTURAL_DEMOGRAPHICS_PROFILE,
    notes:
      "Cases submitted by Ohio's county sheriffs and municipal police departments. The AG hosts and publishes; the named local agency owns each investigation. ASP.NET WebForms index is harvested via a browser userscript; detail pages are fetched programmatically.",
  },
  WY_DCI: {
    code: "WY_DCI",
    shortLabel: "DCI",
    agencyType: "Division of Criminal Investigation",
    jurisdiction: "Statewide",
    url: "https://wyomingdci.wyo.gov/operations/cold-cases",
    method: "web scrape · structured fields · polite",
    geocodingStrategy: "Census street → ZIP centroid → county centroid.",
    completeness: NO_LLM_NEEDED_PROFILE,
    notes:
      "Submit-from-counties compendium. The roster mixes homicide and standalone sexual-assault cases; Latent Trace ingests homicides only. Weapon, scene type, and demographics are structured at source, so no LLM extraction is required.",
  },
  NH_DOJ: {
    code: "NH_DOJ",
    shortLabel: "NH DOJ",
    agencyType: "Attorney General's Cold Case Unit",
    jurisdiction: "Statewide",
    url: "https://www.doj.nh.gov/bureaus/new-hampshire-cold-case-unit/victim-list",
    method: "JSON API + detail scrape · hybrid",
    geocodingStrategy: "Census street → ZIP centroid → county centroid.",
    completeness: NH_PROFILE,
    caveats: [
      {
        title: "Race not published",
        body:
          "NH DOJ does not publish race and Latent Trace does not infer it. The correlation engine treats race as unknown for these cases (it doesn't contribute to scoring).",
      },
      {
        title: "Two case_type values",
        body:
          "NH publishes both unsolved homicides and suspicious deaths. We preserve the distinction (`case_type=suspicious_death` for deaths where a homicide determination hasn't been made).",
      },
    ],
  },
  BCA_MN: {
    code: "BCA_MN",
    shortLabel: "MN BCA",
    agencyType: "Bureau of Criminal Apprehension",
    jurisdiction: "Statewide",
    url: "https://portal.dps.mn.gov/bca/unsolved-cases/Pages/database.aspx",
    method: "browser-assisted harvest · PDF parse · polite",
    geocodingStrategy: "Census street → ZIP centroid → county centroid.",
    completeness: MN_BCA_PROFILE,
    caveats: [
      {
        title: "WAF-gated case list",
        body:
          "The BCA case list sits behind an Imperva web application firewall. Latent Trace harvests the list out-of-band via a one-time browser console request against the SharePoint API; per-case Summary-of-Case PDFs are static assets fetched programmatically.",
      },
      {
        title: "Narrative-derived modus operandi",
        body:
          "Weapon and location type are not published as structured fields. They are extracted from the SOC PDF narrative by the Tier-1/Tier-2 LLM pipeline and surfaced as a reviewable overlay, not source-of-truth.",
      },
    ],
  },
};

/**
 * Maryland sub-state coverage breakdown. Renders inside the expanded MD row.
 * Kept here (vs in DB) because the MD-internal jurisdiction taxonomy is
 * editorial: it answers "what's NOT here, and why" not "what we have."
 */
export const MD_COVERAGE = {
  covered: [
    "Baltimore County",
    "Anne Arundel",
    "Howard",
    "Harford",
    "Charles",
    "Wicomico",
  ],
  noRoster: [
    "Allegany",
    "Baltimore City",
    "Calvert",
    "Caroline",
    "Carroll",
    "Cecil",
    "Dorchester",
    "Frederick",
    "Garrett",
    "Kent",
    "Montgomery",
    "Prince George's",
    "Queen Anne's",
    "St. Mary's",
    "Talbot",
    "Washington",
    "Worcester",
  ],
  stateHandled: ["Somerset"],
} as const;
