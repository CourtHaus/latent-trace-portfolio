"use client";

import dynamic from "next/dynamic";

// ssr:false — Leaflet touches window/document at import, so it can't render on
// the server. Allowed here because this wrapper is itself a Client Component.
const Inner = dynamic(() => import("./CaseLocationMapInner"), {
  ssr: false,
  loading: () => <div className="h-full w-full animate-pulse bg-inset" aria-hidden="true" />,
});

export interface CaseLocationMapProps {
  lat: number;
  lng: number;
  precision: string | null;
}

export function CaseLocationMap({ lat, lng, precision }: CaseLocationMapProps) {
  return (
    <div className="h-[168px] w-full border-b border-hair" role="img" aria-label="Map showing the recovery location">
      <Inner lat={lat} lng={lng} precision={precision} />
    </div>
  );
}
