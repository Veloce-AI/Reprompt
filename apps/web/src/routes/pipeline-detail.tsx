import { Link, useParams } from "@tanstack/react-router";
import { AppShell } from "@/components/app-shell";
import { PipelineCanvas } from "@/components/pipeline-canvas";
import { Button } from "@/components/ui/button";

export default function PipelineDetail() {
  const { pipelineId } = useParams({ from: "/pipelines/$pipelineId" });

  return (
    <AppShell>
    <div className="flex h-full min-h-[calc(100vh-1px)] flex-col">
      <div className="flex items-center justify-between border-b border-line px-8 py-4">
        <div>
          <Link
            to="/"
            className="text-13 text-ink-soft hover:text-ink"
          >
            ← Pipelines
          </Link>
          <h1 className="font-display text-28 font-semibold leading-display text-ink">
            Pipeline canvas
          </h1>
        </div>
        <div className="flex gap-3">
          <Link to="/pipelines/$pipelineId/rubrics" params={{ pipelineId }}>
            <Button variant="secondary">Review rubrics</Button>
          </Link>
          <Link to="/pipelines/$pipelineId/migrations/new" params={{ pipelineId }}>
            <Button variant="primary">New migration</Button>
          </Link>
        </div>
      </div>

      <PipelineCanvas pipelineId={Number(pipelineId)} />
    </div>
    </AppShell>
  );
}
