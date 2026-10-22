import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import AdminLoginPage from "./page";

describe("/admin/login page", () => {
  it("renders generic sent copy without confirming a registered admin email", async () => {
    const tree = await AdminLoginPage({
      searchParams: Promise.resolve({
        sent: "1",
        email: "admin@example.com",
      }),
    });

    render(tree);

    expect(
      screen.getByText(/if this email is eligible, a magic link has been sent/i),
    ).toBeInTheDocument();
    expect(screen.queryByText(/registered admin/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/admin@example\.com/i)).not.toBeInTheDocument();
  });

  it("keeps invalid local email feedback specific to validation", async () => {
    const tree = await AdminLoginPage({
      searchParams: Promise.resolve({
        error: "email",
      }),
    });

    render(tree);

    expect(screen.getByText(/enter a valid email address/i)).toBeInTheDocument();
    expect(screen.queryByText(/registered admin/i)).not.toBeInTheDocument();
  });
});
