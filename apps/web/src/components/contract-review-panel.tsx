import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  type AssertionOut,
  type DagResponse,
  approveAssertion,
  getPipelineDag,
  listAssertions,
  mineContract,
  retireAssertion,
} from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { InfoTooltip } from "@/components/ui/info-tooltip";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

function statusVariant(status: AssertionOut["status"]): "pass" | "near" | "neutral" | "outline" {
  if (status === "approved") return "pass";
  if (status === "retired") return "neutral";
  return "outline";
}

function StageAssertions({
  pipelineId,
  stageId,
  stageName,
}: {
  pipelineId: number;
  stageId: number;
  stageName: string;
}) {
  const qc = useQueryClient();
  const [mining, setMining] = useState(false);
  const [mineError, setMineError] = useState<string | null>(null);

  const assertionsQuery = useQuery({
    queryKey: ["assertions", pipelineId, stageId],
    queryFn: () => listAssertions(pipelineId, stageId),
  });

  const approveMut = useMutation({
    mutationFn: (aid: number) => approveAssertion(pipelineId, stageId, aid),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["assertions", pipelineId, stageId] }),
  });

  const retireMut = useMutation({
    mutationFn: (aid: number) => retireAssertion(pipelineId, stageId, aid),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["assertions", pipelineId, stageId] }),
  });

  const handleMine = async () => {
    setMining(true);
    setMineError(null);
    try {
      await mineContract(pipelineId, stageId);
      qc.invalidateQueries({ queryKey: ["assertions", pipelineId, stageId] });
    } catch (e) {
      setMineError(e instanceof Error ? e.message : "Mining failed");
    } finally {
      setMining(false);
    }
  };

  const assertions = assertionsQuery.data ?? [];

  return (
    <div className="mb-8">
      <div className="mb-2 flex items-center justify-between">
        <h3 className="font-medium text-14 text-ink">{stageName}</h3>
        <Button variant="secondary" size="sm" onClick={handleMine} disabled={mining}>
          {mining ? "Mining…" : "Mine contract"}
        </Button>
      </div>

      {mineError && (
        <p className="mb-2 text-13 text-parity-fail" role="alert">
          {mineError}
        </p>
      )}

      {assertionsQuery.isLoading && (
        <p className="text-13 text-ink-soft">Loading…</p>
      )}

      {!assertionsQuery.isLoading && assertions.length === 0 && (
        <p className="text-13 text-ink-soft">
          No assertions yet — click "Mine contract" to extract invariants from existing traces.
        </p>
      )}

      {assertions.length > 0 && (
        <Card>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Kind</TableHead>
                <TableHead>Description</TableHead>
                <TableHead>Confidence</TableHead>
                <TableHead>Status</TableHead>
                <TableHead />
              </TableRow>
            </TableHeader>
            <TableBody>
              {assertions.map((a) => (
                <TableRow key={a.id}>
                  <TableCell className="align-top font-mono text-12">{a.kind}</TableCell>
                  <TableCell className="align-top text-13 text-ink max-w-xs">
                    {a.description || JSON.stringify(a.spec)}
                    {a.noise_floor != null && (
                      <span className="ml-2 text-12 text-ink-muted">
                        noise {Math.round(a.noise_floor * 100)}%
                      </span>
                    )}
                  </TableCell>
                  <TableCell className="align-top font-mono text-12">
                    {a.confidence != null ? `${Math.round(a.confidence * 100)}%` : "—"}
                  </TableCell>
                  <TableCell className="align-top">
                    <Badge variant={statusVariant(a.status)}>{a.status}</Badge>
                  </TableCell>
                  <TableCell className="align-top">
                    <div className="flex gap-2">
                      {a.status !== "approved" && (
                        <Button
                          variant="secondary"
                          size="sm"
                          disabled={approveMut.isPending}
                          onClick={() => approveMut.mutate(a.id)}
                        >
                          Approve
                        </Button>
                      )}
                      {a.status !== "retired" && (
                        <Button
                          variant="secondary"
                          size="sm"
                          disabled={retireMut.isPending}
                          onClick={() => retireMut.mutate(a.id)}
                        >
                          Retire
                        </Button>
                      )}
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          {assertions[0]?.entropy != null && (
            <div className="border-t border-line px-4 py-2 text-12 text-ink-soft">
              Semantic entropy: {assertions[0].entropy.toFixed(3)} nats
            </div>
          )}
        </Card>
      )}
    </div>
  );
}

export function ContractReviewPanel({ pipelineId }: { pipelineId: number }) {
  const dagQuery = useQuery<DagResponse>({
    queryKey: ["pipeline-dag", pipelineId],
    queryFn: () => getPipelineDag(pipelineId),
  });

  // Real array (not the raw `Record<string, StageInfo>`) so `.length` is an
  // actual number — `dagQuery.data?.stages ?? []`'s `Record` branch has no
  // runtime `.length` (TS only thought it did via the index signature),
  // which meant a genuinely empty pipeline never hit the `=== 0` check
  // below and rendered nothing instead of the "No stages found" message.
  const stages = Object.values(dagQuery.data?.stages ?? {});

  return (
    <div>
      <div className="mb-2 flex items-center gap-1.5">
        <h2 className="font-display text-22 font-semibold text-ink">Contract Mining</h2>
        <InfoTooltip label="What is contract mining?">
          Looks at real outputs from this stage and finds what never changes across them (e.g.
          "the flag is always low/medium/high, always cites a number"). Those become an
          executable contract a migrated prompt must satisfy — instead of just matching your
          original wording.
        </InfoTooltip>
      </div>

      {dagQuery.isLoading && (
        <p className="text-14 text-ink-soft" role="status">Loading stages…</p>
      )}

      {!dagQuery.isLoading && stages.length === 0 && (
        <Card>
          <CardContent className="p-8 text-center text-14 text-ink-soft">
            No stages found — import a pipeline first.
          </CardContent>
        </Card>
      )}

      {!dagQuery.isLoading && stages.length > 0 && (
        <>
          <p className="mb-6 text-13 text-ink-soft">
            Mine contracts from existing traces to extract invariants (required keys, enum
            values, regex patterns) that the stage always produces. Approve invariants to
            promote them to executable assertions used in Phase 8 validation.
          </p>
          {stages.map((stage) => (
            <StageAssertions
              key={stage.id}
              pipelineId={pipelineId}
              stageId={stage.id}
              stageName={stage.name}
            />
          ))}
        </>
      )}
    </div>
  );
}
