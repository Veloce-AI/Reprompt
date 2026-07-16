import { useQuery, type UseQueryResult } from "@tanstack/react-query";
import { getMigrationStatus, type MigrationOut } from "@/lib/api";

export interface UseMigrationStatusPollOptions {
  /** Whether this observer should poll at all right now (independent of
   * whether `migrationId` is set) — mirrors the caller's own gating
   * condition (e.g. `started` in migration-success-screen.tsx). Defaults
   * to `true`. */
  enabled?: boolean;
  /** Seed data so the first render already has something to show instead
   * of a loading flash — same use as `useQuery`'s own `initialData`. */
  initialData?: MigrationOut;
}

/**
 * Shared live-status poll for a single migration: `GET .../status` every 2s
 * while the migration is `"running"`, stopping automatically once it
 * reaches a terminal status. Extracted out of
 * `migration-success-screen.tsx`'s own run view so the Canvas tab's live
 * overlay (`pipeline-workspace.tsx`, see DEV_TRACKER.md's "Canvas tab live
 * migration overlay") reuses the exact same queryKey/queryFn/refetchInterval
 * convention rather than a second, potentially-diverging implementation.
 *
 * `migrationId=null` (e.g. no running migration found yet) disables the
 * query regardless of `options.enabled`.
 */
export function useMigrationStatusPoll(
  pipelineId: number,
  migrationId: number | null,
  options: UseMigrationStatusPollOptions = {}
): UseQueryResult<MigrationOut> {
  const enabled = (options.enabled ?? true) && migrationId !== null;

  return useQuery({
    queryKey: ["migration-status", pipelineId, migrationId],
    queryFn: () => getMigrationStatus(pipelineId, migrationId as number),
    enabled,
    initialData: options.initialData,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "running" ? 2000 : false;
    },
  });
}
