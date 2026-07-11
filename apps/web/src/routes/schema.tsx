import { useMutation } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { Download } from "lucide-react";
import { ApiError, getTraceFormatSchema } from "@/lib/api";
import { AppShell } from "@/components/app-shell";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

const EXAMPLE_TRACE_FILE = `{
  "schema_version": "1.1",
  "pipeline": {
    "id": "support-ticket-triage",
    "name": "Support ticket triage",
    "stages": [
      {
        "id": "extract",
        "name": "Extract ticket facts",
        "depends_on": [],
        "model": "gpt-4o-mini-2024-07-18",
        "prompt_template": "Extract the customer's issue as JSON:\\n\\n{{ticket_text}}"
      },
      {
        "id": "summarize",
        "name": "Summarize for agent handoff",
        "depends_on": ["extract"],
        "model": "claude-3-5-sonnet-20241022",
        "prompt_template": "Summarize this issue in one sentence:\\n\\n{{extract.output}}"
      }
    ]
  },
  "traces": [
    {
      // Trace 1: full accounting captured - tokens and latency present.
      "trace_id": "trace-001",
      "query": { "ticket_text": "My invoice #4471 charged me twice this month." },
      "records": [
        {
          "stage_id": "extract",
          "rendered_prompt": "Extract the customer's issue as JSON:\\n\\nMy invoice #4471 charged me twice this month.",
          "output": "{\\"issue_type\\": \\"billing\\", \\"invoice_id\\": \\"4471\\"}",
          "tokens": { "in": 42, "out": 28 },
          "latency_ms": 612.4
        },
        {
          "stage_id": "summarize",
          "rendered_prompt": "Summarize this issue in one sentence:\\n\\n{\\"issue_type\\": \\"billing\\", \\"invoice_id\\": \\"4471\\"}",
          "output": "Customer was double-charged on invoice #4471 and needs a refund.",
          "tokens": { "in": 58, "out": 17 },
          "latency_ms": 891.0
        }
      ]
    },
    {
      // Trace 2: no token/latency accounting - just as valid. Omit the
      // fields entirely rather than sending fake zeros.
      "trace_id": "trace-002",
      "query": { "ticket_text": "I can't reset my password, the link expired." },
      "records": [
        {
          "stage_id": "extract",
          "rendered_prompt": "Extract the customer's issue as JSON:\\n\\nI can't reset my password, the link expired.",
          "output": "{\\"issue_type\\": \\"account_access\\", \\"detail\\": \\"expired_reset_link\\"}"
        },
        {
          "stage_id": "summarize",
          "rendered_prompt": "Summarize this issue in one sentence:\\n\\n{\\"issue_type\\": \\"account_access\\"}",
          "output": "Customer's password reset link expired before they could use it."
        }
      ]
    }
  ]
}`;

interface FieldRow {
  field: string;
  belongsTo: string;
  required: boolean;
  notes: string;
}

const FIELD_ROWS: FieldRow[] = [
  { field: "id", belongsTo: "Pipeline", required: true, notes: "Unique pipeline identifier." },
  { field: "name", belongsTo: "Pipeline", required: true, notes: "Human-readable name." },
  { field: "stages", belongsTo: "Pipeline", required: true, notes: "The DAG's nodes - at least one." },
  { field: "id", belongsTo: "Stage", required: true, notes: "Unique within the pipeline, used as the join key for records." },
  { field: "name", belongsTo: "Stage", required: true, notes: "Human-readable stage name." },
  { field: "model", belongsTo: "Stage", required: true, notes: "LiteLLM-style model id, e.g. “gpt-4o-2024-08-06”." },
  { field: "prompt_template", belongsTo: "Stage", required: true, notes: "Prompt template with {{variable}} placeholders." },
  { field: "depends_on", belongsTo: "Stage", required: false, notes: "Upstream stage ids. Empty means a root stage." },
  { field: "system_prompt", belongsTo: "Stage", required: false, notes: "System prompt, kept separate from prompt_template." },
  { field: "params", belongsTo: "Stage", required: false, notes: "temperature, top_p, max_tokens, format_mode." },
  { field: "metadata", belongsTo: "Stage", required: false, notes: "Free-form product-specific extras." },
  { field: "trace_id", belongsTo: "Trace", required: true, notes: "Unique within the file." },
  { field: "query", belongsTo: "Trace", required: true, notes: "The original input to the pipeline for this query." },
  { field: "records", belongsTo: "Trace", required: true, notes: "One StageRecord per stage that executed - at least one." },
  { field: "metadata", belongsTo: "Trace", required: false, notes: "Free-form product-specific extras." },
  { field: "stage_id", belongsTo: "StageRecord", required: true, notes: "Must match a Stage.id in the pipeline." },
  { field: "rendered_prompt", belongsTo: "StageRecord", required: true, notes: "The exact prompt text sent to the model." },
  { field: "output", belongsTo: "StageRecord", required: true, notes: "The raw model output/completion text." },
  { field: "input", belongsTo: "StageRecord", required: false, notes: "Resolved input variables fed into the prompt template." },
  { field: "tokens", belongsTo: "StageRecord", required: false, notes: "{ in, out, thinking? } - omit if not captured." },
  { field: "latency_ms", belongsTo: "StageRecord", required: false, notes: "Wall-clock latency of the model call." },
  { field: "cost", belongsTo: "StageRecord", required: false, notes: "Actual $ cost of the call, if known." },
  { field: "documents", belongsTo: "StageRecord", required: false, notes: "Retrieved/supporting document text used by the call." },
  { field: "metadata", belongsTo: "StageRecord", required: false, notes: "Free-form product-specific extras." },
];

