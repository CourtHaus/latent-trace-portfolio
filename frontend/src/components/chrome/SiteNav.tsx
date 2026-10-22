"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Menu } from "lucide-react";
import { Logo } from "./Logo";
import { Sheet, SheetClose, SheetContent, SheetTitle, SheetTrigger } from "@/components/ui/sheet";

interface NavItem {
  label: string;
  href: string;
  match: (pathname: string) => boolean;
}

const NAV_ITEMS: NavItem[] = [
  {
    label: "Cases",
    href: "/cold-cases",
    match: (p) => p === "/cold-cases" || (p.startsWith("/cold-cases/") && p !== "/cold-cases/map"),
  },
  { label: "Map", href: "/cold-cases/map", match: (p) => p === "/cold-cases/map" },
  { label: "Methodology", href: "/methodology", match: (p) => p === "/methodology" || p.startsWith("/methodology#") },
  { label: "Briefings", href: "/briefings", match: (p) => p === "/briefings" },
  { label: "About", href: "/about", match: (p) => p === "/about" },
];

export function SiteNav() {
  const pathname = usePathname() ?? "/";

  return (
    <nav
      className="sticky top-0 z-40 border-b border-border bg-background/80 backdrop-blur-md"
      aria-label="Primary"
    >
      <div className="bleed flex h-14 items-center gap-6">
        <Logo size="lg" />
        <div className="hidden items-center gap-7 md:flex">
          {NAV_ITEMS.map((item) => {
            const isActive = item.match(pathname);
            return (
              <Link
                key={item.label}
                href={item.href}
                aria-current={isActive ? "page" : undefined}
                className={
                  "relative flex h-14 items-center text-sm font-normal transition-colors " +
                  (isActive
                    ? "text-foreground after:absolute after:bottom-0 after:left-0 after:right-0 after:h-px after:bg-accent"
                    : "text-muted-foreground hover:text-foreground")
                }
              >
                {item.label}
              </Link>
            );
          })}
        </div>
        <Link
          href="/cold-cases"
          className="navlink ml-auto hidden font-display text-sm font-semibold uppercase tracking-eyebrow text-foreground md:block"
        >
          Open the index
        </Link>
        <div className="ml-auto flex items-center gap-2 md:hidden">
          {/* ThemeToggle hidden under force-dark; restored in the light-theme
              phase (Phase G). Sign-in CTA removed until the auth tier ships --
              it pointed at #todo and read as broken. */}
          <Sheet>
            <SheetTrigger
              aria-label="Open navigation"
              className="rounded-md border border-border p-2 text-muted-foreground hover:text-foreground"
            >
              <Menu className="h-4 w-4" aria-hidden="true" />
            </SheetTrigger>
            <SheetContent side="right" className="w-64 p-6">
              <SheetTitle className="sr-only">Navigation</SheetTitle>
              <div className="flex flex-col gap-4 pt-4">
                {NAV_ITEMS.map((item) => {
                  const isActive = item.match(pathname);
                  return (
                    <SheetClose
                      key={item.label}
                      nativeButton={false}
                      render={
                        <Link
                          href={item.href}
                          aria-current={isActive ? "page" : undefined}
                          className={
                            "text-base transition-colors " +
                            (isActive
                              ? "font-medium text-foreground"
                              : "text-muted-foreground hover:text-foreground")
                          }
                        />
                      }
                    >
                      {item.label}
                    </SheetClose>
                  );
                })}
              </div>
            </SheetContent>
          </Sheet>
        </div>
      </div>
    </nav>
  );
}
