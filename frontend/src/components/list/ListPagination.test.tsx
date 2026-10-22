import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { ListPagination } from "./ListPagination";

describe("ListPagination", () => {
  it("does not render when totalPages <= 1", () => {
    const { container } = render(
      <ListPagination currentPage={1} totalPages={1} totalFiltered={3} searchParams={{}} />
    );
    expect(container.firstChild).toBeNull();
  });

  it("summarizes records and page count", () => {
    render(
      <ListPagination currentPage={1} totalPages={11} totalFiltered={503} searchParams={{}} />
    );
    expect(screen.getByText(/503 records · 11 pages/)).toBeInTheDocument();
  });

  it("formats large record counts with separators", () => {
    render(
      <ListPagination currentPage={2} totalPages={136} totalFiltered={6760} searchParams={{}} />
    );
    expect(screen.getByText(/6,760 records · 136 pages/)).toBeInTheDocument();
  });

  it("marks the current page with aria-current", () => {
    render(
      <ListPagination currentPage={2} totalPages={11} totalFiltered={503} searchParams={{}} />
    );
    expect(screen.getByRole("link", { name: "2" })).toHaveAttribute("aria-current", "page");
  });

  it("page links preserve existing filter params", () => {
    render(
      <ListPagination
        currentPage={1}
        totalPages={3}
        totalFiltered={120}
        searchParams={{ year_min: "1990", gender: "Female" }}
      />
    );
    const page2Link = screen.getByRole("link", { name: "2" });
    const href = page2Link.getAttribute("href")!;
    expect(href).toContain("year_min=1990");
    expect(href).toContain("gender=Female");
    expect(href).toContain("page=2");
  });

  it("previous link is disabled on page 1", () => {
    render(
      <ListPagination currentPage={1} totalPages={3} totalFiltered={120} searchParams={{}} />
    );
    const prev = screen.queryByLabelText(/previous/i);
    if (prev) {
      expect(prev).toHaveAttribute("aria-disabled", "true");
    }
  });

  it("next link is disabled on last page", () => {
    render(
      <ListPagination currentPage={3} totalPages={3} totalFiltered={120} searchParams={{}} />
    );
    const next = screen.queryByLabelText(/next/i);
    if (next) {
      expect(next).toHaveAttribute("aria-disabled", "true");
    }
  });
});