export default function SchemaReference() {
  const downloadMutation = useMutation({
    mutationFn: getTraceFormatSchema,
    onSuccess: (schema) => {
      const blob = new Blob([JSON.stringify(schema, null, 2)], {
        type: "application/json",
      });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = "trace-format.schema.json";
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);
    },
  });

  return (
    <AppShell>
    <div className="mx-auto max-w-[960px] p-8">
      <Link to="/" className="text-13 text-ink-soft hover:text-ink">
        ← Pipelines
      </Link>
      <h1 className="font-display text-40 font-semibold leading-display text-ink">
        Trace format
      </h1>
      <p className="mt-2 max-w-[640px] text-14 text-ink-soft">
        Refract ingests execution traces from any AI pipeline - however you
        built it, whatever models it calls. This page explains the shape
        Refract expects, so you can decide whether to write an exporter
        against it before you import anything.
      </p>

      <div className="mt-8 flex flex-col gap-6">
        <Card>
          <CardHeader>
            <CardTitle>The shape, in short</CardTitle>
            <CardDescription>
              A trace file is one JSON document with two top-level parts: the
              pipeline definition and the benchmark traces it produced.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <pre className="overflow-x-auto whitespace-pre rounded-control bg-beam-soft p-4 font-mono text-12 text-ink">
{`Pipeline                    the DAG definition
 └─ Stage[]                 nodes: model, prompt template, dependencies

Trace[]                     the benchmark set - one entry per query
 └─ StageRecord[]           one record per stage that executed for that query`}
            </pre>
            <p className="mt-4 text-13 text-ink-soft">
              A <span className="font-mono text-12 text-ink">Stage</span> declares how a node in the
              pipeline is called (model, prompt template, what it depends on).
              A{" "}
              <span className="font-mono text-12 text-ink">StageRecord</span> is
              one actual execution of a stage, captured while answering one
              benchmark query. Parallel branches aren&apos;t a separate
              construct - two stages that both list the same
              <span className="font-mono text-12 text-ink"> depends_on</span>{" "}
              entry (and don&apos;t depend on each other) run in parallel.
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Required vs optional fields</CardTitle>
            <CardDescription>
              At minimum, a trace needs a stage&apos;s name/model/prompt
              template, a trace&apos;s query, and each record&apos;s output.
              Everything else - token counts, latency, cost, retrieved
              documents, metadata - is optional and can be added
              incrementally as your exporter captures more.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Field</TableHead>
                  <TableHead>Belongs to</TableHead>
                  <TableHead>Required</TableHead>
                  <TableHead>Notes</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {FIELD_ROWS.map((row, index) => (
                  <TableRow key={`${row.belongsTo}.${row.field}-${index}`}>
                    <TableCell className="font-mono text-12 text-ink">{row.field}</TableCell>
                    <TableCell className="text-ink-soft">{row.belongsTo}</TableCell>
                    <TableCell>
                      <Badge variant={row.required ? "pass" : "outline"}>
                        {row.required ? "Required" : "Optional"}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-ink-soft">{row.notes}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Minimal example</CardTitle>
            <CardDescription>
              A two-stage pipeline with one trace that has full token/latency
              accounting and one that doesn&apos;t - both are valid.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <pre className="overflow-x-auto whitespace-pre rounded-control bg-beam-soft p-4 font-mono text-12 text-ink">
              {EXAMPLE_TRACE_FILE}
            </pre>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Raw JSON Schema</CardTitle>
            <CardDescription>
              Download the full JSON Schema document Refract validates trace
              files against, generated straight from the canonical Pydantic
              model - useful for generating types or wiring up validation in
              your own exporter.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Button
              variant="secondary"
              onClick={() => downloadMutation.mutate()}
              disabled={downloadMutation.isPending}
            >
              <Download className="h-4 w-4" />
              {downloadMutation.isPending ? "Fetching schema…" : "Download JSON schema"}
            </Button>
            {downloadMutation.isError && (
              <p className="mt-3 text-13 text-parity-fail" role="alert">
                {downloadMutation.error instanceof ApiError
                  ? downloadMutation.error.message
                  : "Couldn't fetch the schema. Check your connection and try again."}
              </p>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Writing an exporter</CardTitle>
            <CardDescription>
              For a copy-paste starting point that records traces in this
              format while your pipeline runs, see{" "}
              <code className="font-mono text-13 text-ink">
                docs/examples/trace_recorder.py
              </code>{" "}
              in the Refract repo.
            </CardDescription>
          </CardHeader>
        </Card>
      </div>
    </div>
    </AppShell>
  );
}
