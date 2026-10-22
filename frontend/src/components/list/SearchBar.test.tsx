import { render, screen, fireEvent, act } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { SearchBar } from "./SearchBar";

describe("SearchBar", () => {
  it("debounces input before calling onChange", () => {
    const onChange = vi.fn();
    vi.useFakeTimers();
    render(<SearchBar value={null} onChange={onChange} isPending={false} />);
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "jord" } });
    expect(onChange).not.toHaveBeenCalled();
    act(() => {
      vi.advanceTimersByTime(300);
    });
    expect(onChange).toHaveBeenCalledWith("jord");
    vi.useRealTimers();
  });

  it("does not call onChange for 1-char input", () => {
    const onChange = vi.fn();
    vi.useFakeTimers();
    render(<SearchBar value={null} onChange={onChange} isPending={false} />);
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "a" } });
    act(() => {
      vi.advanceTimersByTime(300);
    });
    expect(onChange).not.toHaveBeenCalled();
    vi.useRealTimers();
  });

  it("clears the URL state when input is emptied below threshold", () => {
    const onChange = vi.fn();
    vi.useFakeTimers();
    render(<SearchBar value="jord" onChange={onChange} isPending={false} />);
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "" } });
    act(() => {
      vi.advanceTimersByTime(300);
    });
    expect(onChange).toHaveBeenCalledWith(null);
    vi.useRealTimers();
  });
});
