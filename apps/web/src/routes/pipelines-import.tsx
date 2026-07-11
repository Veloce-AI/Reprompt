import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, getPipelineDag, importPipeline, type ImportResult } from "@/lib/api";
import { AppShell } from "@/components/app-shell";
import { Dropzone } from "@/components/dropzone";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { useImportStore } from "@/store/import-store";

type WizardStep = "upload" | "validate" | "preview";

const STEPS: { id: WizardStep; label: string }[] = [
  { id: "upload", label: "Upload traces" },
  { id: "validate", label: "Validation report" },
  { id: "preview", label: "DAG preview" },
];

export default function PipelinesImport() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const pendingFile = useImportStore((s) => s.pendingFile);
  const clearPendingFile = useImportStore((s) => s.clearPendingFile);

  const [step, setStep] = useState<WizardStep>("upload");
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [result, setResult] = useState<ImportResult | null>(null);

  const importMutation = useMutation({
    mutationFn: importPipeline,
    onSuccess: (data) => {
      setResult(data);
      queryClient.invalidateQueries({ queryKey: ["pipelines"] });
      // Deliberately stay on the "validate" step here rather than
      // auto-advancing - the user should get to actually read the
      // validation report (per the product spec) before moving on, not
      // have it flash past. They click through via the button below.
    },
  });

  const dagQuery = useQuery({
    queryKey: ["pipeline-dag", result?.pipeline_id],
    queryFn: () => getPipelineDag(result!.pipeline_id),
    enabled: step === "preview" && result !== null,
  });

  // A file dropped on the Pipelines home empty state arrives here already
  // selected - skip straight to validating it instead of asking again.
  //
  // Guarded with a ref, not just `!selectedFile`: React 18 StrictMode
  // double-invokes effects in dev using the *same* render's closure (no
  // re-render happens between the two invocations), so a state-based
  // guard alone doesn't see its own update in time and this would fire
  // importMutation.mutate() twice, double-importing the pipeline.
  const importStartedRef = useRef(false);
  useEffect(() => {
    if (pendingFile && !importStartedRef.current) {
      importStartedRef.current = true;
      setSelectedFile(pendingFile);
      clearPendingFile();
      setStep("validate");
      importMutation.mutate(pendingFile);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingFile]);

  function handleFileSelected(file: File) {
    setSelectedFile(file);
    setStep("validate");
    importMutation.mutate(file);
  }

  function retry() {
    importMutation.reset();
    setSelectedFile(null);
    setResult(null);
    setStep("upload");
  }

  return (
    <AppShell>
    <div className="p-8">
      <h1 className="font-display text-40 font-semibold leading-display text-ink">
        Import pipeline
      </h1>

      <ol className="my-6 flex gap-6" aria-label="Import steps">
        {STEPS.map((s, index) => {
          const isActive = s.id === step;
          const isDone = STEPS.findIndex((x) => x.id === step) > index;
          return (
            <li
              key={s.id}
              className={
                "flex items-center gap-2 text-13 " +
                (isActive
                  ? "font-medium text-ink"
                  : isDone
                    ? "text-parity-pass"
                    : "text-ink-soft")
              }
            >
              <span
                className={
                  "flex h-5 w-5 items-center justify-center rounded-full text-12 font-mono " +
                  (isActive
                    ? "bg-beam text-paper"
                    : isDone
                      ? "bg-parity-pass text-paper"
                      : "border border-line text-ink-soft")
                }
              >
                {index + 1}
              </span>
              {s.label}
            </li>
          );
        })}
      </ol>

      {step === "upload" && (
        <Card>
          <CardContent className="p-8">
            <Dropzone onFileSelected={handleFileSelected} className="w-full" />
          </CardContent>
        </Card>
      )}

      {step === "validate" && (
        <Card>
          <CardContent className="p-8">
            {importMutation.isPending && (
              <p className="text-14 text-ink-soft" role="status">
                Validating {selectedFile?.name}…
              </p>
            )}

            {importMutation.isError && (
              <div>
                <p className="mb-3 text-14 font-medium text-parity-fail">
                  Trace file failed validation
                </p>
                <pre className="mb-4 whitespace-pre-wrap rounded-control bg-beam-soft p-4 font-mono text-12 text-ink">
                  {importMutation.error instanceof ApiError
                    ? importMutation.error.message
                    : "Unknown error"}
                </pre>
                <Button variant="secondary" onClick={retry}>
                  Choose a different file
                </Button>
              </div>
            )}

            {importMutation.isSuccess && (
              <div>
                <p className="mb-4 text-14 text-parity-pass">
                  {result?.name} validated - {result?.stage_count} stages,{" "}
                  {result?.trace_count} traces.
                </p>
                <Button variant="primary" onClick={() => setStep("preview")}>
                  Continue to DAG preview
                </Button>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {step === "preview" && result && (
        <Card>
          <CardContent className="p-8">
            <p className="mb-4 text-14 text-ink">
              <span className="font-medium">{result.name}</span> imported
              successfully.
            </p>

            {dagQuery.isLoading && (
              <p className="text-14 text-ink-soft" role="status">
                Loading DAG preview…
              </p>
            )}

            {dagQuery.data && (
              <div className="mb-6 space-y-2 font-mono text-13 text-ink-soft">
                {dagQuery.data.layers.map((layer, index) => (
                  <div key={index}>
                    Layer {index}:{" "}
                    {layer.stage_ids
                      .map((id) => dagQuery.data.stages[String(id)]?.name)
                      .join(", ")}
                  </div>
                ))}
              </div>
            )}

            <div className="flex gap-3">
              <Button
                variant="primary"
                onClick={() =>
                  navigate({
                    to: "/pipelines/$pipelineId",
                    params: { pipelineId: String(result.pipeline_id) },
                  })
                }
              >
                View pipeline canvas
              </Button>
              <Link to="/">
                <Button variant="secondary">Back to pipelines</Button>
              </Link>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
    </AppShell>
  );
}
