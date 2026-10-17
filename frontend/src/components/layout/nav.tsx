"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { KeyRoundIcon, ListChecksIcon } from "lucide-react";
import { cn } from "cn";
import { API_MODE } from "@/lib/api/client";
import { BrandMark, NAV_BACK, NAV_SWITCH } from "@/components/layout/transitions";

export const NAV = [
  { href: "/jobs", label: "Jobs", icon: ListChecksIcon },
  { href: "/providers", label: "Providers & keys", icon: KeyRoundIcon },
];

export function pageTitle(pathname: string) {
  return NAV.find((n) => pathname.startsWith(n.href))?.label ?? "Code Fixer";
}

function Brand({ compact }: { compact?: boolean }) {
  return (
    <Link
      href="/"
      transitionTypes={NAV_BACK}
      aria-label="Code Fixer home"
      className="flex shrink-0 items-center gap-2 font-semibold tracking-tight"
    >
      <BrandMark morph={!compact} />
      <span className={compact ? "hidden sm:inline" : undefined}>Code Fixer</span>
    </Link>
  );
}

function NavLinks({ compact }: { compact?: boolean }) {
  const pathname = usePathname();
  return (
    <nav aria-label="Main" className={cn("flex gap-1", compact ? "flex-row" : "flex-col")}>
      {NAV.map(({ href, label, icon: Icon }) => {
        const active = pathname.startsWith(href);
        return (
          <Link
            key={href}
            href={href}
            transitionTypes={NAV_SWITCH}
            aria-current={active ? "page" : undefined}
            className={cn(
              "flex items-center gap-2 rounded-lg px-2.5 py-1.5 text-sm whitespace-nowrap transition-colors",
              active
                ? "bg-muted font-medium text-foreground"
                : "text-muted-foreground hover:bg-muted/60 hover:text-foreground",
            )}
          >
            <Icon className="size-4" />
            {label}
          </Link>
        );
      })}
    </nav>
  );
}

export function Sidebar() {
  return (
    <aside className="sticky top-0 hidden h-dvh w-56 shrink-0 flex-col gap-6 border-r bg-sidebar px-3 py-4 md:flex">
      <div className="px-1.5">
        <Brand />
      </div>
      <NavLinks />
      <div className="mt-auto px-2.5 text-xs text-muted-foreground">
        v0 · {API_MODE === "mock" ? "mock data" : "live backend"}
      </div>
    </aside>
  );
}

export function MobileNav() {
  return (
    <div className="flex items-center justify-between gap-3 border-b px-4 py-2 md:hidden">
      <Brand compact />
      <NavLinks compact />
    </div>
  );
}
