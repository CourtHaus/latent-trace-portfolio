import { renderHook, act } from "@testing-library/react";
import { describe, it, expect, beforeEach, vi } from "vitest";
import { useCollapsibleSections } from "./useCollapsibleSections";

describe("useCollapsibleSections", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("starts with all sections expanded by default", () => {
    const { result } = renderHook(() =>
      useCollapsibleSections("test-key", ["a", "b", "c"])
    );
    expect(result.current.collapsed).toEqual([]);
    expect(result.current.isCollapsed("a")).toBe(false);
  });

  it("starts with defaultCollapsed sections collapsed when there is no stored preference", () => {
    const { result } = renderHook(() =>
      useCollapsibleSections("test-key", ["a", "b", "c"], ["a"])
    );
    expect(result.current.isCollapsed("a")).toBe(true);
    expect(result.current.isCollapsed("b")).toBe(false);
  });

  it("lets a stored preference override defaultCollapsed", () => {
    localStorage.setItem("test-key", JSON.stringify(["b"]));
    const { result } = renderHook(() =>
      useCollapsibleSections("test-key", ["a", "b", "c"], ["a"])
    );
    // 'a' is the default-collapsed section, but the user's stored state wins.
    expect(result.current.isCollapsed("a")).toBe(false);
    expect(result.current.isCollapsed("b")).toBe(true);
  });

  it("keeps a toggle in memory when localStorage writes fail (private mode / quota)", () => {
    const setItem = vi
      .spyOn(Storage.prototype, "setItem")
      .mockImplementation(() => {
        throw new DOMException("QuotaExceededError");
      });
    try {
      // Unique key so the in-memory fallback this test populates can't leak
      // into the localStorage-backed tests above/below.
      const { result } = renderHook(() =>
        useCollapsibleSections("fail-write-key", ["a", "b"], ["a"])
      );
      // 'a' is default-collapsed; expanding it must stick despite the failed write
      // (otherwise the section would snap back and be impossible to open).
      expect(result.current.isCollapsed("a")).toBe(true);
      act(() => result.current.toggle("a"));
      expect(result.current.isCollapsed("a")).toBe(false);
      // Collapsing again still works off the in-memory state.
      act(() => result.current.toggle("a"));
      expect(result.current.isCollapsed("a")).toBe(true);
    } finally {
      setItem.mockRestore();
    }
  });

  it("toggles a section's collapsed state", () => {
    const { result } = renderHook(() =>
      useCollapsibleSections("test-key", ["a", "b"])
    );
    act(() => result.current.toggle("a"));
    expect(result.current.isCollapsed("a")).toBe(true);
    expect(result.current.isCollapsed("b")).toBe(false);
    act(() => result.current.toggle("a"));
    expect(result.current.isCollapsed("a")).toBe(false);
  });

  it("persists collapsed state to localStorage", () => {
    const { result } = renderHook(() =>
      useCollapsibleSections("test-key", ["a", "b"])
    );
    act(() => result.current.toggle("a"));
    expect(localStorage.getItem("test-key")).toContain("a");
  });

  it("rehydrates collapsed state from localStorage on mount", () => {
    localStorage.setItem("test-key", JSON.stringify(["b"]));
    const { result } = renderHook(() =>
      useCollapsibleSections("test-key", ["a", "b"])
    );
    expect(result.current.isCollapsed("b")).toBe(true);
    expect(result.current.isCollapsed("a")).toBe(false);
  });

  it("ignores stale localStorage entries for unknown sections", () => {
    localStorage.setItem("test-key", JSON.stringify(["b", "ghost"]));
    const { result } = renderHook(() =>
      useCollapsibleSections("test-key", ["a", "b"])
    );
    expect(result.current.collapsed).toEqual(["b"]);
  });
});
