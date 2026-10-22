import type { ReactNode } from "react";
import { cn } from "@/lib/utils";
import { Block } from "./Block";

interface ExternalReferencesProps {
  namusCaseId: string | null;
  ncmecCaseId: string | null;
  ncicCaseId?: string | null;
}

function ExtRow({
  label,
  id,
  href,
  title,
}: {
  label: ReactNode;
  id: string;
  href?: string;
  title?: string;
}) {
  const inner = (
    <>
      <span className="font-mono text-2xs uppercase tracking-snug text-muted-foreground">
        {label}
      </span>
      <span className="shrink-0 font-mono text-2xs text-foreground transition-colors group-hover:text-accent">
        {id}
        {href ? <span aria-hidden="true"> →</span> : ""}
      </span>
    </>
  );
  const cls =
    "flex items-center justify-between gap-4 border-b border-hair px-3 py-2.5 text-sm last:border-b-0";
  return href ? (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className={cn(cls, "group transition-colors")}
    >
      {inner}
    </a>
  ) : (
    <div className={cls} title={title}>
      {inner}
    </div>
  );
}

export function ExternalReferences({ namusCaseId, ncmecCaseId, ncicCaseId }: ExternalReferencesProps) {
  if (!namusCaseId && !ncmecCaseId && !ncicCaseId) return null;
  const count = [namusCaseId, ncmecCaseId, ncicCaseId].filter(Boolean).length;

  return (
    <Block
      title="External references"
      headingId="external-references-heading"
      tag={`${count} linked`}
      bodyClassName="px-1 py-1"
    >
      <div className="flex flex-col">
        {namusCaseId && (
          <ExtRow
            label="NamUs unidentified person"
            id={namusCaseId}
            href={`https://www.namus.gov/MissingPersons/Search?Term=${encodeURIComponent(namusCaseId)}`}
          />
        )}
        {ncmecCaseId && (
          <ExtRow
            label="NCMEC poster"
            id={ncmecCaseId}
            href={`https://www.missingkids.org/poster/NCMC/${encodeURIComponent(ncmecCaseId)}/1`}
          />
        )}
        {ncicCaseId && (
          <ExtRow
            label="NCIC reference"
            id={ncicCaseId}
            title="National Crime Information Center: a law-enforcement-only system, not publicly searchable"
          />
        )}
      </div>
    </Block>
  );
}
