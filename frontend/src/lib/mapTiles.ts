// CARTO Basemaps keys are intended for browser tile requests. Next.js embeds
// this NEXT_PUBLIC_ value at build time; changing it requires a rebuild.
export function cartoTileUrl(theme: "light" | "dark"): string {
  const style = theme === "dark" ? "dark_all" : "light_all";
  const url = `https://{s}.basemaps.cartocdn.com/${style}/{z}/{x}/{y}{r}.png`;
  const key = process.env.NEXT_PUBLIC_CARTO_BASEMAP_API_KEY?.trim();
  return key ? `${url}?key=${encodeURIComponent(key)}` : url;
}

export const TILE_ATTRIBUTION =
  '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap contributors</a> ' +
  '&copy; <a href="https://carto.com/attributions">CARTO</a>';
