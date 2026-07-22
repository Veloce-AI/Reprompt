import { useEffect, useMemo, useRef, useState } from "react";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { useVirtualizer } from "@tanstack/react-virtual";
import { getPipelineDag, listStageRecords, type StageRecordOut } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Select } from "@/components/ui/select";
import {
  DrawerRoot,
  DrawerContent,
  DrawerHeader,
  DrawerTitle,
  DrawerDescription,
  DrawerBody,
} from "@/components/ui/drawer";

const PAGE_SIZE = 50;
const ROW_HEIGHT = 56;

// Trace · Stage · Input · Rendered prompt · Output · Tok in · Tok out · Cost · Latency
const GRID_TEMPLATE =
  "minmax(70px,90px) minmax(100px,130px) minmax(180px,1.4fr) minmax(180px,1.4fr) minmax(180px,1.4fr) 76px 76px 84px 84px";

function truncate(text: string, max = 80): string {
  if (text.length <= max) return text;
  return `${text.slice(0, max - 1)}…`;
}

function stringifyInput(input: Record<string, unknown>): string {
  try {
    return JSON.stringify(input);
  } catch {
    return String(input);
  }
}

function formatCost(cost: number | null): string {
  return cost != null ? `$${cost.toFixed(4)}` : "—";
}

function formatLatency(latencyMs: number | null): string {
  return latencyMs != null ? `${Math.round(latencyMs)}ms` : "—";
}

export interface DataTableProps {
  pipelineId: number;
}

/**
 * Virtualized, cursor-paginated spreadsheet browser over every StageRecord
 * (input, rendered prompt, output) for a pipeline — the Data tab's real
 * content (see pipeline-workspace.tsx), replacing its former "Coming soon"
 * placeholder. Read-only: no edit/approve affordances live here, those stay
 * exclusive to the Rubrics tab.
 *
 * Stage filter only for now, deliberately — see DEV_TRACKER.md's Phase 3
 * entry: a Run filter/dropdown is a fast follow-on once the parallel
 * multi-run work (GET /pipelines/{id}/runs) lands, not a forgotten scope
 * item. No text search box either (out of scope, would need real indexing).
 */
