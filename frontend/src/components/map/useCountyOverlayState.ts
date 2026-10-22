import { useState } from "react";

interface PinClickInput {
  geocode_precision?: string | null;
  source_county_fips?: string | null;
}

export function useCountyOverlayState() {
  const [activeFips, setActiveFips] = useState<string | null>(null);

  const onPinClick = (caseRow: PinClickInput) => {
    if (caseRow.geocode_precision === "county" && caseRow.source_county_fips) {
      setActiveFips(caseRow.source_county_fips);
    } else {
      setActiveFips(null);
    }
  };

  const onMapClick = () => setActiveFips(null);

  return { activeFips, onPinClick, onMapClick };
}
