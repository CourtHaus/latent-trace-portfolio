import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { OpsSnapshotDashboard } from "@/components/admin/OpsSnapshotDashboard";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { ApiError } from "@/lib/api";
import { getOperatorSnapshot } from "@/lib/operatorSnapshot";
import { createClient } from "@/lib/supabase/server";

export const metadata: Metadata = {
  title: "Admin",
  robots: { index: false, follow: false },
};

function UnauthorizedAdmin() {
  return (
    <main className="px-6 py-16 sm:px-10">
      <section className="mx-auto max-w-[520px]">
        <Card size="sm">
          <CardContent className="p-5">
            <h1 className="text-2xl font-medium">Admin access required</h1>
            <p className="mt-2 text-sm leading-6 text-muted-foreground">
              This Supabase account is signed in, but it is not allowlisted for
              Latent Trace operator access.
            </p>
            <form action="/admin/logout" method="post" className="mt-4">
              <Button type="submit" variant="outline">
                Logout
              </Button>
            </form>
          </CardContent>
        </Card>
      </section>
    </main>
  );
}

function SnapshotError() {
  return (
    <main className="px-6 py-16 sm:px-10">
      <section className="mx-auto max-w-[520px]">
        <Card size="sm">
          <CardContent className="p-5">
            <h1 className="text-2xl font-medium">Snapshot unavailable</h1>
            <p className="mt-2 text-sm leading-6 text-muted-foreground">
              The operator snapshot could not be loaded. Refresh after the API
              is healthy.
            </p>
          </CardContent>
        </Card>
      </section>
    </main>
  );
}

export default async function AdminPage() {
  const supabase = await createClient();

  // SEC-F02: authorize on getUser(), which revalidates the JWT against the
  // Supabase Auth server. getSession() only decodes the cookie and must not be
  // trusted for an access decision. getSession() is still used afterward purely
  // to obtain the access token to forward to the backend, which performs the
  // authoritative admin check on /operator/snapshot.
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) {
    redirect("/admin/login");
  }

  const {
    data: { session },
  } = await supabase.auth.getSession();

  if (!session?.access_token) {
    redirect("/admin/login");
  }

  let snapshot;
  try {
    snapshot = await getOperatorSnapshot(session.access_token);
  } catch (err) {
    if (err instanceof ApiError && err.status === 403) {
      return <UnauthorizedAdmin />;
    }

    return <SnapshotError />;
  }

  return <OpsSnapshotDashboard snapshot={snapshot} />;
}
