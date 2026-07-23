import { useEffect, useRef, useState } from "react";
import { Link } from "@tanstack/react-router";
import {
  ArrowRight,
  CheckCircle2,
  DollarSign,
  FlaskConical,
  GitCompare,
  RefreshCw,
  Search,
  ShieldCheck,
  Workflow,
} from "lucide-react";
import { Logo } from "@/components/logo";
import { ParityBeam } from "@/components/parity-beam";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const TRACE_STAGES = ["Classify", "Search", "Summarize", "Answer"];

const FLOW_STEPS = [
  {
    icon: Workflow,
    title: "Learn",
    body: "Learns what “a good answer” looks like for each step, from your own examples.",
  },
  {
    icon: Search,
    title: "Search",
    body: "Tries the cheaper model with different prompts and settings until it matches.",
  },
  {
    icon: GitCompare,
    title: "Check",
    body: "Checks the match three ways: rule-based checks, an AI judge, and a similarity score.",
  },
  {
    icon: ShieldCheck,
    title: "Prove",
    body: "Proves it on examples it never used while searching — no cheating.",
  },
  {
    icon: CheckCircle2,
    title: "Hand back",
    body: "Hands you the new working prompts plus a scorecard: accuracy kept, cost saved, speed change.",
  },
];

// "Mutate" runs once, up front - only Score/Critique/Refine actually repeat
// per round (see packages/core/src/reprompt_core/optimizer/loop.py's
// _optimize_stage_prism: one generate_prompt_mutations call before the
// round loop, then cheap_scoring -> critiquing -> refining each round).
// Kept as two separate constants so the landing page doesn't visually claim
// Mutate re-runs every round, which it doesn't.
const PRISM_FIRST_STEP = "Mutate";
const PRISM_LOOP_STEPS = ["Score", "Critique", "Refine"];

/** Mirrors tokens.css's own `prefers-reduced-motion` handling for the one
 * animation on this page driven from JS rather than pure CSS (the step
 * cyclers below) - CSS motion elsewhere on this page rides `--duration-base`,
 * which tokens.css already zeroes under reduced motion for free. */
function useReducedMotion(): boolean {
  const [reduced, setReduced] = useState(
    () => typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
  useEffect(() => {
    const query = window.matchMedia("(prefers-reduced-motion: reduce)");
    const onChange = () => setReduced(query.matches);
    query.addEventListener("change", onChange);
    return () => query.removeEventListener("change", onChange);
  }, []);
  return reduced;
}

/** Loops an active index 0..count-1 on a fixed interval - used to sweep a
 * highlight across the trace stages and the Prism steps so both rows read
 * as "data moving through a sequence" rather than a static list. Disabled
 * entirely (stays at index 0) under reduced motion. */
function useCycle(count: number, intervalMs: number): number {
  const reducedMotion = useReducedMotion();
  const [active, setActive] = useState(0);
  useEffect(() => {
    if (reducedMotion) return;
    const id = setInterval(() => setActive((i) => (i + 1) % count), intervalMs);
    return () => clearInterval(id);
  }, [reducedMotion, count, intervalMs]);
  return reducedMotion ? 0 : active;
}

/** Fades/slides a section's content in the first time it scrolls into view,
 * via IntersectionObserver rather than a scroll listener. Purely decorative
 * (see globals.css's landing-flow-dot comment on why marketing-page motion
 * is exempt from the "motion must map to a real state" rule) - skips
 * straight to visible under reduced motion instead of animating in. */
function Reveal({ children, className }: { children: React.ReactNode; className?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setVisible(true);
          observer.disconnect();
        }
      },
      { threshold: 0.15 }
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  return (
    <div ref={ref} className={cn("landing-reveal", visible && "landing-reveal-visible", className)}>
      {children}
    </div>
  );
}

/**
 * Hero mark: a scaled-up version of the Logo's own beam-split-converge
 * shape (same paths, same tokens) so the hero visual reads as the same
 * mark, not a new one invented for this page. Draws in once on mount via
 * the same clip-path/rAF technique ParityBeam already uses elsewhere in
 * this codebase, rather than a bespoke animation approach.
 */
