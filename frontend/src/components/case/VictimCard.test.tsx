import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { axe } from "vitest-axe";
import { VictimCard } from "./VictimCard";
import { SourceRevealProvider } from "@/components/case-detail/SourceRevealContext";

const trackMock = vi.hoisted(() => vi.fn());
vi.mock("@/lib/analytics/client", () => ({ track: trackMock }));

const base = {
  caseId: 42,
  victim_id: 7,
  first_name: "Jane",
  last_name: "Doe",
  gender: "Female",
  height_text: "5'6\"",
  weight_num: 130,
  age_text: "24",
  age_num: 24,
  race: "White",
  eye_color: "Blue",
  hair_color: "Brown",
};

describe("VictimCard", () => {
  it("renders with stable anchor ID victim-{caseId}-{victim_id}", () => {
    const { container } = render(<VictimCard {...base} />);
    expect(container.querySelector("#victim-42-7")).toBeInTheDocument();
  });

  it("renders name when present", () => {
    render(<VictimCard {...base} />);
    expect(screen.getByText("Jane Doe")).toBeInTheDocument();
  });

  it("humanizes a raw stored gender value (M -> Male)", () => {
    render(<VictimCard {...base} gender="M" />);
    expect(screen.getByText("Male")).toBeInTheDocument();
    expect(screen.queryByText(/^M$/)).not.toBeInTheDocument();
  });

  it("renders unidentified fallback when first + last name are null", () => {
    render(<VictimCard {...base} first_name={null} last_name={null} />);
    expect(screen.getByText(/unidentified/i)).toBeInTheDocument();
  });

  it("renders demographics that are present; omits null fields", () => {
    render(<VictimCard {...base} eye_color={null} hair_color={null} />);
    expect(screen.getByText(/24/)).toBeInTheDocument();
    expect(screen.queryByText(/eye color/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/hair color/i)).not.toBeInTheDocument();
  });

  it("renders extracted-from-narrative suffix when gender_source is tier2", () => {
    render(<VictimCard {...base} gender="Male" gender_source="tier2" />);
    expect(screen.getByText(/extracted from narrative/i)).toBeInTheDocument();
  });

  it("no suffix when gender_source is source", () => {
    render(<VictimCard {...base} gender="Male" gender_source="source" />);
    expect(screen.queryByText(/extracted from narrative/i)).not.toBeInTheDocument();
  });

  it("renders extracted-from-narrative suffix when age_source is tier2", () => {
    render(<VictimCard {...base} age_source="tier2" />);
    expect(screen.getByText(/extracted from narrative/i)).toBeInTheDocument();
  });

  it("renders extracted-from-narrative suffix when race_source is tier2", () => {
    render(<VictimCard {...base} race_source="tier2" />);
    expect(screen.getByText(/extracted from narrative/i)).toBeInTheDocument();
  });

  it("renders a Source button for tier2 age inside a reveal provider", () => {
    render(
      <SourceRevealProvider hasNarrative>
        <VictimCard
          caseId={1}
          victim_id={1}
          first_name="Jane"
          last_name="Doe"
          gender={null}
          height_text={null}
          weight_num={null}
          age_text="34"
          age_num={34}
          race={null}
          eye_color={null}
          hair_color={null}
          age_source="tier2"
          age_extraction={{
            value: "34",
            raw_phrase: "34-year-old",
            source_start: 4,
            source_end: 15,
            low_confidence: false,
          }}
        />
      </SourceRevealProvider>
    );
    expect(screen.getByRole("button", { name: /source/i })).toBeInTheDocument();
  });

  it("has no a11y violations", async () => {
    const { container } = render(<VictimCard {...base} />);
    expect(await axe(container)).toHaveNoViolations();
  });

  it("has no a11y violations when the Source button is rendered", async () => {
    const { container } = render(
      <>
        {/* aria-controls="case-narrative" requires the target element to exist */}
        <div id="case-narrative" />
        <SourceRevealProvider hasNarrative>
          <VictimCard
            caseId={1}
            victim_id={1}
            first_name="Jane"
            last_name="Doe"
            gender={null}
            height_text={null}
            weight_num={null}
            age_text="34"
            age_num={34}
            race={null}
            eye_color={null}
            hair_color={null}
            age_source="tier2"
            age_extraction={{
              value: "34",
              raw_phrase: "34-year-old",
              source_start: 4,
              source_end: 15,
              low_confidence: false,
            }}
          />
        </SourceRevealProvider>
      </>
    );
    expect(await axe(container)).toHaveNoViolations();
  });
});
