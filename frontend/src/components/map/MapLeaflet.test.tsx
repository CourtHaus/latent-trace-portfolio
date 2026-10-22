import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { MapLeaflet } from "./MapLeaflet";

const { mapEvents, mapMock, trackMock } = vi.hoisted(() => ({
  mapEvents: {} as Record<string, () => void>,
  mapMock: {
    fitBounds: vi.fn(),
    flyTo: vi.fn(),
    getZoom: vi.fn(() => 12),
    getBounds: vi.fn(() => ({
      getWest: () => -80,
      getSouth: () => 36,
      getEast: () => -76,
      getNorth: () => 39,
    })),
  },
  trackMock: vi.fn(),
}));

vi.mock("@/lib/analytics/client", () => ({
  track: trackMock,
}));

vi.mock("next-themes", () => ({
  useTheme: () => ({ resolvedTheme: "light" }),
}));

vi.mock("./CountyOverlay", () => ({
  CountyOverlay: () => <div data-testid="county-overlay" />,
}));

vi.mock("react-leaflet-cluster", () => ({
  default: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="marker-cluster">{children}</div>
  ),
}));

vi.mock("react-leaflet", () => ({
  MapContainer: ({
    children,
    zoom,
  }: {
    children: React.ReactNode;
    zoom: number;
  }) => (
    <div data-testid="map-container" data-zoom={zoom}>
      {children}
    </div>
  ),
  TileLayer: () => null,
  Marker: ({
    children,
    eventHandlers,
  }: {
    children: React.ReactNode;
    eventHandlers?: { click?: () => void };
  }) => (
    <button type="button" data-testid="marker" onClick={eventHandlers?.click}>
      {children}
    </button>
  ),
  Popup: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  ZoomControl: () => null,
  AttributionControl: () => null,
  useMap: () => mapMock,
  useMapEvent: (eventName: string, handler: () => void) => {
    mapEvents[eventName] = handler;
  },
}));

const sampleCase = {
  case_id: 42,
  slug: "jane-doe-richmond-va-1998",
  source_case_id: "2022-0003209",
  case_name: "Augusta County - Case: 2022-0003209 - Jane Doe",
  case_type: "homicide",
  incident_date: "1998-05-14",
  latitude: 37.54,
  longitude: -77.43,
  state: "VA",
  city: "Richmond",
  victim_primary_name: "Jane Doe",
  victim_genders: ["Female"],
  victim_races: ["White"],
  geocode_precision: null,
};

function renderMap() {
  return render(
    <MapLeaflet
      mode="points"
      data={[sampleCase]}
      clusters={[]}
      initialBbox={null}
      initialZoom={7}
      shouldFitBounds={false}
      onViewportChange={() => {}}
      onRecenterToken={0}
    />,
  );
}

describe("MapLeaflet telemetry", () => {
  beforeEach(() => {
    trackMock.mockClear();
    mapMock.getBounds.mockClear();
    for (const key of Object.keys(mapEvents)) {
      delete mapEvents[key];
    }
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("emits map_interacted viewport_changed with only interaction_type after a debounced moveend", () => {
    renderMap();

    act(() => {
      expect(mapEvents.moveend).toBeDefined();
      mapEvents.moveend?.();
      vi.advanceTimersByTime(1000);
    });

    expect(trackMock).toHaveBeenCalledWith("map_interacted", {
      interaction_type: "viewport_changed",
    });
    expect(trackMock).toHaveBeenCalledTimes(1);
  });

  it("emits map_interacted marker_clicked with interaction_type and case_id only", () => {
    renderMap();

    fireEvent.click(screen.getByTestId("marker"));

    expect(trackMock).toHaveBeenCalledWith("map_interacted", {
      interaction_type: "marker_clicked",
      case_id: 42,
    });
    expect(trackMock).toHaveBeenCalledTimes(1);
  });
});

describe("MapLeaflet viewport initialization", () => {
  it("uses the initial zoom supplied by the server page", () => {
    render(
      <MapLeaflet
        mode="points"
        data={[sampleCase]}
        clusters={[]}
        initialBbox={[-80, 37, -77, 39]}
        initialZoom={12}
        shouldFitBounds={false}
        onViewportChange={() => {}}
        onRecenterToken={0}
      />,
    );

    expect(screen.getByTestId("map-container")).toHaveAttribute("data-zoom", "12");
  });
});

describe("MapLeaflet cluster mode", () => {
  beforeEach(() => {
    trackMock.mockClear();
    mapMock.flyTo.mockClear();
    mapMock.getZoom.mockClear();
    for (const key of Object.keys(mapEvents)) {
      delete mapEvents[key];
    }
  });

  it("renders one bubble per server cluster and zooms in on click", () => {
    render(
      <MapLeaflet
        mode="clusters"
        data={[]}
        clusters={[
          { latitude: 38.0, longitude: -78.0, count: 120 },
          { latitude: 39.5, longitude: -77.0, count: 8 },
        ]}
        initialBbox={null}
        initialZoom={7}
        shouldFitBounds={false}
        onViewportChange={() => {}}
        onRecenterToken={0}
      />,
    );

    const markers = screen.getAllByTestId("marker");
    expect(markers).toHaveLength(2);

    const firstMarker = markers[0];
    if (!firstMarker) throw new Error("expected a cluster marker");
    fireEvent.click(firstMarker);
    expect(mapMock.flyTo).toHaveBeenCalledTimes(1);
  });

  it("does not render the client-side MarkerClusterGroup in cluster mode", () => {
    render(
      <MapLeaflet
        mode="clusters"
        data={[]}
        clusters={[{ latitude: 38.0, longitude: -78.0, count: 5 }]}
        initialBbox={null}
        initialZoom={7}
        shouldFitBounds={false}
        onViewportChange={() => {}}
        onRecenterToken={0}
      />,
    );
    // Server already aggregated — no client re-clustering wrapper.
    expect(screen.queryByTestId("marker-cluster")).not.toBeInTheDocument();
  });
});
