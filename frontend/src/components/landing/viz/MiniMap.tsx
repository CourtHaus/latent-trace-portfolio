// Decorative schematic scatter map — no data, no a11y surface.
// Geometry ported directly from mockup miniMap() in docs/design/2026-06-07-latent-landing-mockup.html

const GRATICULE_PATHS = [
  "M0 49 H460",
  "M0 99 H460",
  "M77 0 V148",
  "M154 0 V148",
  "M230 0 V148",
  "M307 0 V148",
  "M384 0 V148",
] as const;

// [cx, cy]
const GRAY_POINTS: [number, number][] = [
  [60, 70],
  [92, 60],
  [120, 76],
  [150, 55],
  [200, 82],
  [232, 66],
  [262, 92],
  [300, 60],
  [332, 82],
  [360, 70],
  [180, 112],
  [252, 120],
  [140, 118],
  [292, 114],
  [210, 96],
  [400, 86],
  [418, 72],
  [96, 98],
];

// [cx, cy, haloRadius]
const EMBER_CLUSTERS: [number, number, number][] = [
  [112, 58, 7],
  [207, 80, 8],
  [372, 102, 6],
];

export function MiniMap() {
  return (
    <svg
      viewBox="0 0 460 148"
      width="100%"
      height={148}
      aria-hidden="true"
    >
      {/* Graticule hairlines */}
      <g stroke="rgba(255,255,255,.05)" strokeWidth={1}>
        {GRATICULE_PATHS.map((d) => (
          <path key={d} d={d} />
        ))}
      </g>

      {/* Gray point cloud */}
      {GRAY_POINTS.map(([cx, cy]) => (
        <circle
          key={`g-${cx}-${cy}`}
          cx={cx}
          cy={cy}
          r={2.6}
          fill="#576069"
          opacity={0.8}
        />
      ))}

      {/* Ember cluster halos + dots */}
      {EMBER_CLUSTERS.map(([cx, cy, haloR]) => (
        <g key={`e-${cx}-${cy}`}>
          <circle cx={cx} cy={cy} r={haloR} fill="var(--accent)" fillOpacity={0.18} />
          <circle cx={cx} cy={cy} r={3.2} fill="var(--accent)" />
        </g>
      ))}
    </svg>
  );
}
