import { Link, useRouterState } from "@tanstack/react-router";
import { Workflow, Settings as SettingsIcon, FileText, Home } from "lucide-react";
import { cn } from "@/lib/utils";
import { Logo } from "@/components/logo";
import { ThemeToggle } from "@/components/theme-toggle";

interface NavItem {
  to: string;
  label: string;
  icon: typeof Workflow;
}

const NAV_ITEMS: NavItem[] = [
  { to: "/", label: "Home", icon: Home },
  { to: "/pipelines", label: "Pipelines", icon: Workflow },
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
    // h-screen (a hard cap), not min-h-screen (a floor that lets this whole
    // row grow taller than the viewport when content is tall) - with only
    // a floor, `main`'s flex-stretched height grows right along with it and
    // its own overflow-y-auto region never actually has anything to clip,
    // so the browser scrolls the *whole page*, nav rail included, instead
    // of just the inner content area. Most visible on the Canvas tab
    // (React Flow's own pan/zoom expects a viewport-bounded container, not
    // page-level scroll), but this affected every screen with content
    // taller than the viewport.
    <div className="flex h-screen bg-paper">
      <nav
        className="flex shrink-0 flex-col border-r border-line py-6"
        style={{ width: "var(--nav-rail-width)" }}
        aria-label="Primary"
      >
        {/* Logo also goes to "/" (the landing page), same as the "Home"
            nav item below - two paths to the same place, matching the
            usual "click the logo to go home" convention. */}
        <Link
          to="/"
          className="mb-8 flex flex-col items-center gap-2 px-6 font-display text-20 font-semibold leading-display text-ink"
        >
          <Logo className="h-8 w-8" />
          Reprompt
        </Link>
        <div className="flex flex-col gap-1 px-3">
          {NAV_ITEMS.map((item) => {
            // "/" would match pathname.startsWith(item.to) for every route -
            // needs an exact match, unlike every other nav item.
            const isActive = item.to === "/" ? pathname === "/" : pathname.startsWith(item.to);
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
      {/* min-w-0: a flex item's default min-width is its content's own
          intrinsic min-width, not 0 - a wide child inside `main` (a wide
          single-rank Canvas DAG, the exact shape this was found against)
          could otherwise force `main` wider than its flex-1 share, growing
          this whole row past the viewport and scrolling the *document*
          horizontally, nav rail included, instead of being contained.
          Same root-cause pattern as the migration wizard's transform-rule
          text overflow fixed earlier this session, one level up the tree. */}
      <main className="flex min-w-0 flex-1 flex-col overflow-hidden">
        {/* Reserves real layout space for the theme toggle (rather than a
            fixed/floating overlay) so it never sits on top of a screen's
            own top-right controls (e.g. Contracts' "Mine contract"
            button) - every screen's content starts below this bar, not
            underneath it. */}
        <div className="flex shrink-0 justify-end border-b border-line px-8 py-3">
          <ThemeToggle />
        </div>
        {/* overflow-x-hidden, not just overflow-y-auto: Canvas has its own
            internal pan/zoom for content wider than its container (that's
            the whole point of React Flow) - this level should never itself
            become horizontally scrollable, only vertically for genuinely
            tall (not wide) screens. */}
        <div className="flex-1 overflow-y-auto overflow-x-hidden">
          {/* h-full: gives a definite height for routes (pipeline-workspace)
              that need to size themselves against "the remaining viewport
              below the theme toggle bar" rather than guessing 100vh - a
              plain height:auto block here has no bearing on whether this
              parent's own overflow-y-auto still works for tall content
              (that only depends on this parent having a bounded height,
              which it already does via `flex-1` above), so this is safe
              for every other route too. */}
          <div className="mx-auto h-full max-w-[1440px]">{children}</div>
        </div>
      </main>
    </div>
  );
}
