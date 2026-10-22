import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { axe } from "vitest-axe";

vi.mock("next/navigation", () => ({
  usePathname: vi.fn(),
}));

import { SiteNav } from "./SiteNav";
import { usePathname } from "next/navigation";

describe("SiteNav", () => {
  it("renders logo + all nav links", () => {
    vi.mocked(usePathname).mockReturnValue("/cold-cases");
    render(<SiteNav />);
    expect(screen.getByRole("link", { name: /latent/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Cases" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Map" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Methodology" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Briefings" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "About" })).toBeInTheDocument();
  });

  it("does not render the dead sign-in CTA", () => {
    vi.mocked(usePathname).mockReturnValue("/");
    render(<SiteNav />);
    expect(screen.queryByRole("link", { name: /sign in/i })).toBeNull();
  });

  it("renders the fluid text CTA linking to /cold-cases", () => {
    vi.mocked(usePathname).mockReturnValue("/");
    render(<SiteNav />);
    const cta = screen.getByRole("link", { name: /open the index/i });
    expect(cta).toBeInTheDocument();
    expect(cta).toHaveAttribute("href", "/cold-cases");
  });

  it("marks Cases as active when on /cold-cases", () => {
    vi.mocked(usePathname).mockReturnValue("/cold-cases");
    render(<SiteNav />);
    const casesLink = screen.getByRole("link", { name: "Cases" });
    expect(casesLink.getAttribute("aria-current")).toBe("page");
  });

  it("marks Map as active when on /cold-cases/map", () => {
    vi.mocked(usePathname).mockReturnValue("/cold-cases/map");
    render(<SiteNav />);
    const mapLink = screen.getByRole("link", { name: "Map" });
    expect(mapLink.getAttribute("aria-current")).toBe("page");
  });

  it("routes About to /about and marks it active there", () => {
    vi.mocked(usePathname).mockReturnValue("/about");
    render(<SiteNav />);
    // About renders twice (desktop nav + mobile sheet); the desktop link is first
    // and is the one that carries the active-state marker.
    const [desktopAbout] = screen.getAllByRole("link", { name: "About" });
    expect(desktopAbout).toHaveAttribute("href", "/about");
    expect(desktopAbout).toHaveAttribute("aria-current", "page");
  });

  it("routes Briefings to /briefings and marks it active there", () => {
    vi.mocked(usePathname).mockReturnValue("/briefings");
    render(<SiteNav />);
    const [desktopBriefings] = screen.getAllByRole("link", { name: "Briefings" });
    expect(desktopBriefings).toHaveAttribute("href", "/briefings");
    expect(desktopBriefings).toHaveAttribute("aria-current", "page");
  });

  it("does NOT mark Cases as active when on /cold-cases/map", () => {
    vi.mocked(usePathname).mockReturnValue("/cold-cases/map");
    render(<SiteNav />);
    const casesLink = screen.getByRole("link", { name: "Cases" });
    expect(casesLink.getAttribute("aria-current")).toBeNull();
  });

  it("has no a11y violations", async () => {
    vi.mocked(usePathname).mockReturnValue("/");
    const { container } = render(<SiteNav />);
    expect(await axe(container)).toHaveNoViolations();
  });

  it("renders a hamburger trigger on mobile", () => {
    vi.mocked(usePathname).mockReturnValue("/");
    render(<SiteNav />);
    expect(screen.getByRole("button", { name: /open navigation/i })).toBeInTheDocument();
  });
});
