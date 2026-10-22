import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { MOSection } from "./MOSection";

const trackMock = vi.hoisted(() => vi.fn());
vi.mock("@/lib/analytics/client", () => ({ track: trackMock }));

interface OverrideField {
  value: string | null;
  raw_phrase: string | null;
  source_start: number | null;
  source_end: number | null;
  low_confidence: boolean;
}

interface Overrides {
  weapon?: OverrideField;
  location_type?: OverrideField;
}

function makeExtraction(overrides: Overrides = {}) {
  return {
    weapon: {
      value: "firearm",
      raw_phrase: "shot",
      source_start: 10,
      source_end: 14,
      low_confidence: false,
      ...overrides.weapon,
    },
    location_type: {
      value: "residence",
      raw_phrase: "home",
      source_start: 30,
      source_end: 34,
      low_confidence: false,
      ...overrides.location_type,
    },
    model_id: "qwen2.5:7b",
    extracted_at: "2026-04-25T00:00:00Z",
  };
}

describe("MOSection", () => {
  it("renders both confident fields with Source buttons", () => {
    render(
      <MOSection extraction={makeExtraction()} onRevealConfident={() => {}} />
    );
    expect(screen.getByText("firearm")).toBeInTheDocument();
    expect(screen.getByText("residence")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /source/i })).toHaveLength(2);
  });

  it("only emits the confident Source aria-controls when a narrative is present", () => {
    const { rerender } = render(
      <MOSection extraction={makeExtraction()} onRevealConfident={() => {}} />
    );
    // No narrative (default) → no dangling reference to #case-narrative.
    for (const btn of screen.getAllByRole("button", { name: /source/i })) {
      expect(btn).not.toHaveAttribute("aria-controls");
    }
    rerender(
      <MOSection extraction={makeExtraction()} onRevealConfident={() => {}} hasNarrative />
    );
    for (const btn of screen.getAllByRole("button", { name: /source/i })) {
      expect(btn).toHaveAttribute("aria-controls", "case-narrative");
    }
  });

  it("renders 'not mentioned in case file' for ('unknown', false)", () => {
    render(
      <MOSection
        extraction={makeExtraction({
          weapon: {
            value: "unknown",
            raw_phrase: null,
            source_start: null,
            source_end: null,
            low_confidence: false,
          },
        })}
        onRevealConfident={() => {}}
      />
    );
    expect(screen.getByText(/not mentioned in case file/i)).toBeInTheDocument();
  });

  it("renders 'extraction unavailable' for (None, true)", () => {
    render(
      <MOSection
        extraction={makeExtraction({
          weapon: {
            value: null,
            raw_phrase: null,
            source_start: null,
            source_end: null,
            low_confidence: true,
          },
          location_type: {
            value: null,
            raw_phrase: null,
            source_start: null,
            source_end: null,
            low_confidence: true,
          },
        })}
        onRevealConfident={() => {}}
      />
    );
    expect(screen.getAllByText(/extraction unavailable/i)).toHaveLength(2);
  });

  it("collapses to one-line summary when BOTH fields are unknown", () => {
    render(
      <MOSection
        extraction={makeExtraction({
          weapon: {
            value: "unknown",
            raw_phrase: null,
            source_start: null,
            source_end: null,
            low_confidence: false,
          },
          location_type: {
            value: "unknown",
            raw_phrase: null,
            source_start: null,
            source_end: null,
            low_confidence: false,
          },
        })}
        onRevealConfident={() => {}}
      />
    );
    expect(
      screen.getByText(/no modus operandi could be extracted/i)
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /about these fields/i })
    ).toBeInTheDocument();
  });

  it("clicks Source on confident → calls onRevealConfident with span", () => {
    const onReveal = vi.fn();
    render(
      <MOSection extraction={makeExtraction()} onRevealConfident={onReveal} />
    );
    fireEvent.click(screen.getAllByRole("button", { name: /source/i })[0]!);
    expect(onReveal).toHaveBeenCalledWith({ start: 10, end: 14 });
  });

  it("clicks Source on low_conf with raw_phrase → opens popover with phrase", () => {
    render(
      <MOSection
        extraction={makeExtraction({
          weapon: {
            value: "firearm",
            raw_phrase: "in the kitchen",
            source_start: null,
            source_end: null,
            low_confidence: true,
          },
        })}
        onRevealConfident={() => {}}
      />
    );
    fireEvent.click(screen.getAllByRole("button", { name: /source/i })[0]!);
    expect(screen.getByText(/in the kitchen/i)).toBeInTheDocument();
    expect(screen.getByText(/couldn't anchor verbatim/i)).toBeInTheDocument();
  });

  it("clicks Source on low_conf without raw_phrase → fallback popover content", () => {
    render(
      <MOSection
        extraction={makeExtraction({
          weapon: {
            value: "firearm",
            raw_phrase: null,
            source_start: null,
            source_end: null,
            low_confidence: true,
          },
        })}
        onRevealConfident={() => {}}
      />
    );
    fireEvent.click(screen.getAllByRole("button", { name: /source/i })[0]!);
    expect(
      screen.getByText(/no specific phrase identified/i)
    ).toBeInTheDocument();
  });

  it("renders provenance footer (model_id)", () => {
    render(
      <MOSection extraction={makeExtraction()} onRevealConfident={() => {}} />
    );
    expect(screen.getByText(/qwen2\.5:7b/i)).toBeInTheDocument();
  });

  describe("source_revealed telemetry", () => {
    beforeEach(() => {
      trackMock.mockClear();
    });

    it("clicking Source on weapon fires track('source_revealed', { field: 'weapon' })", () => {
      render(
        <MOSection extraction={makeExtraction()} onRevealConfident={() => {}} />
      );
      // First Source button is Weapon
      fireEvent.click(screen.getAllByRole("button", { name: /source/i })[0]!);
      expect(trackMock).toHaveBeenCalledWith("source_revealed", { field: "weapon" });
    });

    it("clicking Source on location_type fires track('source_revealed', { field: 'location_type' })", () => {
      render(
        <MOSection extraction={makeExtraction()} onRevealConfident={() => {}} />
      );
      // Second Source button is Location
      fireEvent.click(screen.getAllByRole("button", { name: /source/i })[1]!);
      expect(trackMock).toHaveBeenCalledWith("source_revealed", { field: "location_type" });
    });

    it("track properties contain ONLY field — no extraction value, no offsets", () => {
      render(
        <MOSection extraction={makeExtraction()} onRevealConfident={() => {}} />
      );
      fireEvent.click(screen.getAllByRole("button", { name: /source/i })[0]!);
      const [, props] = trackMock.mock.calls[0] as [string, Record<string, unknown>];
      expect(Object.keys(props)).toEqual(["field"]);
    });

    it("clicking Source on low_conf weapon fires track('source_revealed', { field: 'weapon' })", () => {
      render(
        <MOSection
          extraction={makeExtraction({
            weapon: { value: "firearm", raw_phrase: null, source_start: null, source_end: null, low_confidence: true },
          })}
          onRevealConfident={() => {}}
        />
      );
      fireEvent.click(screen.getAllByRole("button", { name: /source/i })[0]!);
      expect(trackMock).toHaveBeenCalledWith("source_revealed", { field: "weapon" });
      expect(trackMock).toHaveBeenCalledTimes(1);
    });
  });
});
