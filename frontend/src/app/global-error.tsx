"use client";

// Last-resort boundary: only fires when the ROOT layout itself throws, so it
// renders WITHOUT the app shell or globals.css. Styles are inlined with the
// brand palette so it renders correctly even when nothing else loaded. Per-route
// error.tsx handles the common cases; this is the safety net.
export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  console.error("Root error boundary:", error);
  return (
    <html lang="en">
      <body
        style={{
          margin: 0,
          minHeight: "100vh",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background: "#090F15",
          color: "#E9EDF2",
          fontFamily: "system-ui, -apple-system, 'Segoe UI', sans-serif",
          padding: "2rem",
        }}
      >
        <div role="alert" style={{ maxWidth: 420, textAlign: "center" }}>
          <p
            style={{
              fontFamily: "ui-monospace, monospace",
              fontSize: 12,
              letterSpacing: "0.14em",
              textTransform: "uppercase",
              color: "#8B939C",
              margin: 0,
            }}
          >
            Error
          </p>
          <h1 style={{ fontSize: 24, fontWeight: 600, margin: "12px 0 0" }}>
            Something went wrong
          </h1>
          <p style={{ fontSize: 14, lineHeight: 1.6, color: "#8B939C", marginTop: 12 }}>
            An unexpected error interrupted the page. Trying again often resolves
            it.
          </p>
          <button
            type="button"
            onClick={() => reset()}
            style={{
              marginTop: 20,
              border: "1px solid #2A3540",
              borderRadius: 6,
              background: "transparent",
              color: "#E9EDF2",
              fontSize: 14,
              fontWeight: 600,
              padding: "8px 16px",
              cursor: "pointer",
            }}
          >
            Try again
          </button>
        </div>
      </body>
    </html>
  );
}
