import { useId, useState } from "react";
import { Info } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * Small "(i)" affordance for a plain-language explanation next to a
 * heading/label — deliberately lighter than `Drawer` (see
 * `apps/web/src/components/ui/drawer.tsx`): a short popover, not a
 * full side panel. Opens on hover or focus (discoverable without a
 * click) and toggles on click too (so it also works on touch, where
 * there's no hover) — closes on blur/mouse-leave/second click.
 *
 * No existing tooltip/popover primitive was in `components/ui/` at the
 * time this was added (only `badge`/`button`/`card`/`drawer`/`input`/
 * `select`/`table`) — the codebase's prior convention for short hints was
 * the native `title` attribute (see `stage-node.tsx`, `rubric-review-panel.tsx`),
 * which doesn't support the multi-sentence explanation this needs and
 * can't be styled to match the design system's tokens. This is a small,
 * self-contained popover built from those same tokens rather than a new
 * dependency.
 */
export function InfoTooltip({
  label = "More info",
  children,
  className,
}: {
  label?: string;
  children: React.ReactNode;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const panelId = useId();

  return (
    <span className={cn("relative inline-flex", className)}>
      <button
        type="button"
        aria-label={label}
        aria-describedby={panelId}
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={() => setOpen(false)}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        className="flex h-4 w-4 items-center justify-center rounded-full text-ink-soft transition-colors duration-fast ease-out hover:text-ink focus-visible:shadow-[var(--focus-ring)]"
      >
        <Info className="h-3.5 w-3.5" />
      </button>
      {open && (
        <div
          id={panelId}
          role="tooltip"
          className="absolute left-1/2 top-full z-50 mt-2 w-72 -translate-x-1/2 rounded-card border border-line bg-paper p-3 text-12 leading-normal text-ink shadow-popover"
        >
          {children}
        </div>
      )}
    </span>
  );
}
