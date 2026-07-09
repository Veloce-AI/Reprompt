import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import {
  DrawerRoot,
  DrawerTrigger,
  DrawerContent,
  DrawerHeader,
  DrawerTitle,
  DrawerDescription,
  DrawerBody,
} from "@/components/ui/drawer";
import { ParityBeam } from "@/components/parity-beam";
import { useState } from "react";

export default function DevKit() {
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [replayKey, setReplayKey] = useState(0);

  return (
    <div className="mx-auto max-w-[var(--content-max-width)] px-8 py-10 space-y-12">
      <header>
        <h1 className="font-display text-40 font-semibold leading-display text-ink">
          Design kit
        </h1>
        <p className="text-16 text-ink-soft mt-2">
          Refract design system — all tokens, primitives, and the signature
          ParityBeam component.
        </p>
      </header>

      {/* 1. Color */}
      <section>
        <h2 className="font-display text-28 font-semibold leading-display text-ink mb-4">
          Color
        </h2>
        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-4">
          {[
            { name: "--paper", hex: "#FAFBFD", value: "var(--paper)" },
            { name: "--ink", hex: "#10182B", value: "var(--ink)" },
            { name: "--ink-soft", hex: "#5A6478", value: "var(--ink-soft)" },
            { name: "--line", hex: "#E3E8F0", value: "var(--line)" },
            { name: "--beam", hex: "#4C5FE8", value: "var(--beam)" },
            { name: "--beam-soft", hex: "#EDEFFE", value: "var(--beam-soft)" },
          ].map((swatch) => (
            <div key={swatch.name} className="space-y-2">
              <div
                className="h-16 rounded-card border border-line"
                style={{ backgroundColor: swatch.value }}
              />
              <div>
                <div className="text-13 font-medium text-ink">{swatch.name}</div>
                <div className="text-12 text-ink-soft font-mono">{swatch.hex}</div>
              </div>
            </div>
          ))}
        </div>

        <h3 className="font-display text-20 font-semibold leading-display text-ink mt-6 mb-3">
          Spectrum gradient (reserved for ParityBeam)
        </h3>
        <div
          className="h-8 rounded-card border border-line"
          style={{ background: "var(--spectrum)" }}
        />

        <h3 className="font-display text-20 font-semibold leading-display text-ink mt-6 mb-3">
          Parity semantics
        </h3>
        <div className="grid grid-cols-3 gap-4">
          {[
            { name: "--parity-pass", hex: "#0E9F6E", meaning: "≥95% score" },
            { name: "--parity-near", hex: "#D97706", meaning: "80–95% score" },
            { name: "--parity-fail", hex: "#DC2626", meaning: "<80% score" },
          ].map((swatch) => (
            <div key={swatch.name} className="space-y-2">
              <div
                className="h-12 rounded-card border border-line"
                style={{ backgroundColor: swatch.hex }}
              />
              <div>
                <div className="text-13 font-medium text-ink">{swatch.name}</div>
                <div className="text-12 text-ink-soft font-mono">{swatch.hex}</div>
                <div className="text-12 text-ink-soft">{swatch.meaning}</div>
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* 2. Type */}
      <section>
        <h2 className="font-display text-28 font-semibold leading-display text-ink mb-4">
          Type
        </h2>
        <div className="space-y-2">
          {[
            { size: "40px", class: "text-40" },
            { size: "28px", class: "text-28" },
            { size: "20px", class: "text-20" },
            { size: "16px", class: "text-16" },
            { size: "14px", class: "text-14" },
            { size: "13px", class: "text-13" },
            { size: "12px", class: "text-12" },
          ].map((s) => (
            <div key={s.size} className="flex items-baseline gap-4">
              <span className="w-12 text-12 text-ink-soft font-mono tabular-nums">
                {s.size}
              </span>
              <span className={`${s.class} text-ink`}>
                IBM Plex Sans — The quick brown fox jumps over the lazy dog.
              </span>
            </div>
          ))}
        </div>

        <h3 className="font-display text-20 font-semibold leading-display text-ink mt-6 mb-3">
          Display (Spectral SemiBold)
        </h3>
        <p className="font-display text-40 font-semibold leading-display text-ink">
          Parity 96.4%
        </p>

        <h3 className="font-display text-20 font-semibold leading-display text-ink mt-6 mb-3">
          Mono (IBM Plex Mono, tabular-nums)
        </h3>
        <p className="font-mono tabular-nums text-16 text-ink">
          0123456789 — $1,234.56 — 96.4%
        </p>
      </section>

      {/* 3. Button */}
      <section>
        <h2 className="font-display text-28 font-semibold leading-display text-ink mb-4">
          Button
        </h2>
        <div className="flex flex-wrap gap-3 items-center">
          <Button variant="primary">Primary action</Button>
          <Button variant="secondary">Secondary action</Button>
          <Button variant="ghost">Ghost action</Button>
          <Button variant="destructive">Delete pipeline</Button>
          <Button variant="primary" disabled>
            Disabled
          </Button>
          <Button variant="primary" size="sm">
            Small
          </Button>
          <Button variant="primary" size="lg">
            Large
          </Button>
        </div>
      </section>

      {/* 4. Card */}
      <section>
        <h2 className="font-display text-28 font-semibold leading-display text-ink mb-4">
          Card
        </h2>
        <div className="grid grid-cols-2 gap-4">
          <Card>
            <CardHeader>
              <CardTitle>Pipeline summary</CardTitle>
              <CardDescription>8 stages, 3 models, 24 queries</CardDescription>
            </CardHeader>
            <CardContent>
              <p className="text-14 text-ink">
                Default card with 6px radius and 1px --line border.
              </p>
            </CardContent>
          </Card>
          <Card className="bg-beam-soft border-beam">
            <CardHeader>
              <CardTitle>Selected pipeline</CardTitle>
              <CardDescription>Selected state with --beam-soft tint</CardDescription>
            </CardHeader>
            <CardContent>
              <p className="text-14 text-ink">
                This card shows the selected state.
              </p>
            </CardContent>
          </Card>
        </div>
      </section>

      {/* 5. Table */}
      <section>
        <h2 className="font-display text-28 font-semibold leading-display text-ink mb-4">
          Table
        </h2>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Pipeline</TableHead>
              <TableHead>Stages</TableHead>
              <TableHead>Models</TableHead>
              <TableHead className="text-right">Parity</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {[
              {
                name: "Valuation analysis",
                stages: "20",
                models: [
                  { name: "GPT-4o", variant: "neutral" as const },
                  { name: "Claude 3.5", variant: "neutral" as const },
                ],
                parity: { value: "96.4%", variant: "pass" as const },
              },
              {
                name: "Document extractor",
                stages: "8",
                models: [
                  { name: "Gemini 1.5", variant: "neutral" as const },
                ],
                parity: { value: "87.2%", variant: "near" as const },
              },
              {
                name: "Support triage",
                stages: "5",
                models: [
                  { name: "GPT-4o-mini", variant: "neutral" as const },
                  { name: "Claude Haiku", variant: "neutral" as const },
                ],
                parity: { value: "61.0%", variant: "fail" as const },
              },
            ].map((row) => (
              <TableRow key={row.name}>
                <TableCell className="font-medium">{row.name}</TableCell>
                <TableCell className="font-mono tabular-nums">{row.stages}</TableCell>
                <TableCell>
                  <div className="flex gap-1.5">
                    {row.models.map((m) => (
                      <Badge key={m.name} variant={m.variant}>
                        {m.name}
                      </Badge>
                    ))}
                  </div>
                </TableCell>
                <TableCell className="text-right">
                  <Badge variant={row.parity.variant}>
                    {row.parity.value}
                  </Badge>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </section>

      {/* 6. Badge */}
      <section>
        <h2 className="font-display text-28 font-semibold leading-display text-ink mb-4">
          Badge
        </h2>
        <div className="space-y-3">
          <div className="flex flex-wrap gap-2">
            <Badge variant="neutral">GPT-4o</Badge>
            <Badge variant="neutral">Claude 3.5 Sonnet</Badge>
            <Badge variant="neutral">Gemini 1.5 Pro</Badge>
            <Badge variant="outline">gpt-4o-2024-08-06</Badge>
          </div>
          <div className="flex flex-wrap gap-2">
            <Badge variant="pass">96.4% pass</Badge>
            <Badge variant="near">87.2% near</Badge>
            <Badge variant="fail">61.0% fail</Badge>
          </div>
        </div>
      </section>

      {/* 7. Drawer */}
      <section>
        <h2 className="font-display text-28 font-semibold leading-display text-ink mb-4">
          Drawer
        </h2>
        <DrawerRoot open={drawerOpen} onOpenChange={setDrawerOpen}>
          <DrawerTrigger asChild>
            <Button variant="primary">Open stage drawer</Button>
          </DrawerTrigger>
          <DrawerContent>
            <DrawerHeader>
              <DrawerTitle>Stage detail</DrawerTitle>
              <DrawerDescription>
                Extract entities — GPT-4o
              </DrawerDescription>
            </DrawerHeader>
            <DrawerBody>
              <div className="space-y-4 text-14 text-ink">
                <p>
                  This drawer will show rubric items, benchmark vs candidate
                  comparison, and iteration timeline in future milestones.
                </p>
                <div className="space-y-2">
                  <h4 className="font-medium text-13 text-ink-soft uppercase tracking-wide">
                    Rubric checks
                  </h4>
                  <div className="space-y-1">
                    <div className="flex items-center gap-2">
                      <span className="text-parity-pass">✓</span>
                      <span>Returns valid JSON with 4 keys</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className="text-parity-pass">✓</span>
                      <span>Mentions all product names from input</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className="text-parity-fail">✘</span>
                      <span>Tone matched 7/10 traces</span>
                    </div>
                  </div>
                </div>
              </div>
            </DrawerBody>
          </DrawerContent>
        </DrawerRoot>
      </section>

      {/* 8. ParityBeam */}
      <section>
        <h2 className="font-display text-28 font-semibold leading-display text-ink mb-4">
          ParityBeam
        </h2>
        <div className="space-y-8 max-w-xl">
          <div>
            <div className="text-13 text-ink-soft mb-2">Pass (96.4%)</div>
            <ParityBeam score={96.4} />
          </div>
          <div>
            <div className="text-13 text-ink-soft mb-2">Near (87.2%)</div>
            <ParityBeam score={87.2} />
          </div>
          <div>
            <div className="text-13 text-ink-soft mb-2">Fail (61.0%)</div>
            <ParityBeam score={61.0} />
          </div>
          <div>
            <div className="text-13 text-ink-soft mb-2">No score</div>
            <ParityBeam />
          </div>
          <div>
            <div className="text-13 text-ink-soft mb-2">With label and cost</div>
            <ParityBeam score={96.4} showLabel cost="$0.42/1k" />
          </div>
          <div>
            <div className="text-13 text-ink-soft mb-2">
              Animated draw-in with stagger (click replay)
            </div>
            <div key={replayKey} className="space-y-3 mt-2">
              <ParityBeam score={96.4} animateIn animateDelay={0} />
              <ParityBeam score={87.2} animateIn animateDelay={60} />
              <ParityBeam score={61.0} animateIn animateDelay={120} />
            </div>
            <Button
              variant="secondary"
              size="sm"
              className="mt-3"
              onClick={() => setReplayKey((k) => k + 1)}
            >
              Replay draw-in
            </Button>
          </div>
        </div>
      </section>
    </div>
  );
}
