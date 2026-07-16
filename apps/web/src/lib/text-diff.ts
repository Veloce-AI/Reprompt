/**
 * Word-level diff between two strings — powers the migration Results
 * section's before/after prompt view (see DEV_TRACKER.md's "Phase C —
 * Before/after prompt diff"). Pure, no React/DOM — unit-testable on its
 * own, rendered by `migration-success-screen.tsx`.
 *
 * Deliberately hand-rolled instead of pulling in a diff dependency
 * (`diff`/`jsdiff` etc.) — prompts are short enough (a few hundred to a
 * couple thousand words at most) that a plain O(n*m) LCS table is more
 * than fast enough, and it keeps this a zero-dependency addition per the
 * task's own "keep it minimal" guidance.
 */

export type DiffOpType = "equal" | "insert" | "delete";

export interface DiffOp {
  type: DiffOpType;
  text: string;
}

/**
 * Tokenizes on whitespace boundaries while keeping the whitespace itself as
 * its own token (so re-joining every token reproduces the original string
 * exactly) — e.g. `"a  b"` -> `["a", "  ", "b"]`.
 */
function tokenize(text: string): string[] {
  if (text === "") return [];
  return text.split(/(\s+)/).filter((t) => t.length > 0);
}

/**
 * Longest-common-subsequence word diff between `before` and `after`.
 * Returns a list of ops that, concatenated in order, reproduce `after`
 * (equal + insert) and, taking only equal + delete, reproduce `before`.
 * Adjacent tokens of the same op type are merged into one `DiffOp` so the
 * caller doesn't need to do its own coalescing before rendering.
 */
export function diffWords(before: string, after: string): DiffOp[] {
  const a = tokenize(before);
  const b = tokenize(after);
  const n = a.length;
  const m = b.length;

  // dp[i][j] = length of the LCS of a[i:] and b[j:]
  const dp: number[][] = Array.from({ length: n + 1 }, () => new Array<number>(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
    }
  }

  const raw: DiffOp[] = [];
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (a[i] === b[j]) {
      raw.push({ type: "equal", text: a[i] });
      i++;
      j++;
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      raw.push({ type: "delete", text: a[i] });
      i++;
    } else {
      raw.push({ type: "insert", text: b[j] });
      j++;
    }
  }
  while (i < n) {
    raw.push({ type: "delete", text: a[i] });
    i++;
  }
  while (j < m) {
    raw.push({ type: "insert", text: b[j] });
    j++;
  }

  // Coalesce consecutive same-type ops into one, so the renderer emits one
  // <span> per run of changes rather than one per word.
  const ops: DiffOp[] = [];
  for (const op of raw) {
    const last = ops[ops.length - 1];
    if (last && last.type === op.type) {
      last.text += op.text;
    } else {
      ops.push({ ...op });
    }
  }
  return ops;
}
