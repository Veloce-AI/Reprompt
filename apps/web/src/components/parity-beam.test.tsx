import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { ParityBeam, parityStatus } from "./parity-beam";

describe("parityStatus", () => {
  it("returns pass for scores >= 95", () => {
    expect(parityStatus(100)).toBe("pass");
    expect(parityStatus(95)).toBe("pass");
    expect(parityStatus(96.4)).toBe("pass");
  });

  it("returns near for scores >= 80 and < 95", () => {
    expect(parityStatus(94.9)).toBe("near");
    expect(parityStatus(80)).toBe("near");
    expect(parityStatus(87.2)).toBe("near");
  });

  it("returns fail for scores < 80", () => {
    expect(parityStatus(79.9)).toBe("fail");
    expect(parityStatus(0)).toBe("fail");
    expect(parityStatus(61.0)).toBe("fail");
  });

  it("respects custom thresholds", () => {
    expect(parityStatus(90, 90, 80)).toBe("pass");
    expect(parityStatus(85, 90, 80)).toBe("near");
    expect(parityStatus(75, 90, 80)).toBe("fail");
  });
});

describe("ParityBeam", () => {
  it("renders with role meter and aria attributes when score is provided", () => {
    render(<ParityBeam score={96.4} />);
    const meter = screen.getByRole("meter");
    expect(meter).toBeInTheDocument();
    expect(meter).toHaveAttribute("aria-valuenow", "96.4");
    expect(meter).toHaveAttribute("aria-valuemin", "0");
    expect(meter).toHaveAttribute("aria-valuemax", "100");
    expect(meter).toHaveAttribute("aria-label", "Parity score 96.4%");
  });

  it("renders with role img and no-score label when score is undefined", () => {
    render(<ParityBeam />);
    const img = screen.getByRole("img");
    expect(img).toBeInTheDocument();
    expect(img).toHaveAttribute("aria-label", "No migration yet");
  });

  it("applies pass color for high score", () => {
    const { container } = render(<ParityBeam score={96.4} />);
    const marker = container.querySelector(".bg-parity-pass");
    expect(marker).toBeInTheDocument();
  });

  it("applies near color for medium score", () => {
    const { container } = render(<ParityBeam score={87.2} />);
    const marker = container.querySelector(".bg-parity-near");
    expect(marker).toBeInTheDocument();
  });

  it("applies fail color for low score", () => {
    const { container } = render(<ParityBeam score={61.0} />);
    const marker = container.querySelector(".bg-parity-fail");
    expect(marker).toBeInTheDocument();
  });

  it("shows label when showLabel is true", () => {
    render(<ParityBeam score={96.4} showLabel />);
    expect(screen.getByText("96.4%")).toBeInTheDocument();
  });

  it("shows cost when provided", () => {
    render(<ParityBeam score={96.4} cost="$0.42/1k" />);
    expect(screen.getByText("$0.42/1k")).toBeInTheDocument();
  });

  it("gives each animated instance an independent stagger delay via inline style, not a shared class", () => {
    const { container } = render(
      <div>
        <ParityBeam score={90} animateIn animateDelay={0} />
        <ParityBeam score={80} animateIn animateDelay={60} />
      </div>
    );
    const tracks = container.querySelectorAll('[data-testid="beam-track"]');
    expect(tracks).toHaveLength(2);
    expect(tracks[0].getAttribute("style")).toContain("0ms");
    expect(tracks[1].getAttribute("style")).toContain("60ms");
    // No global <style> tag with a shared keyframe class should be injected.
    expect(container.querySelectorAll("style").length).toBe(0);
  });

  it("keeps the marker's centering transform intact when animateIn is used", () => {
    const { container } = render(
      <ParityBeam score={96.4} animateIn animateDelay={0} />
    );
    const marker = container.querySelector(".bg-parity-pass")?.parentElement;
    expect(marker?.className).toContain("-translate-x-1/2");
    expect(marker?.className).toContain("-translate-y-1/2");
    expect(marker?.getAttribute("style") ?? "").not.toContain("scaleX");
  });

  it("beam track clips to zero width before animating in, and clips to full width when animateIn is off", () => {
    const animated = render(
      <ParityBeam score={90} animateIn animateDelay={0} />
    );
    const animatedTrack = animated.container.querySelector(
      '[data-testid="beam-track"]'
    );
    expect(animatedTrack?.getAttribute("style")).toContain(
      "inset(0 100% 0 0)"
    );

    const staticRender = render(<ParityBeam score={90} />);
    const staticTrack = staticRender.container.querySelector(
      '[data-testid="beam-track"]'
    );
    expect(staticTrack?.getAttribute("style")).toContain("inset(0 0% 0 0)");
  });
});
