import { cn } from "@/lib/utils";

export interface MOBadgeProps {
  field: string;
  value: string | null;
  lowConfidence: boolean;
  size?: "card" | "detail";
}

/**
 * MO classification badge — used by list cards (size="card") and the
 * detail-page MO section (size="detail"). Hidden entirely when value is
 * null or "unknown" per the card-display contract: showing "Weapon: unknown"
 * adds no information when the case file already doesn't say.
 *
 * Low-confidence extractions render with the same shape but italic + an
 * "uncertain" suffix. The "uncertain" word is the same across cards,
 * detail page, and methodology — single learn-once convention.
 */
export function MOBadge({
  field,
  value,
  lowConfidence,
  size = "card",
}: MOBadgeProps) {
  if (value === null || value === "unknown") {
    return null;
  }
  return (
    <span
      data-testid="mo-badge"
      className={cn(
        "inline-flex items-center gap-1 rounded-sm bg-muted/60 px-2 py-0.5",
        size === "card" ? "text-xs" : "text-sm",
        lowConfidence && "italic"
      )}
    >
      <span className="font-medium text-muted-foreground">{field}:</span>
      <span>{value}</span>
      {lowConfidence && (
        <span className="text-xs text-muted-foreground">uncertain</span>
      )}
    </span>
  );
}
