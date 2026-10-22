import type { ReactNode } from "react";
import type { components } from "@/lib/api-types";
import { humanizeGender } from "@/lib/humanizeGender";
import { VictimProvenance } from "./VictimProvenance";

type ProvenanceSource = "source" | "tier2" | null;

function ExtractionSuffix({ source }: { source: ProvenanceSource }) {
  if (source !== "tier2") return null;
  return (
    <span className="ml-1.5 text-2xs italic text-faint">
      (extracted from narrative)
    </span>
  );
}

export interface VictimCardProps {
  caseId: number;
  victim_id: number;
  first_name: string | null;
  last_name: string | null;
  gender: string | null;
  height_text: string | null;
  weight_num: number | null;
  age_text: string | null;
  age_num: number | null;
  race: string | null;
  eye_color: string | null;
  hair_color: string | null;
  dob?: string | null;
  dod?: string | null;
  ethnicity?: string | null;
  tribal_affiliation?: string | null;
  identifying_marks?: string | null;
  aliases?: string | null;
  occupation?: string | null;
  age_source?: ProvenanceSource;
  gender_source?: ProvenanceSource;
  race_source?: ProvenanceSource;
  age_extraction?: components["schemas"]["ExtractedField"] | null;
  gender_extraction?: components["schemas"]["ExtractedField"] | null;
}

export function VictimCard(props: VictimCardProps) {
  const {
    caseId, victim_id,
    first_name, last_name,
    gender, height_text, weight_num,
    age_text, age_num, race,
    eye_color, hair_color,
    dob, dod, ethnicity, tribal_affiliation,
    identifying_marks, aliases, occupation,
    age_source, gender_source, race_source,
    age_extraction, gender_extraction,
  } = props;

  const name = [first_name, last_name].filter(Boolean).join(" ") || `Unidentified${gender ? ` ${humanizeGender(gender) ?? gender}` : ""}`;

  const demographicRows: Array<[string, string | null, ReactNode]> = [
    [
      "Age",
      age_text ?? (age_num !== null ? String(age_num) : null),
      <VictimProvenance key="age" source={age_source ?? null} field={age_extraction} fieldName="victim_age" victimName={name} />,
    ],
    [
      "Gender",
      gender ? (humanizeGender(gender) ?? gender) : null,
      <VictimProvenance key="gender" source={gender_source ?? null} field={gender_extraction} fieldName="victim_gender" victimName={name} />,
    ],
    [
      "Race",
      race,
      <ExtractionSuffix key="race" source={race_source ?? null} />,
    ],
    ["Ethnicity", ethnicity ?? null, null],
    ["Height", height_text, null],
    ["Weight", weight_num !== null ? `${weight_num} lbs` : null, null],
    ["Eye color", eye_color, null],
    ["Hair color", hair_color, null],
    ["Date of birth", dob ?? null, null],
    ["Date of death", dod ?? null, null],
    ["Tribal affiliation", tribal_affiliation ?? null, null],
    ["Identifying marks", identifying_marks ?? null, null],
    ["Aliases", aliases ?? null, null],
    ["Occupation", occupation ?? null, null],
  ];

  return (
    <article id={`victim-${caseId}-${victim_id}`} className="space-y-3">
      <h3 className="font-display text-lg font-semibold text-foreground">{name}</h3>
      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2.5">
        {demographicRows
          .filter(([, value]) => value)
          .map(([label, value, suffix]) => (
            <div key={label} className="contents">
              <dt className="font-mono text-2xs uppercase tracking-snug text-faint">
                {label}
              </dt>
              <dd className="text-right text-sm text-foreground">
                {value}
                {suffix}
              </dd>
            </div>
          ))}
      </dl>
    </article>
  );
}
