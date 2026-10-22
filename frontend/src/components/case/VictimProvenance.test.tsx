import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { VictimProvenance } from "./VictimProvenance";
import { SourceRevealProvider } from "@/components/case-detail/SourceRevealContext";

const trackMock = vi.hoisted(() => vi.fn());
vi.mock("@/lib/analytics/client", () => ({ track: trackMock }));

const anchoredField = {
  value: "34",
  raw_phrase: "34-year-old",
  source_start: 4,
  source_end: 15,
  low_confidence: false,
};

describe("VictimProvenance", () => {
  it("renders nothing for source-provided values", () => {
    const { container } = render(
      <VictimProvenance source="source" field={null} fieldName="victim_age" />
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing when source is null", () => {
    const { container } = render(
      <VictimProvenance source={null} field={anchoredField} fieldName="victim_age" />
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("renders a static suffix without a provider", () => {
    render(
      <VictimProvenance source="tier2" field={anchoredField} fieldName="victim_age" />
    );
    expect(screen.getByText(/extracted from narrative/)).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("renders a static suffix when low_confidence is true", () => {
    render(
      <SourceRevealProvider hasNarrative>
        <VictimProvenance
          source="tier2"
          field={{ ...anchoredField, low_confidence: true }}
          fieldName="victim_age"
        />
      </SourceRevealProvider>
    );
    expect(screen.getByText(/extracted from narrative/)).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("renders a static suffix when low_confidence is false but offsets are null", () => {
    render(
      <SourceRevealProvider hasNarrative>
        <VictimProvenance
          source="tier2"
          field={{ ...anchoredField, source_start: null, source_end: null, low_confidence: false }}
          fieldName="victim_age"
        />
      </SourceRevealProvider>
    );
    expect(screen.getByText(/extracted from narrative/)).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("renders a Source button inside a provider and fires analytics on click", () => {
    render(
      <SourceRevealProvider hasNarrative>
        <VictimProvenance source="tier2" field={anchoredField} fieldName="victim_age" />
      </SourceRevealProvider>
    );
    const btn = screen.getByRole("button", { name: /source/i });
    expect(btn).toHaveAttribute("aria-controls", "case-narrative");
    fireEvent.click(btn);
    expect(trackMock).toHaveBeenCalledWith("source_revealed", { field: "victim_age" });
  });

  it("renders Source button without aria-controls when hasNarrative is false", () => {
    render(
      <SourceRevealProvider hasNarrative={false}>
        <VictimProvenance source="tier2" field={anchoredField} fieldName="victim_age" />
      </SourceRevealProvider>
    );
    const btn = screen.getByRole("button", { name: /source/i });
    expect(btn).not.toHaveAttribute("aria-controls");
  });
});
