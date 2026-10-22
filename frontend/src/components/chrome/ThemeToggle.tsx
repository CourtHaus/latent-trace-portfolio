"use client";

import { Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";
import { useSyncExternalStore } from "react";

// Subscribe is a no-op. useSyncExternalStore handles the SSR / hydration
// divergence cleanly: during hydration it reads the server snapshot
// (false) so the rendered HTML matches what the server emitted; then on
// the next render it reads the client snapshot (true). This is the
// React 19 way to do "render differently after mount" without
// setState-in-effect or a setMounted dance.
const NOOP_SUBSCRIBE = () => () => {};

function useIsClient(): boolean {
  return useSyncExternalStore(
    NOOP_SUBSCRIBE,
    () => true,
    () => false,
  );
}

export function ThemeToggle() {
  const { resolvedTheme, setTheme } = useTheme();
  const isClient = useIsClient();

  const current = isClient ? resolvedTheme : "dark";
  const next = current === "dark" ? "light" : "dark";

  return (
    <button
      type="button"
      aria-label="Toggle theme"
      onClick={() => setTheme(next)}
      className="rounded-md p-1.5 text-muted-foreground hover:text-foreground transition-colors"
    >
      {current === "dark" ? (
        <Sun className="h-4 w-4" aria-hidden="true" />
      ) : (
        <Moon className="h-4 w-4" aria-hidden="true" />
      )}
    </button>
  );
}
