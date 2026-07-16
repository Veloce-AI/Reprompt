import { useState } from "react";
import { Link, useParams } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { ChevronDown, ChevronRight } from "lucide-react";
import { getMigrationResults, type CandidateOut, type StageSummary } from "@/lib/api";
import { AppShell } from "@/components/app-shell";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ParityBeam, parityStatus } from "@/components/parity-beam";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

const STATUS_LABELS: Record<string, string> = {
  pending: "Pending",
  running: "Running",
  completed: "Completed",
  failed: "Failed",
  stopped_early: "Stopped early",
};

const STATUS_VARIANTS: Record<string, "outline" | "pass" | "fail" | "neutral" | "near"> = {
  pending: "outline",
  running: "neutral",
  completed: "pass",
  failed: "fail",
  stopped_early: "near",
};

function fmt(value: number, decimals = 4): string {
  return `$${value.toFixed(decimals)}`;
}

function scorePercent(scores: Record<string, number | null>): number | null {
  const f = scores["final"];
  return f != null ? Math.round(f * 100) : null;
}

function ScoreBadge({
  scores,
  parity_threshold,
}: {
  scores: Record<string, number | null>;
  parity_threshold: number;
}) {
  const pct = scorePercent(scores);
  if (pct == null) return <span className="text-13 text-ink-soft">—</span>;
  const status = parityStatus(pct, parity_threshold * 100);
  return <Badge variant={status}>{pct}%</Badge>;
}

function StageRow({
  summary,
  parity_threshold,
  candidates,
}: {
  summary: StageSummary;
  parity_threshold: number;
  candidates: CandidateOut[];
}) {
  const [expanded, setExpanded] = useState(false);
  const best = summary.best_candidate;
  const pct = best ? scorePercent(best.scores) : null;

  return (
    <>
      <TableRow
        className="cursor-pointer select-none"
        onClick={() => setExpanded((v) => !v)}
        aria-expanded={expanded}
      >
        <TableCell className="w-6 pr-0">
          {expanded ? (
            <ChevronDown className="h-4 w-4 text-ink-soft" />
          ) : (
            <ChevronRight className="h-4 w-4 text-ink-soft" />
          )}
        </TableCell>
        <TableCell className="font-medium text-ink">{summary.stage_name}</TableCell>
        <TableCell className="font-mono text-13 text-ink-soft">{summary.original_model}</TableCell>
        <TableCell className="font-mono text-13 text-ink">
          {best ? best.target_model : <span className="text-ink-soft">—</span>}
        </TableCell>
        <TableCell className="w-48">
          {pct != null ? (
            <div className="flex items-center gap-3">
              <ParityBeam
                score={pct}
                passThreshold={parity_threshold * 100}
                className="w-24"
              />
              <ScoreBadge scores={best!.scores} parity_threshold={parity_threshold} />
            </div>
          ) : (
            <span className="text-13 text-ink-soft">No attempts</span>
          )}
        </TableCell>
        <TableCell className="font-mono text-13 tabular-nums text-ink-soft">
          {fmt(summary.total_cost)}
        </TableCell>
        <TableCell className="text-13 text-ink-soft">{summary.attempts}</TableCell>
      </TableRow>

      {expanded && (
        <TableRow className="bg-beam-soft/30 hover:bg-beam-soft/30">
          <TableCell colSpan={7} className="px-8 py-4">
            {best && (
              <div className="mb-4">
                <p className="mb-1 text-12 font-medium text-ink-soft">Best prompt variant</p>
                <pre className="max-h-48 overflow-auto rounded-control border border-line bg-paper p-3 font-mono text-12 text-ink">
                  {best.prompt_variant}
                </pre>
                <div className="mt-2 flex flex-wrap gap-2">
                  <span className="text-12 text-ink-soft">
                    temp={String(best.params["temperature"] ?? "—")}
                  </span>
                  <span className="text-12 text-ink-soft">format={best.format}</span>
                  <span className="text-12 text-ink-soft">
                    source={String(best.params["source"] ?? "—")}
                  </span>
                </div>
              </div>
            )}

            {candidates.length > 0 && (
              <>
                <p className="mb-2 text-12 font-medium text-ink-soft">
                  All {candidates.length} attempts
                </p>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Source</TableHead>
                      <TableHead>Target model</TableHead>
                      <TableHead>Format</TableHead>
                      <TableHead>Temp</TableHead>
                      <TableHead>Det.</TableHead>
                      <TableHead>Judge</TableHead>
                      <TableHead>Embed</TableHead>
                      <TableHead>Final</TableHead>
                      <TableHead>Cost</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {candidates.map((c) => {
                      const isBest = best?.id === c.id;
                      return (
                        <TableRow key={c.id} className={isBest ? "bg-parity-pass/5" : ""}>
                          <TableCell className="text-12">
                            {isBest && (
                              <span className="mr-1 text-parity-pass">★</span>
                            )}
                            {String(c.params["source"] ?? "—")}
                          </TableCell>
                          <TableCell className="font-mono text-12">{c.target_model}</TableCell>
                          <TableCell className="text-12">{c.format}</TableCell>
                          <TableCell className="font-mono text-12 tabular-nums">
                            {String(c.params["temperature"] ?? "—")}
                          </TableCell>
                          <TableCell className="font-mono text-12 tabular-nums">
                            {c.scores["deterministic"] != null
                              ? `${Math.round(c.scores["deterministic"]! * 100)}%`
                              : "—"}
                          </TableCell>
                          <TableCell className="font-mono text-12 tabular-nums">
                            {c.scores["judge"] != null
                              ? `${Math.round(c.scores["judge"]! * 100)}%`
                              : "—"}
                          </TableCell>
                          <TableCell className="font-mono text-12 tabular-nums">
                            {c.scores["embedding_sim"] != null
                              ? `${Math.round(c.scores["embedding_sim"]! * 100)}%`
                              : "—"}
                          </TableCell>
                          <TableCell className="font-mono text-12 tabular-nums font-medium">
                            {c.scores["final"] != null
                              ? `${Math.round(c.scores["final"]! * 100)}%`
                              : "—"}
                          </TableCell>
                          <TableCell className="font-mono text-12 tabular-nums text-ink-soft">
                            {fmt(c.cost)}
                          </TableCell>
                        </TableRow>
                      );
                    })}
                  </TableBody>
                </Table>
              </>
            )}

            {candidates.length === 0 && (
              <p className="text-13 text-ink-soft">No attempts recorded for this stage.</p>
            )}
          </TableCell>
        </TableRow>
      )}
    </>
  );
}

