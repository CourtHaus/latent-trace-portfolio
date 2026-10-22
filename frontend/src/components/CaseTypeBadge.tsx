import { humanizeCaseType } from "@/lib/humanizeCaseType";
import { cn } from "@/lib/utils";

export interface CaseTypeBadgeProps {
  caseType: string;
  className?: string;
}

// Instrument badges: mono uppercase pills, color-coded by severity. Accent is
// reserved for live/interactive signals, so types use the status palette
// (danger/warning) + neutral, not the accent.
const TYPE_STYLES: Readonly<Record<string, string>> = {
  homicide: "border-danger/35 bg-danger/10 text-danger",
  suspicious_death: "border-warning/35 bg-warning/10 text-warning",
};
const DEFAULT_STYLE = "border-border bg-elev text-faint";

/**
 * Small categorical tag for a case's type — a mono uppercase pill, color-coded
 * by severity (homicide = red, suspicious death = amber, others neutral).
 */
export function CaseTypeBadge({ caseType, className }: CaseTypeBadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center whitespace-nowrap rounded border px-2 py-0.5 font-mono text-2xs uppercase tracking-eyebrow",
        TYPE_STYLES[caseType] ?? DEFAULT_STYLE,
        className,
      )}
    >
      {humanizeCaseType(caseType)}
    </span>
  );
}
