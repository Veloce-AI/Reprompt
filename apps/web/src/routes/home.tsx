import { Link, useNavigate } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { listPipelines } from "@/lib/api";
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
  const setPendingFile = useImportStore((s) => s.setPendingFile);
  const { data: pipelines, isLoading, isError, error } = useQuery({
    queryKey: ["pipelines"],
    queryFn: listPipelines,
  });

  function startImportWith(file: File) {
    setPendingFile(file);
    navigate({ to: "/pipelines/import" });
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
              </TableRow>
            ))}
          </TableBody>
        </Table>
        )}
      </div>
    </AppShell>
  );
}
