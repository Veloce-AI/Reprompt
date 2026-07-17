import { Link, useParams } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { getMigrationResults, getMigrationStatus, type StageResultOut } from "@/lib/api";
import { AppShell } from "@/components/app-shell";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ParityBeam, parityStatus } from "@/components/parity-beam";
import { diffWords } from "@/lib/text-diff";
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

function DiffPrompt({ original, winning }: { original: string; winning: string }) {
  const ops = diffWords(original, winning);
  return (
    <pre className="max-h-40 overflow-auto rounded border border-line bg-paper p-2 font-mono text-11 leading-normal text-ink whitespace-pre-wrap">
      {ops.map((op, i) => {
        if (op.type === "delete")
          return <span key={i} className="bg-parity-fail/10 text-parity-fail line-through">{op.text}</span>;
        if (op.type === "insert")
          return <span key={i} className="bg-parity-pass/10 text-parity-pass">{op.text}</span>;
        return <span key={i}>{op.text}</span>;
      })}
    </pre>
  );
}

function StageResultRow({
  result,
  parityThreshold,
}: {
  result: StageResultOut;
  parityThreshold: number;
}) {
  const pct = Math.round(result.score * 100);
  const status = parityStatus(pct, parityThreshold * 100);

  return (
    <TableRow>
      <TableCell className="align-top font-medium text-ink">{result.stage_name}</TableCell>
      <TableCell className="align-top">
        <DiffPrompt original={result.original_prompt} winning={result.winning_prompt} />
      </TableCell>
      <TableCell className="align-top font-mono text-12 text-ink-soft">
        {result.winning_model}
      </TableCell>
      <TableCell className="align-top w-40">
        <div className="flex items-center gap-2">
          <ParityBeam score={pct} passThreshold={parityThreshold * 100} className="w-20" />
          <Badge variant={status}>{pct}%</Badge>
        </div>
      </TableCell>
    </TableRow>
  );
}

export default function MigrationDetail() {
  const { pipelineId, migrationId } = useParams({
    from: "/pipelines/$pipelineId/migrations/$migrationId",
  });
  const pid = Number(pipelineId);
  const mid = Number(migrationId);

  const statusQuery = useQuery({
    queryKey: ["migration-status", pid, mid],
    queryFn: () => getMigrationStatus(pid, mid),
  });

  const resultsQuery = useQuery({
    queryKey: ["migration-results", pid, mid],
    queryFn: () => getMigrationResults(pid, mid),
  });

  const migration = statusQuery.data;
  const results: StageResultOut[] = resultsQuery.data ?? [];

  return (
    <AppShell>
      <div className="p-8">
        <Link
          to="/pipelines/$pipelineId"
          params={{ pipelineId }}
          search={{ tab: "canvas" }}
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

        {(statusQuery.isLoading || resultsQuery.isLoading) && (
          <p className="mt-8 text-14 text-ink-soft" role="status">
            Loading results…
          </p>
        )}

        {(statusQuery.isError || resultsQuery.isError) && (
          <p className="mt-8 text-14 text-parity-fail" role="alert">
            {(() => {
              const err = statusQuery.error ?? resultsQuery.error;
              return err instanceof Error ? err.message : "Couldn't load migration results.";
            })()}
          </p>
        )}

        {migration && (
          <div className="mt-6 grid grid-cols-2 gap-4 sm:grid-cols-4">
            <Card>
              <CardContent className="p-5">
                <p className="text-12 text-ink-soft">Total spend</p>
                <p className="mt-1 font-mono text-20 font-semibold tabular-nums text-ink">
                  {migration.total_cost_usd != null
                    ? `$${migration.total_cost_usd.toFixed(4)}`
                    : "—"}
                </p>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="p-5">
                <p className="text-12 text-ink-soft">Budget</p>
                <p className="mt-1 font-mono text-20 font-semibold tabular-nums text-ink">
                  ${migration.budget.toFixed(2)}
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
                <p className="text-12 text-ink-soft">Stages optimized</p>
                <p className="mt-1 font-mono text-20 font-semibold tabular-nums text-ink">
                  {results.length}
                </p>
              </CardContent>
            </Card>
          </div>
        )}

        {migration?.stop_reason && (
          <p className="mt-4 text-13 text-ink-soft">
            Stop reason: <span className="text-ink">{migration.stop_reason}</span>
          </p>
        )}

        <h2 className="mt-8 mb-3 font-display text-18 font-semibold text-ink">
          Stage results
        </h2>
        <p className="mb-4 text-13 text-ink-soft">
          Winning prompt per stage — the best-scoring variant found across all target models.
        </p>

        {!resultsQuery.isLoading && results.length === 0 ? (
          <Card>
            <CardContent className="p-8 text-center text-14 text-ink-soft">
              No results yet — the migration may not have run yet.
            </CardContent>
          </Card>
        ) : (
          <Card>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Stage</TableHead>
                  <TableHead>Prompt diff (original → winning)</TableHead>
                  <TableHead>Model</TableHead>
                  <TableHead>Score</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {results.map((r) => (
                  <StageResultRow
                    key={r.stage_id}
                    result={r}
                    parityThreshold={migration?.parity_threshold ?? 0.95}
                  />
                ))}
              </TableBody>
            </Table>
          </Card>
        )}
      </div>
    </AppShell>
  );
}
