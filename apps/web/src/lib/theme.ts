import { create } from "zustand";

export type ThemeMode = "system" | "light" | "dark";

const STORAGE_KEY = "reprompt-theme";

function readStoredMode(): ThemeMode {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw === "light" || raw === "dark" || raw === "system") return raw;
  } catch {
    // Storage unavailable (private mode, disabled cookies, etc.) - fall
    // through to the default below, same tolerance as canvas-layout.ts's
    // loadCanvasLayoutChoice.
  }
  return "system";
}

// The DOM half of theme switching: an explicit "light"/"dark" override sets
// data-theme so it wins over the OS setting (see tokens.css's paired
// @media(prefers-color-scheme:dark) / [data-theme] blocks). "system" removes
// the attribute entirely so the CSS media query alone decides - which also
// means a live OS-level theme change is picked up with zero JS listener; the
// browser's own media query engine does that for free, no matchMedia
// subscription needed here.
function applyThemeAttribute(mode: ThemeMode): void {
  const root = document.documentElement;
  if (mode === "system") {
    root.removeAttribute("data-theme");
  } else {
    root.setAttribute("data-theme", mode);
  }
}

interface ThemeStore {
  mode: ThemeMode;
  setMode: (mode: ThemeMode) => void;
}

// UI-only state (per stack decision: Zustand for UI state, not server data -
// see store/import-store.ts for the precedent). `index.html` carries a small
// inline script that mirrors this same read-and-apply logic so an explicit
// light/dark override paints correctly on the very first frame, before this
// module (or React) has loaded - keep the two in sync if this logic changes.
export const useThemeStore = create<ThemeStore>((set) => ({
  mode: readStoredMode(),
  setMode: (mode) => {
    try {
      localStorage.setItem(STORAGE_KEY, mode);
    } catch {
      // Storage full/unavailable - the choice just won't persist across reloads.
    }
    applyThemeAttribute(mode);
    set({ mode });
  },
}));
