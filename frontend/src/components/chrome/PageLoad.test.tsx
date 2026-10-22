import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { PageLoad } from "./PageLoad";

describe("PageLoad", () => {
  it("applies page-load-child + incremental animation-delay to each direct child", () => {
    const { container } = render(
      <PageLoad>
        <section data-testid="a">A</section>
        <section data-testid="b">B</section>
        <section data-testid="c">C</section>
      </PageLoad>,
    );
    const children = container.querySelectorAll("section");
    expect(children.length).toBe(3);
    for (let i = 0; i < 3; i++) {
      const el = children[i] as HTMLElement;
      expect(el.className).toMatch(/page-load-child/);
      expect(el.style.animationDelay).toBe(`${i * 80}ms`);
    }
  });

  it("passes through a single child with page-load-child class", () => {
    const { getByTestId } = render(
      <PageLoad>
        <div data-testid="only">hi</div>
      </PageLoad>,
    );
    expect(getByTestId("only").className).toMatch(/page-load-child/);
  });
});
