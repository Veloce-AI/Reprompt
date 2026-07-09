import { cn } from "@/lib/utils";
import { useEffect, useState } from "react";

export type ParityStatus = "pass" | "near" | "fail";

export function parityStatus(
  score: number,
  passThreshold = 95,
  nearThreshold = 80
): ParityStatus {
  if (score >= passThreshold) return "pass";
  if (score >= nearThreshold) return "near";
  return "fail";
}

export interface ParityBeamProps {
  score?: number;
  cost?: string;
  passThreshold?: number;
  nearThreshold?: number;
  prismPosition?: number;
  showLabel?: boolean;
  animateIn?: boolean;
  animateDelay?: number;
  className?: string;
}

const statusColors: Record<ParityStatus, string> = {
  pass: "bg-parity-pass",
  near: "bg-parity-near",
  fail: "bg-parity-fail",
};

export function ParityBeam({
  score,
  cost,
  passThreshold = 95,
  nearThreshold = 80,
  prismPosition = 0.5,
  showLabel = false,
  animateIn = false,
  animateDelay = 0,
  className,
}: ParityBeamProps) {
  const hasScore = score !== undefined;

  if (!hasScore) {
    return (
      <div
        role="img"
        aria-label="No migration yet"
        className={cn("relative w-full", className)}
        style={{ height: "var(--beam-thickness)" }}
      >
        <div
          className="absolute inset-0 rounded-full"
          style={{
            backgroundColor: "var(--ink)",
            opacity: 0.35,
          }}
        />
      </div>
    );
  }

  const status = parityStatus(score, passThreshold, nearThreshold);
  const markerPosition = Math.max(0, Math.min(100, score));

  // Beam draws in left-to-right via a clip-path transition, not a shared
  // global keyframe class — each instance's delay lives in its own inline
  // style so multiple beams on one page (e.g. the /dev/kit stagger demo)
  // don't fight over a single CSS class definition.
  const [drawn, setDrawn] = useState(!animateIn);

  useEffect(() => {
    if (!animateIn) return;
    setDrawn(false);
    const raf = requestAnimationFrame(() => {
      requestAnimationFrame(() => setDrawn(true));
    });
    return () => cancelAnimationFrame(raf);
  }, [animateIn]);

  return (
    <div
      role="meter"
      aria-valuenow={score}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-label={`Parity score ${score}%`}
      className={cn("relative w-full", className)}
      style={{ height: "var(--beam-thickness)" }}
    >
      <div
        data-testid="beam-track"
        className="absolute inset-0 flex"
        style={{
          height: "var(--beam-thickness)",
          clipPath: drawn ? "inset(0 0% 0 0)" : "inset(0 100% 0 0)",
          transition: animateIn
            ? `clip-path var(--duration-base) var(--ease-out) ${animateDelay}ms`
            : undefined,
        }}
      >
        <div
          className="h-full"
          style={{
            width: `${prismPosition * 100}%`,
            backgroundColor: "var(--ink)",
            borderTopLeftRadius: "calc(var(--beam-thickness) / 2)",
            borderBottomLeftRadius: "calc(var(--beam-thickness) / 2)",
          }}
        />
        <div
          className="h-full flex-1"
          style={{
            background: "var(--spectrum)",
            borderTopRightRadius: "calc(var(--beam-thickness) / 2)",
            borderBottomRightRadius: "calc(var(--beam-thickness) / 2)",
          }}
        />
      </div>

      <div
        className="absolute top-1/2 -translate-x-1/2 -translate-y-1/2"
        style={{
          left: `${markerPosition}%`,
          transition: animateIn
            ? `left var(--duration-base) var(--ease-out) ${animateDelay}ms`
            : undefined,
        }}
      >
        <div
          className={cn(
            "h-2 w-2 rounded-full border-2 border-paper",
            statusColors[status]
          )}
        />
      </div>

      {showLabel && (
        <span
          className="absolute -top-5 -translate-x-1/2 text-12 font-mono tabular-nums text-ink-soft"
          style={{ left: `${markerPosition}%` }}
        >
          {score}%
        </span>
      )}

      {cost && (
        <span className="absolute right-0 top-1/2 -translate-y-1/2 text-12 font-mono tabular-nums text-ink-soft pl-2">
          {cost}
        </span>
      )}
    </div>
  );
}