function HeroBeam() {
  const [drawn, setDrawn] = useState(false);

  useEffect(() => {
    const raf = requestAnimationFrame(() => {
      requestAnimationFrame(() => setDrawn(true));
    });
    return () => cancelAnimationFrame(raf);
  }, []);

  return (
    <svg
      viewBox="0 0 320 160"
      fill="none"
      className="h-auto w-full max-w-md"
      role="img"
      aria-label="A prompt splits into candidate rewrites, then converges on a single verified answer"
    >
      <text x="4" y="72" className="fill-ink-soft" style={{ font: "12px var(--font-mono)" }}>
        prompt in
      </text>
      <path d="M4 84 H70" stroke="var(--ink)" strokeWidth="3" strokeLinecap="round" />
      <path
        d="M70 84 Q 160 20 250 84"
        stroke="var(--spectrum-violet)"
        strokeWidth="2.5"
        strokeLinecap="round"
        pathLength={100}
        style={{
          strokeDasharray: 100,
          strokeDashoffset: drawn ? 0 : 100,
          transition: "stroke-dashoffset var(--duration-base) var(--ease-out) 150ms",
        }}
      />
      <path
        d="M70 84 Q 160 148 250 84"
        stroke="var(--spectrum-teal)"
        strokeWidth="2.5"
        strokeLinecap="round"
        pathLength={100}
        style={{
          strokeDasharray: 100,
          strokeDashoffset: drawn ? 0 : 100,
          transition: "stroke-dashoffset var(--duration-base) var(--ease-out) 150ms",
        }}
      />
      <path
        d="M250 84 H310"
        stroke="var(--parity-pass)"
        strokeWidth="4"
        strokeLinecap="round"
        pathLength={100}
        style={{
          strokeDasharray: 100,
          strokeDashoffset: drawn ? 0 : 100,
          transition: "stroke-dashoffset var(--duration-base) var(--ease-out) 400ms",
        }}
      />
      <text x="240" y="140" textAnchor="end" className="fill-parity-pass" style={{ font: "12px var(--font-mono)" }}>
        verified match out
      </text>
    </svg>
  );
}

function SectionHeading({ eyebrow, title }: { eyebrow: string; title: string }) {
  return (
    <div className="mb-8">
      <p className="text-12 font-semibold uppercase tracking-wide text-beam">{eyebrow}</p>
      <h2 className="mt-1 font-display text-28 font-semibold leading-display text-ink">{title}</h2>
    </div>
  );
}

