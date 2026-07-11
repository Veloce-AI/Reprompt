import { Link, useRouterState } from "@tanstack/react-router";
import { Workflow, Settings as SettingsIcon, FileText } from "lucide-react";
import { cn } from "@/lib/utils";
import { Logo } from "@/components/logo";

interface NavItem {
  to: string;
  label: string;
  icon: typeof Workflow;
}

const NAV_ITEMS: NavItem[] = [
  { to: "/", label: "Pipelines", icon: Workflow },
  { to: "/schema", label: "Trace format", icon: FileText },
  { to: "/settings", label: "Settings", icon: SettingsIcon },
];

/**
 * Persistent app frame: a left nav rail (per tokens.css --nav-rail-width,
 * defined in M0 but never wired up until now) plus a max-width content
 * area. Every top-level screen wraps its content in this instead of
 * inventing its own header/spacing - the whole point is one consistent
 * frame across the product instead of each screen feeling separate.
 */
export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = useRouterState({ select: (s) => s.location.pathname });

  return (
    <div className="flex min-h-screen bg-paper">
      <nav
        className="flex shrink-0 flex-col border-r border-line py-6"
        style={{ width: "var(--nav-rail-width)" }}
        aria-label="Primary"
      >
        <Link
          to="/"
          className="mb-8 flex flex-col items-center gap-2 px-6 font-display text-20 font-semibold leading-display text-ink"
        >
          <Logo className="h-8 w-8" />
          Refract
        </Link>
        <div className="flex flex-col gap-1 px-3">
          {NAV_ITEMS.map((item) => {
            const isActive =
              item.to === "/" ? pathname === "/" : pathname.startsWith(item.to);
            const Icon = item.icon;
            return (
              <Link
                key={item.to}
                to={item.to}
                className={cn(
                  "flex items-center gap-3 rounded-control px-3 py-2 text-13 font-medium transition-colors duration-fast ease-out focus-visible:shadow-[var(--focus-ring)]",
                  isActive
                    ? "bg-beam-soft text-beam"
                    : "text-ink-soft hover:bg-beam-soft/50 hover:text-ink"
                )}
              >
                <Icon className="h-4 w-4 shrink-0" aria-hidden="true" />
                {item.label}
              </Link>
            );
          })}
        </div>
      </nav>
      <main className="flex-1 overflow-y-auto">
        <div className="mx-auto max-w-[1440px]">{children}</div>
      </main>
    </div>
  );
}