export default function MigrationDetail() {
  const { pipelineId, migrationId } = useParams({
    from: "/pipelines/$pipelineId/migrations/$migrationId",
  });
  const pid = Number(pipelineId);
  const mid = Number(migrationId);

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["migration-results", pid, mid],
    queryFn: () => getMigrationResults(pid, mid),
  });

  const migration = data?.migration;
  const totalAttempts = data?.all_candidates.length ?? 0;

  // Group all_candidates by stage_id for the expanded rows.
  const candidatesByStage: Record<number, CandidateOut[]> = {};
  for (const c of data?.all_candidates ?? []) {
    (candidatesByStage[c.stage_id] ??= []).push(c);
  }

  return (
    <AppShell>
      <div className="p-8">
        <Link
          to="/pipelines/$pipelineId"
          params={{ pipelineId }}
          className="text-13 text-ink-soft hover:text-ink"
        >
          ← Pipeline canvas
        </Link>

        <div className="mt-2 flex items-center gap-3">
          <h1 className="font-display text-28 font-semibold leading-display text-ink">
            Migration #{mid}
          </h1>
          {migration && (
            <Badge variant={STATUS_VARIANTS[migration.status] ?? "outline"}>
              {STATUS_LABELS[migration.status] ?? migration.status}
            </Badge>
          )}
        </div>

        {isLoading && (
          <p className="mt-8 text-14 text-ink-soft" role="status">
            Loading results…
          </p>
        )}

        {isError && (
          <p className="mt-8 text-14 text-parity-fail" role="alert">
            {error instanceof Error ? error.message : "Couldn't load migration results."}
          </p>
        )}

        {data && migration && (
          <>
            {/* Summary cards */}
            <div className="mt-6 grid grid-cols-2 gap-4 sm:grid-cols-4">
              <Card>
                <CardContent className="p-5">
                  <p className="text-12 text-ink-soft">Total spend</p>
                  <p className="mt-1 font-mono text-20 font-semibold tabular-nums text-ink">
                    {migration.total_cost_usd != null
                      ? fmt(migration.total_cost_usd, 4)
                      : "—"}
                  </p>
                </CardContent>
              </Card>
              <Card>
                <CardContent className="p-5">
                  <p className="text-12 text-ink-soft">Budget</p>
                  <p className="mt-1 font-mono text-20 font-semibold tabular-nums text-ink">
                    {fmt(migration.budget, 2)}
                  </p>
                </CardContent>
              </Card>
              <Card>
                <CardContent className="p-5">
                  <p className="text-12 text-ink-soft">Parity threshold</p>
                  <p className="mt-1 font-mono text-20 font-semibold tabular-nums text-ink">
                    {Math.round(migration.parity_threshold * 100)}%
                  </p>
                </CardContent>
              </Card>
              <Card>
                <CardContent className="p-5">
                  <p className="text-12 text-ink-soft">Total attempts</p>
                  <p className="mt-1 font-mono text-20 font-semibold tabular-nums text-ink">
                    {totalAttempts}
                  </p>
                </CardContent>
              </Card>
            </div>

            {migration.stop_reason && (
              <p className="mt-4 text-13 text-ink-soft">
                Stop reason: <span className="text-ink">{migration.stop_reason}</span>
              </p>
            )}

            {/* Stage results */}
            <h2 className="mt-8 mb-3 font-display text-18 font-semibold text-ink">
              Stage results
            </h2>
            <p className="mb-4 text-13 text-ink-soft">
              Click a row to see the best prompt variant and all attempts for that stage.
            </p>

            {data.stage_summaries.length === 0 ? (
              <Card>
                <CardContent className="p-8 text-center text-14 text-ink-soft">
                  No stage results yet — the migration may not have run yet.
                </CardContent>
              </Card>
            ) : (
              <Card>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="w-6" />
                      <TableHead>Stage</TableHead>
                      <TableHead>Original model</TableHead>
                      <TableHead>Best target model</TableHead>
                      <TableHead>Score</TableHead>
                      <TableHead>Cost</TableHead>
                      <TableHead>Attempts</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {data.stage_summaries.map((summary) => (
                      <StageRow
                        key={summary.stage_id}
                        summary={summary}
                        parity_threshold={migration.parity_threshold}
                        candidates={candidatesByStage[summary.stage_id] ?? []}
                      />
                    ))}
                  </TableBody>
                </Table>
              </Card>
            )}
          </>
        )}
      </div>
    </AppShell>
  );
}
