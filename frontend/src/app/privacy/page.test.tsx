import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import PrivacyPage, { metadata } from "./page";

describe("PrivacyPage", () => {
  it("renders the privacy heading", () => {
    render(<PrivacyPage />);
    expect(screen.getByRole("heading", { name: /privacy/i, level: 1 })).toBeInTheDocument();
  });

  it("lists the events we collect", () => {
    render(<PrivacyPage />);
    for (const eventName of [
      "page_viewed",
      "map_interacted",
      "filter_applied",
      "filter_cleared",
      "related_case_clicked",
      "source_revealed",
      "analytics_opted_out",
    ]) {
      expect(screen.getByText(new RegExp(eventName, "i"))).toBeInTheDocument();
    }
  });

  it("discloses the localStorage anonymous identifier so the privacy claim matches SDK behavior", () => {
    // The init config sets persistence: 'localStorage', which means PostHog
    // stores a distinct_id in localStorage. The privacy page must disclose
    // this — otherwise the implementation makes a stronger collection claim
    // than the policy admits to.
    render(<PrivacyPage />);
    // Multiple disclosures of localStorage in different sections of the page
    // (collection, what-we-don't-do, opt-out). getByText would throw on multi-
    // match; getAllByText returns the list and we assert non-empty.
    expect(screen.getAllByText(/localStorage/i).length).toBeGreaterThan(0);
  });

  it("describes the hosting model accurately as PostHog Cloud, not self-hosted", () => {
    render(<PrivacyPage />);
    expect(screen.getByText(/PostHog Cloud/)).toBeInTheDocument();
    expect(screen.queryByText(/self-hosted/i)).not.toBeInTheDocument();
  });

  it("has the opt-out control", () => {
    render(<PrivacyPage />);
    expect(screen.getByRole("button", { name: /opt out/i })).toBeInTheDocument();
  });
});

describe("metadata", () => {
  it("has a privacy title", () => {
    expect(metadata.title).toMatch(/privacy/i);
  });

  it("sets a canonical URL", () => {
    expect(metadata.alternates?.canonical).toBe("/privacy");
  });
});
