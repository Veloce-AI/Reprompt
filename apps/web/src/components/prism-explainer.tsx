import { useState } from "react";
import {
  DrawerRoot,
  DrawerContent,
  DrawerHeader,
  DrawerTitle,
  DrawerDescription,
  DrawerBody,
} from "@/components/ui/drawer";

/**
 * Self-contained "How Prism works" trigger + panel. Owns its own
 * open/close state, so any caller just drops in `<PrismExplainer />`
 * wherever Prism's live view is shown (currently
 * `MigrationSuccessScreen`) — no wiring required.
 *
 * Content is deliberately factual, not marketing copy — it describes the
 * real, already-shipped loop (see DEV_TRACKER.md's "Why two strategies,
 * and why the name 'Prism'" section): judge-aware critique, up to 3
 * refine rounds, budget-bounded, per-stage. It explicitly does NOT claim
 * memory/learning across separate migrations — nothing persists between
 * runs today, and the copy says so plainly rather than leaving it
 * ambiguous (see START_HERE.md / DEV_TRACKER.md's branding-pass notes).
 */
export function PrismExplainer() {
  const [open, setOpen] = useState(false);

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="text-12 text-ink-soft underline decoration-dotted underline-offset-2 transition-colors duration-fast ease-out hover:text-ink"
      >
        How Prism works
      </button>

      <DrawerRoot open={open} onOpenChange={setOpen}>
        <DrawerContent>
          <DrawerHeader>
            <DrawerTitle>How Prism works</DrawerTitle>
            <DrawerDescription>Prism is a self-evolving prompt optimizer</DrawerDescription>
          </DrawerHeader>
          <DrawerBody>
            <div className="space-y-4 text-13 text-ink">
              <p>
                For each pipeline stage, Prism evolves the prompt through several
                rounds before locking in a winner: it mutates the prompt, scores
                the results, has an AI judge critique the weakest attempts (with
                real reasoning, not just a number), and refines the prompt
                against that specific feedback — up to 3 rounds per stage. A
                parameter/format sweep runs alongside, and the best-scoring
                candidate across every round is what gets selected.
              </p>
              <p>
                Every round is bounded: refinement stops early once a round
                stops actually improving the score, and the whole run stops the
                moment it hits your budget — Prism never keeps spending past
                what it needs to.
              </p>
              <p>
                <strong>What Prism doesn't do:</strong> each migration evolves
                its own prompt from scratch. Prism doesn't carry learnings
                between separate migrations — nothing here "remembers" a past
                run or "gets smarter" over time.
              </p>
            </div>
          </DrawerBody>
        </DrawerContent>
      </DrawerRoot>
    </>
  );
}
