/**
 * Refract's mark: a beam entering a prism and splitting into the spectrum
 * gradient — the same visual idea ParityBeam already uses (a signal passing
 * through unchanged in kind, refracted in color). Reuses --ink and
 * --spectrum tokens, nothing new to the palette.
 */
export function Logo({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 32 32"
      fill="none"
      className={className}
      aria-hidden="true"
    >
      <defs>
        <linearGradient id="refract-logo-spectrum" x1="16" y1="6" x2="30" y2="26" gradientUnits="userSpaceOnUse">
          <stop offset="0%" stopColor="#8B5CF6" />
          <stop offset="50%" stopColor="#4C5FE8" />
          <stop offset="100%" stopColor="#14B8A6" />
        </linearGradient>
      </defs>
      {/* incoming beam */}
      <path d="M2 16 H14" stroke="var(--ink)" strokeWidth="2.5" strokeLinecap="round" />
      {/* prism */}
      <path d="M14 7 L22 16 L14 25 Z" fill="var(--paper)" stroke="var(--ink)" strokeWidth="1.5" strokeLinejoin="round" />
      {/* refracted spectrum beams */}
      <path d="M20 10 L30 6" stroke="url(#refract-logo-spectrum)" strokeWidth="2.5" strokeLinecap="round" />
      <path d="M22 16 L30 16" stroke="url(#refract-logo-spectrum)" strokeWidth="2.5" strokeLinecap="round" />
      <path d="M20 22 L30 26" stroke="url(#refract-logo-spectrum)" strokeWidth="2.5" strokeLinecap="round" />
    </svg>
  );
}
