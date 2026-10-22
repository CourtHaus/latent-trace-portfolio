import http from "k6/http";
import { check, sleep } from "k6";

// Spike profile against the API. Set BASE_URL to the API host.
//   k6 run -e BASE_URL=https://<api-host> tools/loadtest/spike.js
// Caching means most repeat requests should be cheap; this proves the origin
// survives the cache-miss + revalidation load under a sudden burst.
export const options = {
  scenarios: {
    spike: {
      executor: "ramping-vus",
      startVUs: 0,
      stages: [
        { duration: "30s", target: 200 }, // ramp to spike
        { duration: "1m", target: 200 },  // hold
        { duration: "30s", target: 0 },   // ramp down
      ],
      gracefulRampDown: "10s",
    },
  },
  thresholds: {
    http_req_failed: ["rate<0.01"], // <1% errors
    "http_req_duration{kind:cached}": ["p(95)<800"],
    "http_req_duration{kind:uncached}": ["p(95)<3000"],
  },
};

const BASE = __ENV.BASE_URL;
if (!BASE) {
  throw new Error("Set BASE_URL, e.g. -e BASE_URL=https://api.example.run.app");
}

// Realistic mix: default views (cacheable) dominate; a filtered view exercises
// a cache-miss path; detail pages are already ISR at the frontend.
const cached = [
  "/api/v1/cold-cases?limit=50&offset=0&sort=incident_date_desc",
  "/api/v1/cold-cases/map?zoom=4",
  "/api/v1/cold-cases/filter-options",
  "/api/v1/cold-cases/facet-counts",
  "/api/v1/cold-cases/year-histogram",
];
const uncached = [
  "/api/v1/cold-cases?limit=50&offset=0&sort=incident_date_desc&state=OH",
  "/api/v1/cold-cases/map?zoom=8&bbox=-84,38,-80,42",
];

export default function () {
  // 80% cached default views, 20% filtered (cache-miss-ish).
  const roll = Math.random();
  if (roll < 0.8) {
    const url = cached[Math.floor(Math.random() * cached.length)];
    const res = http.get(`${BASE}${url}`, { tags: { kind: "cached" } });
    check(res, { "cached 200": (r) => r.status === 200 });
  } else {
    const url = uncached[Math.floor(Math.random() * uncached.length)];
    const res = http.get(`${BASE}${url}`, { tags: { kind: "uncached" } });
    check(res, { "uncached 200": (r) => r.status === 200 });
  }
  sleep(1);
}
