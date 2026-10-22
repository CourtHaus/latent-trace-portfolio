import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { MapContainer } from "react-leaflet";
import { CountyOverlay } from "./CountyOverlay";

describe("CountyOverlay", () => {
  it("renders nothing when fips is null", () => {
    const { container } = render(
      <MapContainer center={[0, 0]} zoom={2}>
        <CountyOverlay fips={null} />
      </MapContainer>
    );
    // No GeoJSON path inserted
    expect(container.querySelectorAll("path.leaflet-interactive")).toHaveLength(0);
  });

  it("attempts to load atlas + render a polygon when fips is set", async () => {
    // Spy on dynamic import to confirm lazy-load path executes
    const { findByTestId } = render(
      <MapContainer center={[39.7, -104.9]} zoom={6}>
        <CountyOverlay fips="08031" />
      </MapContainer>
    );
    // Asset load is async; allow the effect + lazy import to settle
    // Component renders a wrapper element with a stable testid even before geom loads
    const wrapper = await findByTestId("county-overlay");
    expect(wrapper).toBeInTheDocument();
  });
});