export function DataTable({ pipelineId }: DataTableProps) {
  const [stageId, setStageId] = useState<number | null>(null);
  const [selectedRecord, setSelectedRecord] = useState<StageRecordOut | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Same query key the Canvas tab's PipelineCanvas uses for the DAG fetch
  // (pipeline-canvas.tsx) - reuses that cache entry instead of a second
  // network round-trip when both tabs have been visited in a session.
  const dagQuery = useQuery({
    queryKey: ["pipeline-dag", pipelineId],
    queryFn: () => getPipelineDag(pipelineId),
  });

  const stages = useMemo(
    () => (dagQuery.data ? Object.values(dagQuery.data.stages).sort((a, b) => a.id - b.id) : []),
    [dagQuery.data]
  );

  const recordsQuery = useInfiniteQuery({
    queryKey: ["stage-records", pipelineId, stageId],
    queryFn: ({ pageParam }) =>
      listStageRecords(pipelineId, { stageId, cursor: pageParam as number, limit: PAGE_SIZE }),
    initialPageParam: 0,
    getNextPageParam: (lastPage) => lastPage.next_cursor,
  });

  const records = useMemo(
    () => recordsQuery.data?.pages.flatMap((page) => page.records) ?? [],
    [recordsQuery.data]
  );

  const rowVirtualizer = useVirtualizer({
    count: records.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => ROW_HEIGHT,
    overscan: 12,
  });

  const virtualRows = rowVirtualizer.getVirtualItems();
  const lastVirtualRow = virtualRows[virtualRows.length - 1];
  const lastVirtualIndex = lastVirtualRow?.index ?? -1;

  // Infinite scroll: once the last rendered row is at (or near) the end of
  // what's currently loaded, fetch the next cursor page. Effect (not inline
  // during render) since fetchNextPage is a side effect.
  useEffect(() => {
    if (
      lastVirtualIndex >= records.length - 1 &&
      records.length > 0 &&
      recordsQuery.hasNextPage &&
      !recordsQuery.isFetchingNextPage
    ) {
      recordsQuery.fetchNextPage();
    }
  }, [lastVirtualIndex, records.length, recordsQuery]);

  return (
    <div className="p-8">
      <div className="mb-4 flex items-center gap-3">
        <label className="text-13 text-ink-soft" htmlFor="data-tab-stage-filter">
          Stage
        </label>
        <Select
          id="data-tab-stage-filter"
          className="w-56"
          value={stageId ?? ""}
          onChange={(e) => setStageId(e.target.value === "" ? null : Number(e.target.value))}
        >
          <option value="">All stages</option>
          {stages.map((s) => (
            <option key={s.id} value={s.id}>
              {s.name}
            </option>
          ))}
        </Select>
        {recordsQuery.isFetching && !recordsQuery.isFetchingNextPage && (
          <span className="text-12 text-ink-soft" role="status">
            Loading…
          </span>
        )}
      </div>

      {recordsQuery.isLoading && (
        <p className="text-14 text-ink-soft" role="status">
          Loading stage records…
        </p>
      )}

      {recordsQuery.isError && (
        <p className="text-14 text-parity-fail" role="alert">
          Couldn't load stage records.
        </p>
      )}

      {!recordsQuery.isLoading && !recordsQuery.isError && records.length === 0 && (
        <p className="text-14 text-ink-soft">No stage records for this pipeline yet.</p>
      )}

      {records.length > 0 && (
        <div className="rounded-card border border-line">
          <div
            className="grid border-b border-line bg-beam-soft/40 px-4 text-12 font-medium text-ink-soft"
            style={{ gridTemplateColumns: GRID_TEMPLATE }}
          >
            <div className="px-2 py-2">Trace</div>
            <div className="px-2 py-2">Stage</div>
            <div className="px-2 py-2">Input</div>
            <div className="px-2 py-2">Rendered prompt</div>
            <div className="px-2 py-2">Output</div>
            <div className="px-2 py-2 text-right">Tok in</div>
            <div className="px-2 py-2 text-right">Tok out</div>
            <div className="px-2 py-2 text-right">Cost</div>
            <div className="px-2 py-2 text-right">Latency</div>
          </div>

          <div
            ref={scrollRef}
            className="max-h-[70vh] overflow-y-auto"
            data-testid="data-table-scroll"
          >
            <div style={{ height: rowVirtualizer.getTotalSize(), position: "relative" }}>
              {virtualRows.map((virtualRow) => {
                const record = records[virtualRow.index];
                return (
                  <button
                    key={record.id}
                    type="button"
                    onClick={() => setSelectedRecord(record)}
                    className="grid w-full items-center border-b border-line px-4 text-left text-13 text-ink transition-colors duration-fast ease-out hover:bg-beam-soft/50"
                    style={{
                      gridTemplateColumns: GRID_TEMPLATE,
                      position: "absolute",
                      top: 0,
                      left: 0,
                      width: "100%",
                      height: virtualRow.size,
                      transform: `translateY(${virtualRow.start}px)`,
                    }}
                  >
                    <div className="truncate px-2 font-mono text-12 text-ink-soft">
                      {record.trace_id}
                    </div>
                    <div className="min-w-0 overflow-hidden px-2">
                      <Badge variant="outline" className="max-w-full truncate">
                        {record.stage_name}
                      </Badge>
                    </div>
                    <div className="truncate px-2 text-ink-soft">
                      {truncate(stringifyInput(record.input))}
                    </div>
                    <div className="truncate px-2 text-ink-soft">
                      {truncate(record.rendered_prompt)}
                    </div>
                    <div className="truncate px-2 text-ink-soft">{truncate(record.output)}</div>
                    <div className="px-2 text-right tabular-nums">{record.tokens_in ?? "—"}</div>
                    <div className="px-2 text-right tabular-nums">{record.tokens_out ?? "—"}</div>
                    <div className="px-2 text-right tabular-nums">{formatCost(record.cost)}</div>
                    <div className="px-2 text-right tabular-nums">
                      {formatLatency(record.latency_ms)}
                    </div>
                  </button>
                );
              })}
            </div>
          </div>
        </div>
      )}

      <StageRecordDrawer record={selectedRecord} onClose={() => setSelectedRecord(null)} />
    </div>
  );
}

function StageRecordDrawer({
  record,
  onClose,
}: {
  record: StageRecordOut | null;
  onClose: () => void;
}) {
  return (
    <DrawerRoot open={record !== null} onOpenChange={(open) => !open && onClose()}>
      <DrawerContent>
        <DrawerHeader>
          <DrawerTitle>{record ? record.stage_name : "Stage record"}</DrawerTitle>
          <DrawerDescription>
            {record ? `Record ${record.id} · Trace ${record.trace_id}` : ""}
          </DrawerDescription>
        </DrawerHeader>
        <DrawerBody>
          {record && (
            <div className="space-y-4">
              <div className="flex flex-wrap gap-4 text-12 text-ink-soft">
                <span>Tokens in: {record.tokens_in ?? "—"}</span>
                <span>Tokens out: {record.tokens_out ?? "—"}</span>
                <span>Cost: {formatCost(record.cost)}</span>
                <span>Latency: {formatLatency(record.latency_ms)}</span>
              </div>

              <div>
                <h3 className="mb-1 text-12 font-medium text-ink">Input</h3>
                <pre className="whitespace-pre-wrap break-words rounded-control bg-beam-soft/30 p-3 text-12 text-ink">
                  {JSON.stringify(record.input, null, 2)}
                </pre>
              </div>

              <div>
                <h3 className="mb-1 text-12 font-medium text-ink">Rendered prompt</h3>
                <pre className="whitespace-pre-wrap break-words rounded-control bg-beam-soft/30 p-3 text-12 text-ink">
                  {record.rendered_prompt}
                </pre>
              </div>

              <div>
                <h3 className="mb-1 text-12 font-medium text-ink">Output</h3>
                <pre className="whitespace-pre-wrap break-words rounded-control bg-beam-soft/30 p-3 text-12 text-ink">
                  {record.output}
                </pre>
              </div>
            </div>
          )}
        </DrawerBody>
      </DrawerContent>
    </DrawerRoot>
  );
}
