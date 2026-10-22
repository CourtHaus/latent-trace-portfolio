import { cache } from "react";
import { apiFetch } from "@/lib/api";
import type { components } from "@/lib/api-types";

export type CorrelationConfigResponse =
  components["schemas"]["CorrelationConfigResponse"];

/**
 * React.cache-wrapped fetch of /methodology/correlation-weights. Returns the
 * correlation engine's tunable constants and live worked-example weights so the
 * methodology page's scoring section renders values from the backend.
 */
export const getCorrelationWeights = cache(
  async (): Promise<CorrelationConfigResponse> => {
    return apiFetch<CorrelationConfigResponse>(
      "/api/v1/methodology/correlation-weights",
    );
  },
);