export default function Landing() {
  const activeTraceStage = useCycle(TRACE_STAGES.length, 1000);
  const activePrismStep = useCycle(PRISM_LOOP_STEPS.length, 1100);

  return (
    <div className="flex min-h-screen flex-col bg-paper">
      <header className="mx-auto flex w-full max-w-[1440px] items-center justify-between px-8 py-6">
        <div className="flex items-center gap-2 font-display text-20 font-semibold leading-display text-ink">
          <Logo className="h-7 w-7" />
          Reprompt
        </div>
        <Button asChild variant="secondary" size="sm">
          <Link to="/login">Sign in</Link>
        </Button>
      </header>

      <main className="flex-1">
        {/* ---- Hero ---- */}
        <section className="mx-auto flex w-full max-w-[1440px] flex-col items-center gap-10 px-8 pb-20 pt-8 text-center md:flex-row md:text-left">
          <div className="flex flex-1 flex-col items-center gap-5 md:items-start">
            <h1 className="max-w-xl font-display text-40 font-semibold leading-display text-ink">
              Change the AI model behind your product without breaking it — and prove it.
            </h1>
            <p className="max-w-lg text-16 text-ink-soft">
              Reprompt migrates multi-stage LLM pipelines to cheaper or on-prem models, and proves
              the outputs still match — no manual prompt rewriting, no guessing.
            </p>
            <div className="flex flex-wrap items-center justify-center gap-3 md:justify-start">
              <Button asChild size="lg">
                <Link to="/login">
                  Sign in
                  <ArrowRight className="h-4 w-4" aria-hidden="true" />
                </Link>
              </Button>
              <Button asChild variant="ghost" size="lg">
                <a href="#how-it-works">See how it works</a>
              </Button>
            </div>
          </div>
          <div className="flex flex-1 justify-center">
            <HeroBeam />
          </div>
        </section>

        {/* ---- What is a trace ---- */}
        <section className="border-t border-line px-8 py-16">
          <Reveal className="mx-auto max-w-[1440px]">
            <SectionHeading eyebrow="Where it starts" title="It starts with what your pipeline already does" />
            <p className="max-w-2xl text-14 text-ink-soft">
              Give Reprompt real examples of your pipeline running — what went into each step,
              and what came out. No new instrumentation to build against a spec: if you can log
              inputs and outputs, you already have a trace.
            </p>
            <div className="mt-8 flex flex-wrap items-center gap-2">
              {TRACE_STAGES.map((stage, i) => (
                <div key={stage} className="flex items-center gap-2">
                  <div
                    className={cn(
                      "rounded-card border px-4 py-2 text-13 font-medium transition-colors duration-base ease-out",
                      i === activeTraceStage
                        ? "border-beam bg-beam-soft text-beam"
                        : "border-line bg-paper text-ink"
                    )}
                  >
                    {stage}
                  </div>
                  {i < TRACE_STAGES.length - 1 && (
                    <ArrowRight className="h-4 w-4 shrink-0 text-ink-soft" aria-hidden="true" />
                  )}
                </div>
              ))}
            </div>
          </Reveal>
        </section>

        {/* ---- The flow ---- */}
        <section id="how-it-works" className="border-t border-line px-8 py-16">
          <Reveal className="mx-auto max-w-[1440px]">
            <SectionHeading eyebrow="How it works" title="From trace to proof, in five steps" />
            <div className="relative">
              <div
                className="relative mb-10 hidden h-px bg-line md:block"
                aria-hidden="true"
              >
                <div className="landing-flow-dot absolute -top-[3px] h-[7px] w-[7px] rounded-full bg-beam" />
              </div>
              <ol className="grid grid-cols-1 gap-6 md:grid-cols-5">
                {FLOW_STEPS.map((step, i) => {
                  const Icon = step.icon;
                  return (
                    <li key={step.title} className="flex flex-col gap-2">
                      <div className="flex items-center gap-2">
                        <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-beam-soft text-12 font-semibold text-beam">
                          {i + 1}
                        </span>
                        <Icon className="h-4 w-4 text-beam" aria-hidden="true" />
                      </div>
                      <p className="text-13 font-semibold text-ink">{step.title}</p>
                      <p className="text-13 text-ink-soft">{step.body}</p>
                    </li>
                  );
                })}
              </ol>
            </div>
          </Reveal>
        </section>

        {/* ---- Prism spotlight ---- */}
        <section className="border-t border-line bg-beam-soft/40 px-8 py-16">
          <Reveal className="mx-auto max-w-[1440px]">
            <SectionHeading eyebrow="The optimizer" title="Prism: the search, when one rewrite isn't enough" />
            <div className="flex flex-col gap-8 md:flex-row md:items-start">
              <p className="max-w-xl text-14 text-ink-soft">
                For harder migrations, Reprompt can hand the search to Prism — a self-evolving
                prompt optimizer that acts like a small agentic system. It rewrites the prompt,
                scores the result, reads exactly why a weak attempt fell short, fixes those
                specific problems, and tries again — for up to three rounds before locking in a
                winner.
              </p>
              <div className="flex flex-1 flex-col gap-4">
                <div className="flex flex-wrap items-center gap-2">
                  {/* Mutate runs once, up front - shown as a fixed step, not
                      part of the cycling highlight below (see PRISM_FIRST_STEP's
                      comment for why: it doesn't actually repeat per round). */}
                  <div className="rounded-card border border-line bg-paper px-3 py-1.5 text-13 font-medium text-ink">
                    {PRISM_FIRST_STEP}
                  </div>
                  <ArrowRight className="h-3.5 w-3.5 shrink-0 text-ink-soft" aria-hidden="true" />
                  {PRISM_LOOP_STEPS.map((step, i) => (
                    <div key={step} className="flex items-center gap-2">
                      <div
                        className={cn(
                          "rounded-card border px-3 py-1.5 text-13 font-medium transition-colors duration-base ease-out",
                          i === activePrismStep
                            ? "border-beam bg-beam-soft text-beam"
                            : "border-line bg-paper text-ink"
                        )}
                      >
                        {step}
                      </div>
                      <RefreshCw className="h-3.5 w-3.5 shrink-0 text-ink-soft" aria-hidden="true" />
                    </div>
                  ))}
                  <span className="rounded-full border border-line bg-paper px-3 py-1 text-12 font-medium text-ink-soft">
                    up to 3 refine rounds
                  </span>
                </div>
                <div className="flex flex-col gap-3 text-13 text-ink-soft">
                  <div className="flex items-start gap-2">
                    <DollarSign className="mt-0.5 h-4 w-4 shrink-0 text-beam" aria-hidden="true" />
                    <span>
                      <span className="font-medium text-ink">Hard dollar ceiling</span> — never
                      runs longer or costs more than it has to.
                    </span>
                  </div>
                  <div className="flex items-start gap-2">
                    <FlaskConical className="mt-0.5 h-4 w-4 shrink-0 text-beam" aria-hidden="true" />
                    <span>
                      <span className="font-medium text-ink">Plateau detection</span> — stops
                      refining an attempt the moment a round stops actually improving it.
                    </span>
                  </div>
                </div>
              </div>
            </div>
          </Reveal>
        </section>

        {/* ---- Proof not promise ---- */}
        <section className="border-t border-line px-8 py-16">
          <Reveal className="mx-auto max-w-[1440px]">
            <SectionHeading eyebrow="The result" title="Proof, not a promise" />
            <p className="max-w-2xl text-14 text-ink-soft">
              Every migration is checked three ways — a fast rule-based pass, an AI judge
              comparing old vs. new answers, and a similarity score — then proven on examples it
              never used while searching. You get a scorecard, not a guess.
            </p>
            <div className={cn("mt-10 max-w-lg rounded-card border border-line bg-paper p-6")}>
              <p className="mb-6 text-13 font-medium text-ink-soft">Example scorecard</p>
              <ParityBeam score={97} cost="$0.004 → $0.0006 / call" showLabel animateIn />
            </div>
          </Reveal>
        </section>

        {/* ---- CTA ---- */}
        <section className="border-t border-line px-8 py-20 text-center">
          <div className="mx-auto flex max-w-[1440px] flex-col items-center gap-5">
            <h2 className="font-display text-28 font-semibold leading-display text-ink">
              Bring your own traces. See the scorecard.
            </h2>
            <p className="max-w-md text-14 text-ink-soft">
              Sign in to import a pipeline and run your first migration.
            </p>
            <Button asChild size="lg">
              <Link to="/login">
                Sign in
                <ArrowRight className="h-4 w-4" aria-hidden="true" />
              </Link>
            </Button>
          </div>
        </section>
      </main>

      <footer className="border-t border-line px-8 py-8">
        <div className="mx-auto flex max-w-[1440px] flex-col items-center justify-between gap-3 text-13 text-ink-soft md:flex-row">
          <span>
            Reprompt by{" "}
            <a href="https://veloceai.in/" className="text-beam hover:underline">
              Veloce AI
            </a>
          </span>
          <Link to="/schema" className="text-beam hover:underline">
            Trace format reference
          </Link>
        </div>
      </footer>
    </div>
  );
}
