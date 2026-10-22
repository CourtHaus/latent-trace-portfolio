import type { Metadata } from "next";
import { Mail } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { sendAdminMagicLink } from "./actions";

export const metadata: Metadata = {
  title: "Admin Login",
  robots: { index: false, follow: false },
};

export default async function AdminLoginPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = await searchParams;
  const sent = params.sent === "1";
  const error = typeof params.error === "string" ? params.error : "";
  const errorMessage =
    error === "email"
      ? "Enter a valid email address."
      : "Sign-in link could not be verified. Request a new link.";

  return (
    <main className="px-6 py-16 sm:px-10">
      <section className="mx-auto max-w-[420px]">
        <div className="mb-6">
          <p className="mb-2 font-mono text-2xs uppercase tracking-eyebrow text-muted-foreground">
            Operator Access
          </p>
          <h1 className="text-3xl font-medium">Admin login</h1>
        </div>
        <Card size="sm">
          <CardContent className="p-5">
            {sent ? (
              <p className="text-sm leading-6 text-muted-foreground">
                If this email is eligible, a magic link has been sent. Open it from this browser
                to continue.
              </p>
            ) : (
              <form action={sendAdminMagicLink} className="space-y-4">
                <div className="space-y-2">
                  <label className="block text-sm font-medium" htmlFor="email">
                    Email
                  </label>
                  <input
                    id="email"
                    name="email"
                    type="email"
                    required
                    autoComplete="email"
                    aria-invalid={error ? true : undefined}
                    aria-describedby={error ? "email-error" : undefined}
                    className="h-10 w-full rounded-md border border-border bg-background px-3 text-sm outline-none focus:border-ring focus:ring-3 focus:ring-ring/30"
                  />
                </div>
                {error && (
                  <p id="email-error" role="alert" className="text-sm leading-6 text-destructive">
                    {errorMessage}
                  </p>
                )}
                <Button type="submit" className="w-full">
                  <Mail aria-hidden="true" />
                  Send magic link
                </Button>
              </form>
            )}
          </CardContent>
        </Card>
      </section>
    </main>
  );
}
