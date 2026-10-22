import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { createDebouncedTracker } from "./createDebouncedTracker";

describe("createDebouncedTracker", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("fires once after the trailing edge of a burst", () => {
    const fn = vi.fn();
    const tracker = createDebouncedTracker(fn, 1000);
    tracker();
    tracker();
    tracker();
    expect(fn).not.toHaveBeenCalled();
    vi.advanceTimersByTime(999);
    expect(fn).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1);
    expect(fn).toHaveBeenCalledTimes(1);
  });

  it("resets the timer on every call within the window", () => {
    const fn = vi.fn();
    const tracker = createDebouncedTracker(fn, 1000);
    tracker();
    vi.advanceTimersByTime(800);
    tracker(); // resets
    vi.advanceTimersByTime(800);
    expect(fn).not.toHaveBeenCalled(); // would have fired at 1000 without reset
    vi.advanceTimersByTime(200);
    expect(fn).toHaveBeenCalledTimes(1);
  });

  it("fires again for a separate burst after the window elapses", () => {
    const fn = vi.fn();
    const tracker = createDebouncedTracker(fn, 1000);
    tracker();
    vi.advanceTimersByTime(1000);
    expect(fn).toHaveBeenCalledTimes(1);
    tracker();
    vi.advanceTimersByTime(1000);
    expect(fn).toHaveBeenCalledTimes(2);
  });

  it("cancel() clears a pending fire", () => {
    const fn = vi.fn();
    const tracker = createDebouncedTracker(fn, 1000);
    tracker();
    tracker.cancel();
    vi.advanceTimersByTime(2000);
    expect(fn).not.toHaveBeenCalled();
  });

  it("cancel() after firing is a no-op", () => {
    const fn = vi.fn();
    const tracker = createDebouncedTracker(fn, 1000);
    tracker();
    vi.advanceTimersByTime(1000);
    expect(fn).toHaveBeenCalledTimes(1);
    expect(() => tracker.cancel()).not.toThrow();
    vi.advanceTimersByTime(2000);
    expect(fn).toHaveBeenCalledTimes(1); // no phantom re-fire
  });

  it("cancel() mid-burst suppresses the trailing fire", () => {
    const fn = vi.fn();
    const tracker = createDebouncedTracker(fn, 1000);
    tracker(); tracker(); tracker();
    vi.advanceTimersByTime(500);
    tracker.cancel();
    vi.advanceTimersByTime(1000);
    expect(fn).not.toHaveBeenCalled();
  });
});
