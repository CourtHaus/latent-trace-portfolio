import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useSourceReveal } from "./SourceRevealController";

describe("useSourceReveal", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("starts with no transient highlight and no persistent underlines", () => {
    const { result } = renderHook(() => useSourceReveal());
    expect(result.current.transient).toBeNull();
    expect(result.current.persistent).toEqual([]);
  });

  it("revealConfident sets the transient and adds to persistent", () => {
    const { result } = renderHook(() => useSourceReveal());
    act(() => result.current.revealConfident({ start: 5, end: 10 }));
    expect(result.current.transient).toEqual({ start: 5, end: 10 });
    expect(result.current.persistent).toEqual([{ start: 5, end: 10 }]);
  });

  it("revealConfident replaces the transient but accumulates persistent", () => {
    const { result } = renderHook(() => useSourceReveal());
    act(() => result.current.revealConfident({ start: 5, end: 10 }));
    act(() => result.current.revealConfident({ start: 20, end: 25 }));
    expect(result.current.transient).toEqual({ start: 20, end: 25 });
    expect(result.current.persistent).toEqual([
      { start: 5, end: 10 },
      { start: 20, end: 25 },
    ]);
  });

  it("transient clears after the duration; persistent remains", () => {
    const { result } = renderHook(() => useSourceReveal());
    act(() => result.current.revealConfident({ start: 5, end: 10 }));
    act(() => {
      vi.advanceTimersByTime(3500);
    });
    expect(result.current.transient).toBeNull();
    expect(result.current.persistent).toEqual([{ start: 5, end: 10 }]);
  });

  it("clearAll clears both transient and persistent", () => {
    const { result } = renderHook(() => useSourceReveal());
    act(() => result.current.revealConfident({ start: 5, end: 10 }));
    act(() => result.current.clearAll());
    expect(result.current.transient).toBeNull();
    expect(result.current.persistent).toEqual([]);
  });
});
