import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { RelatedCasesPanel, type Correlation } from "./RelatedCasesPanel";

const trackMock = vi.hoisted(() => vi.fn());
vi.mock("@/lib/analytics/client", () => ({ track: trackMock }));

const mkCorrelation = (overrides: Partial<Correlation> = {}): Correlation => ({
  case_id: 42,
  slug: "jane-doe-richmond-va-1992",
  victim_primary_name: "Jane Doe",
  city: "Richmond",
  state: "VA",
  year: 1992,
  score: 2.5,
  score_max: 10,
  proximity_factor: 0.55,
  matched_dimensions: [
    { name: "weapon", value: "firearm", low_confidence: false, weight: 6.0 },
    { name: "victim_gender", value: "F", low_confidence: false, weight: 1.5 },
    { name: "victim_age", value: "34 & 36", low_confidence: false, weight: 2.0 },
  ],
  distance_miles: 12.4,
  years_apart: 8,
  ...overrides,
});

const confidentExtraction = {
  weapon: { value: "firearm", raw_phrase: "shot", source_start: 0, source_end: 4, low_confidence: false },
  location_type: { value: "residence", raw_phrase: "home", source_start: 5, source_end: 9, low_confidence: false },
  model_id: "qwen2.5:7b",
  extracted_at: "2026-04-25T00:00:00Z",
};

describe("RelatedCasesPanel", () => {
  it("renders the panel header with the actual count", () => {
    render(
      <RelatedCasesPanel
        fromCaseId={1}
        parentExtraction={confidentExtraction}
        correlations={[mkCorrelation(), mkCorrelation({ case_id: 43 })]}
      />,
    );
    expect(
      screen.getByRole("heading", { name: /cases with shared characteristics \(2\)/i }),
    ).toBeInTheDocument();
  });

  it("includes the methodology link in the header", () => {
    render(
      <RelatedCasesPanel fromCaseId={1} parentExtraction={confidentExtraction} correlations={[mkCorrelation()]} />,
    );
    const link = screen.getByRole("link", { name: /about this/i });
    expect(link).toHaveAttribute("href", "/methodology#correlation");
  });

  it("renders empty state when correlations is []", () => {
    render(<RelatedCasesPanel fromCaseId={1} parentExtraction={confidentExtraction} correlations={[]} />);
    expect(
      screen.getByText(/no plausible matches in geographic \+ temporal proximity/i),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /methodology/i })).toBeInTheDocument();
  });

  it("does NOT render banner when both MO dims are concrete (2-MO state)", () => {
    render(<RelatedCasesPanel fromCaseId={1} parentExtraction={confidentExtraction} correlations={[mkCorrelation()]} />);
    expect(screen.queryByText(/MO classification not available/i)).toBeNull();
    expect(screen.queryByText(/Only the .* dimension is available/i)).toBeNull();
  });

  it("renders 0-MO banner when extraction is null", () => {
    render(<RelatedCasesPanel fromCaseId={1} parentExtraction={null} correlations={[]} />);
    expect(
      screen.getByText(
        /MO classification not available for this case\. Correlations limited to demographic matches/i,
      ),
    ).toBeInTheDocument();
  });

  it("renders 0-MO banner when both weapon and location_type are unknown", () => {
    render(
      <RelatedCasesPanel
        fromCaseId={1}
        parentExtraction={{
          weapon: { value: "unknown", raw_phrase: null, source_start: null, source_end: null, low_confidence: false },
          location_type: { value: "unknown", raw_phrase: null, source_start: null, source_end: null, low_confidence: false },
          model_id: "qwen2.5:7b",
          extracted_at: "2026-04-25T00:00:00Z",
        }}
        correlations={[]}
      />,
    );
    expect(screen.getByText(/MO classification not available for this case/i)).toBeInTheDocument();
  });

  it("renders 1-MO banner naming the AVAILABLE dimension (weapon)", () => {
    render(
      <RelatedCasesPanel
        fromCaseId={1}
        parentExtraction={{
          weapon: { value: "firearm", raw_phrase: "shot", source_start: 0, source_end: 4, low_confidence: false },
          location_type: { value: "unknown", raw_phrase: null, source_start: null, source_end: null, low_confidence: false },
          model_id: "qwen2.5:7b",
          extracted_at: "2026-04-25T00:00:00Z",
        }}
        correlations={[mkCorrelation()]}
      />,
    );
    expect(
      screen.getByText(
        /Only the weapon dimension is available for this case\. Correlations score on one MO dimension plus demographics/i,
      ),
    ).toBeInTheDocument();
  });

  it("renders 1-MO banner naming the AVAILABLE dimension (location type)", () => {
    render(
      <RelatedCasesPanel
        fromCaseId={1}
        parentExtraction={{
          weapon: { value: null, raw_phrase: null, source_start: null, source_end: null, low_confidence: true },
          location_type: { value: "residence", raw_phrase: "home", source_start: 0, source_end: 4, low_confidence: false },
          model_id: "qwen2.5:7b",
          extracted_at: "2026-04-25T00:00:00Z",
        }}
        correlations={[mkCorrelation()]}
      />,
    );
    expect(
      screen.getByText(/Only the location type dimension is available for this case/i),
    ).toBeInTheDocument();
  });
});

