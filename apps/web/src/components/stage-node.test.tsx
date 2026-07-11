import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { ReactFlowProvider } from "@xyflow/react";
import { StageNode } from "./stage-node";
import type { StageInfo } from "@/lib/api";
import type { NodeProps } from "@xyflow/react";
import type { StageFlowNode } from "./stage-node";

function baseStage(overrides: Partial<StageInfo> = {}): StageInfo {
  return {
    id: 1,
    name: "Extract entities",
    model: "gpt-4o-mini-2024-07-18",
    avg_tokens_in: 120,
    avg_tokens_out: 45,
    avg_latency_ms: 812,
    ...overrides,
  };
}

// StageNode is an @xyflow/react NodeProps component - it needs the handful
// of node-level props (id, selected, dragging, etc.) that ReactFlow injects
// at render time, plus a ReactFlowProvider ancestor for the Handle
// components to attach to. Rather than the full canvas + DAG data flow that
// pipeline-detail.tsx sets up, build the minimal NodeProps this component
// actually reads (data) and construct the rest.
function renderStageNode(stage: StageInfo) {
  const props = {
    id: "1",
    data: { stage },
    type: "stage",
    selected: false,
    isConnectable: true,
    zIndex: 0,
    dragging: false,
    positionAbsoluteX: 0,
    positionAbsoluteY: 0,
  } as unknown as NodeProps<StageFlowNode>;

  return render(
    <ReactFlowProvider>
      <StageNode {...props} />
    </ReactFlowProvider>
  );
}

describe("StageNode", () => {
  it("shows the tokens and latency line when both are present", () => {
    renderStageNode(baseStage());

    expect(screen.getByText("120→45 tok · 812ms")).toBeInTheDocument();
  });

  it("shows 'tokens not tracked' instead of a fake 0->0 when token averages are null", () => {
    renderStageNode(baseStage({ avg_tokens_in: null, avg_tokens_out: null }));

    expect(screen.getByText("tokens not tracked · 812ms")).toBeInTheDocument();
    expect(screen.queryByText(/0→0/)).not.toBeInTheDocument();
  });

  it("shows 'latency not tracked' when latency average is null", () => {
    renderStageNode(baseStage({ avg_latency_ms: null }));

    expect(screen.getByText("120→45 tok · latency not tracked")).toBeInTheDocument();
  });

  it("shows both as not tracked when every stat is null", () => {
    renderStageNode(
      baseStage({ avg_tokens_in: null, avg_tokens_out: null, avg_latency_ms: null })
    );

    expect(screen.getByText("tokens not tracked · latency not tracked")).toBeInTheDocument();
  });

  it("renders the stats line in the same muted, compact style whether or not stats are present", () => {
    const { container: withStats } = renderStageNode(baseStage());
    const withStatsEl = screen.getByText("120→45 tok · 812ms");
    expect(withStatsEl.className).toContain("text-ink-soft");
    expect(withStatsEl.className).toContain("text-12");

    withStats.remove();

    renderStageNode(baseStage({ avg_tokens_in: null, avg_tokens_out: null, avg_latency_ms: null }));
    const withoutStatsEl = screen.getByText("tokens not tracked · latency not tracked");
    expect(withoutStatsEl.className).toContain("text-ink-soft");
    expect(withoutStatsEl.className).toContain("text-12");
  });

  it("still renders the stage name and model badge", () => {
    renderStageNode(baseStage({ name: "Summarize", model: "claude-3-5-sonnet-20241022" }));

    expect(screen.getByText("Summarize")).toBeInTheDocument();
    expect(screen.getByText("claude-3-5-sonnet-20241022")).toBeInTheDocument();
  });
});
