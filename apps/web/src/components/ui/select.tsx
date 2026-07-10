import * as React from "react";
import { cn } from "@/lib/utils";

export type SelectProps = React.SelectHTMLAttributes<HTMLSelectElement>;

// A thin, token-driven wrapper over the native <select> - deliberately not a
// full Radix/shadcn combobox. The wizard's model pickers are plain "choose
// one of a short curated list" selects; a native element gets keyboard
// support, screen readers, and mobile behavior for free and matches Input's
// styling exactly (h-8, rounded-control, border-line, focus ring).
const Select = React.forwardRef<HTMLSelectElement, SelectProps>(
  ({ className, children, ...props }, ref) => (
    <select
      ref={ref}
      className={cn(
        "h-8 w-full rounded-control border border-line bg-paper px-3 text-13 text-ink transition-colors duration-fast ease-out focus-visible:outline-none focus-visible:shadow-[var(--focus-ring)] disabled:pointer-events-none disabled:opacity-50",
        className
      )}
      {...props}
    >
      {children}
    </select>
  )
);
Select.displayName = "Select";

export { Select };
