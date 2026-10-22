// @vitest-environment node

import { beforeEach, describe, expect, it, vi } from "vitest";

const signInWithOtp = vi.fn();

vi.mock("next/navigation", () => ({
  redirect: vi.fn((path: string) => {
    throw new Error(`redirect:${path}`);
  }),
}));

vi.mock("@/lib/supabase/server", () => ({
  createClient: vi.fn(async () => ({
    auth: {
      signInWithOtp,
    },
  })),
}));

import { sendAdminMagicLink } from "./actions";

function formData(email: string) {
  const data = new FormData();
  data.set("email", email);
  return data;
}

describe("sendAdminMagicLink", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    process.env.NEXT_PUBLIC_SITE_URL = "https://app.example/";
  });

  it("redirects invalid email input to the local validation error", async () => {
    await expect(sendAdminMagicLink(formData("not-an-email"))).rejects.toThrow(
      "redirect:/admin/login?error=email",
    );
  });

  it("sends a magic link without creating auth users", async () => {
    signInWithOtp.mockResolvedValue({ error: null });

    await expect(sendAdminMagicLink(formData("Admin@Example.com "))).rejects.toThrow(
      "redirect:/admin/login?sent=1",
    );

    expect(signInWithOtp).toHaveBeenCalledWith({
      email: "admin@example.com",
      options: {
        emailRedirectTo: "https://app.example/auth/callback?next=/admin",
        shouldCreateUser: false,
      },
    });
  });

  it("uses the same sent redirect when Supabase declines the OTP request", async () => {
    signInWithOtp.mockResolvedValue({ error: new Error("Signups not allowed") });

    await expect(sendAdminMagicLink(formData("missing@example.com"))).rejects.toThrow(
      "redirect:/admin/login?sent=1",
    );
  });
});
