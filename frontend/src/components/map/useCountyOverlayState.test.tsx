import { describe, it, expect } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useCountyOverlayState } from "./useCountyOverlayState";

describe("useCountyOverlayState", () => {
  it("returns null initially", () => {
    const { result } = renderHook(() => useCountyOverlayState());
    expect(result.current.activeFips).toBeNull();
  });

  it("sets fips when a county-precision pin is clicked", () => {
    const { result } = renderHook(() => useCountyOverlayState());
    act(() => {
      result.current.onPinClick({
        geocode_precision: "county",
        source_county_fips: "08031",
      });
    });
    expect(result.current.activeFips).toBe("08031");
  });

  it("clears fips when a non-county pin is clicked", () => {
    const { result } = renderHook(() => useCountyOverlayState());
    act(() => {
      result.current.onPinClick({
        geocode_precision: "county",
        source_county_fips: "08031",
      });
    });
    act(() => {
      result.current.onPinClick({
        geocode_precision: "street",
        source_county_fips: "08031",
      });
    });
    expect(result.current.activeFips).toBeNull();
  });

  it("clears fips when onMapClick fires", () => {
    const { result } = renderHook(() => useCountyOverlayState());
    act(() => {
      result.current.onPinClick({
        geocode_precision: "county",
        source_county_fips: "08031",
      });
    });
    act(() => {
      result.current.onMapClick();
    });
    expect(result.current.activeFips).toBeNull();
  });

  it("clears fips when source_county_fips is missing", () => {
    const { result } = renderHook(() => useCountyOverlayState());
    act(() => {
      result.current.onPinClick({
        geocode_precision: "county",
        source_county_fips: null,
      });
    });
    expect(result.current.activeFips).toBeNull();
  });
});
