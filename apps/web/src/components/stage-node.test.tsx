import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { ReactFlowProvider } from "@xyflow/react";
import { StageNode } from "./stage-node";
import type { StageInfo, StagePhase, StageRunState } from "@/lib/api";
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
    trace_count: 0,
    total_cost_usd: null,
    ...overrides,
  };
}

// StageNode is an @xyflow/react NodeProps component - it needs the handful
// of node-level props (id, selected, dragging, etc.) that ReactFlow injects
// at render time, plus a ReactFlowProvider ancestor for the Handle
// components to attach to. Rather than the full canvas + DAG data flow that
// pipeline-detail.tsx sets up, build the minimal NodeProps this component
// actually reads (data) and construct the rest.
function renderStageNode(stage: StageInfo, runState?: StageRunState, substep?: StagePhase | null) {
  const props = {
    id: "1",
    data: { stage, runState, substep },
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

  it("renders no state dot and a neutral border when runState is omitted (static canvas)", () => {
    const { container } = renderStageNode(baseStage());

    // ParityBeam's own no-score indicator is also role="img" — scope to the
    // stage-state dot specifically via its aria-label prefix.
    expect(screen.queryByLabelText(/^Stage /)).not.toBeInTheDocument();
    expect(container.querySelector(".border-line")).toBeInTheDocument();
  });

  it("pulses the beam-colored dot and border for a running stage", () => {
    renderStageNode(baseStage(), "running");

    const dot = screen.getByRole("img", { name: "Stage running" });
    expect(dot.className).toContain("bg-beam");
    expect(dot.className).toContain("animate-pulse");
  });

  it("shows a success dot/border for a done stage", () => {
    renderStageNode(baseStage(), "done");

    const dot = screen.getByRole("img", { name: "Stage done" });
    expect(dot.className).toContain("bg-parity-pass");
  });

  it("shows an error dot/border for a failed stage", () => {
    renderStageNode(baseStage(), "failed");

    const dot = screen.getByRole("img", { name: "Stage failed" });
    expect(dot.className).toContain("bg-parity-fail");
  });

  it("shows a human-readable sub-step label under the pulsing dot for a running stage", () => {
    renderStageNode(baseStage(), "running", "critiquing");

    expect(screen.getByText("Running — critiquing weakest candidates")).toBeInTheDocument();
  });

  it("maps every StagePhase to a human-readable label, never the raw enum value", () => {
    const phases: Record<StagePhase, string> = {
      mutating: "generating prompt variants",
      cheap_scoring: "ranking candidates",
      critiquing: "critiquing weakest candidates",
      refining: "refining prompt",
      sweeping: "running parameter sweep",
      scoring: "scoring candidates",
    };

    for (const [phase, label] of Object.entries(phases) as [StagePhase, string][]) {
      const { unmount } = renderStageNode(baseStage(), "running", phase);
      expect(screen.getByText(`Running — ${label}`)).toBeInTheDocument();
      unmount();
    }
  });

  it("does not show a sub-step label when the stage isn't running", () => {
    renderStageNode(baseStage(), "done", "scoring");

    expect(screen.queryByText(/^Running —/)).not.toBeInTheDocument();
  });

  it("does not show a sub-step label when running but no substep is known yet", () => {
    renderStageNode(baseStage(), "running");

    expect(screen.queryByText(/^Running —/)).not.toBeInTheDocument();
  });
});
