# Latent Trace frontend

The web application uses Next.js App Router, React, TypeScript, Tailwind CSS,
and Leaflet. The production origin is [latenttrace.org](https://latenttrace.org).
See the [development guide](../docs/development.md) for backend setup and the
[rights notice](../LICENSE) before adapting the code.

## Start locally

Use Node.js 22+ and pnpm 10.33.2. Start the backend on port 8000, then run these
commands from `frontend/`:

```bash
pnpm install --frozen-lockfile
test -e .env.local || cp .env.local.example .env.local
pnpm dev
```

The application runs on [localhost:3000](http://localhost:3000). The committed
API types allow a first run without generating code. Keep `API_BASE_URL`
server-side; any `NEXT_PUBLIC_` value is included in browser bundles.

## Configuration

[.env.local.example](.env.local.example) documents each setting. Local public
reads require only the API origin. CARTO map tiles require a publishable
Basemaps key to remove their watermark. Operator login additionally requires
Supabase URL and anon/publishable key values. A service-role key must never
appear in a `NEXT_PUBLIC_` setting.

PostHog and Sentry are opt-in through their environment variables. Vercel Speed
Insights is included in the root layout. Review [data handling](../docs/data-and-privacy.md)
when changing telemetry or external requests. Public environment changes need
a new build; changing an environment variable alone does not update an
already-deployed browser bundle.

## Commands

| Command | Purpose |
| --- | --- |
| `pnpm dev` | Start the development server |
| `pnpm build` | Build for production; requires a reachable API |
| `pnpm start` | Serve the production build |
| `pnpm lint` | Run ESLint |
| `pnpm typecheck` | Run TypeScript without emitting files |
| `pnpm test` / `pnpm test:watch` | Run Vitest once / in watch mode |
| `pnpm test:smoke` | Run the production-build smoke wrapper |
| `pnpm types:api` | Generate API types from localhost:8000/openapi.json |
| `pnpm types:check` | Generate types and fail if the tracked file changes |

## UI conventions

Use tokens from [globals.css](src/app/globals.css), shared case/date formatting,
and existing filter components. Keep map attribution visible and distinguish
approximate geocoding from street-level locations. Use the supplied
[brand assets](../branding/DESIGN.md). The older [design records](../docs/engineering-decisions.md)
explain decisions but do not override the current implementation.