describe("RelatedCasesPanel — CorrelationBars rendering", () => {
  it("renders victim_primary_name when present", () => {
    render(
      <RelatedCasesPanel
        fromCaseId={1}
        parentExtraction={confidentExtraction}
        correlations={[mkCorrelation({ victim_primary_name: "Jane Doe" })]}
      />,
    );
    expect(screen.getByText("Jane Doe")).toBeInTheDocument();
  });

  it("renders 'Unidentified' italic+muted when victim_primary_name is null", () => {
    render(
      <RelatedCasesPanel
        fromCaseId={1}
        parentExtraction={confidentExtraction}
        correlations={[mkCorrelation({ victim_primary_name: null })]}
      />,
    );
    const el = screen.getByText("Unidentified");
    expect(el.className).toMatch(/italic/);
    expect(el.className).toMatch(/muted/);
  });

  it("renders the single score (no denominator)", () => {
    render(
      <RelatedCasesPanel fromCaseId={1} parentExtraction={confidentExtraction} correlations={[mkCorrelation()]} />,
    );
    expect(screen.getByText("2.5")).toBeInTheDocument();
  });

  it("draws a segment per matched dimension", () => {
    const { container } = render(
      <RelatedCasesPanel fromCaseId={1} parentExtraction={confidentExtraction} correlations={[mkCorrelation()]} />,
    );
    expect(container.querySelectorAll("[data-seg]").length).toBe(3);
  });

  it("renders a dimension legend", () => {
    render(
      <RelatedCasesPanel fromCaseId={1} parentExtraction={confidentExtraction} correlations={[mkCorrelation()]} />,
    );
    expect(screen.getByText(/weapon/i)).toBeInTheDocument();
    expect(screen.getByText(/gender/i)).toBeInTheDocument();
  });

  it("wraps the entire row in a single Link to /cold-cases/{id}/{slug}", () => {
    render(
      <RelatedCasesPanel
        fromCaseId={1}
        parentExtraction={confidentExtraction}
        correlations={[mkCorrelation({ case_id: 99, slug: "x-y-z" })]}
      />,
    );
    const links = screen.getAllByRole("link");
    const caseLink = links.find((l) => l.getAttribute("href") === "/cold-cases/99/x-y-z");
    expect(caseLink).toBeDefined();
    if (caseLink) {
      expect(caseLink.querySelectorAll("a").length).toBe(0);
    }
  });
});

describe("RelatedCasesPanel telemetry", () => {
  beforeEach(() => {
    trackMock.mockClear();
  });

  it("emits related_case_clicked with from_case_id, to_case_id, rank=1 for first row", () => {
    render(
      <RelatedCasesPanel
        fromCaseId={100}
        parentExtraction={confidentExtraction}
        correlations={[mkCorrelation({ case_id: 200 }), mkCorrelation({ case_id: 201 })]}
      />,
    );
    const row = screen
      .getAllByRole("link")
      .find((l) => l.getAttribute("href")?.startsWith("/cold-cases/200/"))!;
    fireEvent.click(row);
    expect(trackMock).toHaveBeenCalledWith("related_case_clicked", {
      from_case_id: 100,
      to_case_id: 200,
      rank: 1,
    });
    expect(trackMock).toHaveBeenCalledTimes(1);
  });

  it("emits rank=N for the Nth row (1-indexed)", () => {
    render(
      <RelatedCasesPanel
        fromCaseId={100}
        parentExtraction={confidentExtraction}
        correlations={[
          mkCorrelation({ case_id: 200 }),
          mkCorrelation({ case_id: 201 }),
          mkCorrelation({ case_id: 202 }),
        ]}
      />,
    );
    const row = screen
      .getAllByRole("link")
      .find((l) => l.getAttribute("href")?.startsWith("/cold-cases/202/"))!;
    fireEvent.click(row);
    expect(trackMock).toHaveBeenCalledWith("related_case_clicked", {
      from_case_id: 100,
      to_case_id: 202,
      rank: 3,
    });
    expect(trackMock).toHaveBeenCalledTimes(1);
  });
});
