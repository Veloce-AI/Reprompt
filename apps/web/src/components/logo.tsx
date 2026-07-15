/**
 * Reprompt's mark: one beam enters, splits into two candidate paths (a
 * lens shape — the search), and resolves into a single confident beam in
 * the brand's primary indigo (the winner). Maps directly to what the
 * product does: try multiple directions, converge on one answer. Reuses
 * --ink and --beam tokens, plus the two spectrum extremes for the
 * candidate arcs — nothing new to the palette.
 */
export function Logo({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 32 32"
      fill="none"
      className={className}
      aria-hidden="true"
    >
      {/* incoming beam - the original prompt */}
      <path d="M2 16 H8" stroke="var(--ink)" strokeWidth="2.5" strokeLinecap="round" />
      {/* two candidate arcs - the search, forming a lens */}
      <path d="M8 16 Q 16 4 24 16" stroke="#8B5CF6" strokeWidth="2.25" strokeLinecap="round" />
      <path d="M8 16 Q 16 28 24 16" stroke="#14B8A6" strokeWidth="2.25" strokeLinecap="round" />
      {/* resolved beam - the winner, emphasized in the brand accent */}
      <path d="M24 16 H30" stroke="var(--beam)" strokeWidth="3" strokeLinecap="round" />
    </svg>
  );
}
