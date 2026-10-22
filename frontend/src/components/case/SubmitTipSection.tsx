import { Block } from "@/components/case-detail/Block";

export interface SubmitTipSectionProps {
  phone: string | null;
  email: string | null;
  address: string | null;
}

export function SubmitTipSection({ phone, email, address }: SubmitTipSectionProps) {
  if (!phone && !email && !address) return null;

  return (
    <Block title="Submit a tip" headingId="submit-tip-heading">
      <p className="text-2xs leading-relaxed text-muted-foreground">
        Contact the investigating agency directly with information about this case.
        These are the agency&rsquo;s own channels. Latent Trace stores nothing about you.
      </p>
      <dl className="mt-3 space-y-2 text-sm">
        {phone && (
          <div className="flex items-baseline gap-3">
            <dt className="font-mono text-2xs uppercase tracking-snug text-faint">Phone</dt>
            {/* tel: URIs should contain only digits, +, -, and . per RFC 3966. */}
            {/* Display stays human-readable; href gets the normalized form.   */}
            <dd>
              <a href={`tel:${phone.replace(/[^\d+]/g, "")}`} className="text-accent hover:underline">
                {phone}
              </a>
            </dd>
          </div>
        )}
        {email && (
          <div className="flex items-baseline gap-3">
            <dt className="font-mono text-2xs uppercase tracking-snug text-faint">Email</dt>
            <dd>
              <a href={`mailto:${encodeURIComponent(email)}`} className="text-accent hover:underline">
                {email}
              </a>
            </dd>
          </div>
        )}
        {address && (
          <div className="flex items-baseline gap-3">
            <dt className="font-mono text-2xs uppercase tracking-snug text-faint">Address</dt>
            <dd className="text-muted-foreground">{address}</dd>
          </div>
        )}
      </dl>
    </Block>
  );
}
