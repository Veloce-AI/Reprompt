import { create } from "zustand";

interface ImportStore {
  pendingFile: File | null;
  setPendingFile: (file: File) => void;
  clearPendingFile: () => void;
}

// UI-only state (per stack decision: Zustand for UI state, not server data).
// Holds a File the user just dropped/selected on the Pipelines home empty
// state, so the Import wizard route can pick up where they left off
// instead of asking them to select the file a second time. File objects
// aren't serializable, so this can't be passed via router search params.
export const useImportStore = create<ImportStore>((set) => ({
  pendingFile: null,
  setPendingFile: (file) => set({ pendingFile: file }),
  clearPendingFile: () => set({ pendingFile: null }),
}));
