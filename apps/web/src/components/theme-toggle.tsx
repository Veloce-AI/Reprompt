import { cn } from "@/lib/utils";
import { useThemeStore, type ThemeMode } from "@/lib/theme";

const THEME_OPTIONS: { value: ThemeMode; label: string; title: string }[] = [
  { value: "system", label: "System", title: "Follow your device's setting" },
  { value: "light", label: "Light", title: "Always use the light theme" },
  { value: "dark", label: "Dark", title: "Always use the dark theme" },
];

/**
 * Three-state theme picker: System (default, follows OS `prefers-color-scheme`)
 * / Light / Dark. Same segmented-control visual pattern as the Canvas tab's
 * layout toolbar (`pipeline-canvas.tsx`'s `SegmentedGroup`) - reimplemented
 * here as its own small component rather than imported, since that one is a
 * private, unexported helper local to that file.
 */
export function ThemeToggle() {
  const mode = useThemeStore((s) => s.mode);
  const setMode = useThemeStore((s) => s.setMode);

  return (
    <div
      className="flex overflow-hidden rounded-control border border-line bg-paper"
      role="group"
      aria-label="Theme"
    >
      {THEME_OPTIONS.map((option) => {
        const selected = option.value === mode;
        return (
          <button
            key={option.value}
            type="button"
            title={option.title}
            aria-pressed={selected}
            onClick={() => setMode(option.value)}
            className={cn(
              "px-2.5 py-1 text-12 font-medium transition-colors duration-fast ease-out",
              selected
                ? "bg-beam-soft text-beam"
                : "text-ink-soft hover:bg-beam-soft/40 hover:text-ink"
            )}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}
