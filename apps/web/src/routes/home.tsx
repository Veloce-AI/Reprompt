import type { MouseEvent } from "react";
import { Link, useNavigate } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Trash2 } from "lucide-react";
import { ApiError, deletePipeline, listPipelines, type PipelineSummary } from "@/lib/api";
import { AppShell } from "@/components/app-shell";
import { Dropzone } from "@/components/dropzone";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ParityBeam } from "@/components/parity-beam";
import { useImportStore } from "@/store/import-store";

export default function Home() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const setPendingFile = useImportStore((s) => s.setPendingFile);
  const { data: pipelines, isLoading, isError, error } = useQuery({
    queryKey: ["pipelines"],
    queryFn: listPipelines,
  });

  const deleteMutation = useMutation({
    mutationFn: (pipelineId: number) => deletePipeline(pipelineId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["pipelines"] });
    },
  });

  function startImportWith(file: File) {
    setPendingFile(file);
    navigate({ to: "/pipelines/import" });
  }

  // Destructive + irreversible (hard delete, cascades to every stage,
  // rubric, run, and migration underneath it) - requires an explicit
  // confirm step, not a bare click. window.confirm is deliberate here:
  // no modal/dialog primitive exists in the codebase yet (see
  // components/ui/), and adding one just for this would be more surface
  // area than a destructive-action gate needs.
  function handleDeleteClick(event: MouseEvent, pipeline: PipelineSummary) {
    event.stopPropagation();
    if (deleteMutation.isPending) return;
    const confirmed = window.confirm(
      `Delete "${pipeline.name}"? This permanently removes its stages, rubrics, runs, and migrations. This can't be undone.`
    );
    if (confirmed) {
      deleteMutation.mutate(pipeline.id);
    }
  }

  return (
    <AppShell>
      <div className="p-8">
        <div className="mb-8 flex items-center justify-between">
          <div>
            <h1 className="font-display text-40 font-semibold leading-display text-ink">
              Pipelines
            </h1>
            <p className="mt-1 text-14 text-ink-soft">
              Import a pipeline's execution traces to start a migration.
            </p>
          </div>
          {pipelines && pipelines.length > 0 && (
            <Link to="/pipelines/import">
              <Button variant="primary">Import pipeline</Button>
            </Link>
          )}
        </div>

        {isLoading && (
          <p className="text-14 text-ink-soft" role="status">
            Loading pipelines…
          </p>
        )}

        {isError && (
          <p className="text-14 text-parity-fail" role="alert">
            Couldn't load pipelines: {error instanceof Error ? error.message : "unknown error"}
          </p>
        )}

        {deleteMutation.isError && (
          <p className="mb-4 text-14 text-parity-fail" role="alert">
            Couldn't delete pipeline:{" "}
            {deleteMutation.error instanceof ApiError
              ? deleteMutation.error.message
              : "unknown error"}
          </p>
        )}

        {pipelines && pipelines.length === 0 && (
          <Card className="border-dashed">
            <CardContent className="flex flex-col items-center gap-6 p-16">
              <div className="text-center">
                <h2 className="font-display text-28 font-semibold leading-display text-ink">
                  Import your first pipeline
                </h2>
                <p className="mt-2 text-14 text-ink-soft">
                  Upload a trace file to see its stages, models, and benchmark
                  queries. See the{" "}
                  <Link to="/schema" className="text-beam underline underline-offset-2">
                    trace format docs
                  </Link>{" "}
                  for the file shape.
                </p>
              </div>
              <Dropzone
                onFileSelected={startImportWith}
                label="Drop your trace file here, or click to browse"
                className="w-full max-w-xl"
              />
            </CardContent>
          </Card>
        )}

        {pipelines && pipelines.length > 0 && (
          <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead>Stages</TableHead>
              <TableHead>Models</TableHead>
              <TableHead>Benchmark queries</TableHead>
              <TableHead>Last migration parity</TableHead>
              <TableHead className="w-12" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {pipelines.map((pipeline) => (
              <TableRow
                key={pipeline.id}
                className="cursor-pointer"
                onClick={() =>
                  navigate({
                    to: "/pipelines/$pipelineId",
                    params: { pipelineId: String(pipeline.id) },
                    search: { tab: "canvas" },
                  })
                }
              >
                <TableCell className="font-medium text-ink">
                  {pipeline.name}
                </TableCell>
                <TableCell className="font-mono tabular-nums">
                  {pipeline.stage_count}
                </TableCell>
                <TableCell>
                  <div className="flex flex-wrap gap-1">
                    {pipeline.models_used.map((model) => (
                      <Badge key={model} variant="neutral">
                        {model}
                      </Badge>
                    ))}
                  </div>
                </TableCell>
                <TableCell className="font-mono tabular-nums">
                  {pipeline.benchmark_query_count}
                </TableCell>
                <TableCell className="w-40">
                  {/* No migration has run yet in M1 - ParityBeam's own
                      no-score state communicates that, same component
                      that will show a real score once M4 exists. */}
                  <ParityBeam />
                </TableCell>
                <TableCell>
                  <Button
                    variant="ghost"
                    size="icon"
                    aria-label={`Delete ${pipeline.name}`}
                    disabled={deleteMutation.isPending}
                    onClick={(event) => handleDeleteClick(event, pipeline)}
                  >
                    <Trash2 className="h-4 w-4 text-parity-fail" />
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
        )}
      </div>
    </AppShell>
  );
}
