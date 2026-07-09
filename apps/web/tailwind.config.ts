import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        paper: "var(--paper)",
        ink: "var(--ink)",
        "ink-soft": "var(--ink-soft)",
        line: "var(--line)",
        beam: "var(--beam)",
        "beam-soft": "var(--beam-soft)",
        "parity-pass": "var(--parity-pass)",
        "parity-near": "var(--parity-near)",
        "parity-fail": "var(--parity-fail)",
      },
      fontFamily: {
        display: ["var(--font-display)"],
        sans: ["var(--font-sans)"],
        mono: ["var(--font-mono)"],
      },
      fontSize: {
        "12": "var(--text-12)",
        "13": "var(--text-13)",
        "14": "var(--text-14)",
        "16": "var(--text-16)",
        "20": "var(--text-20)",
        "28": "var(--text-28)",
        "40": "var(--text-40)",
      },
      fontWeight: {
        regular: "var(--weight-regular)",
        medium: "var(--weight-medium)",
        semibold: "var(--weight-semibold)",
      },
      lineHeight: {
        normal: "var(--leading-normal)",
        display: "var(--leading-display)",
      },
      spacing: {
        "1": "var(--space-1)",
        "2": "var(--space-2)",
        "3": "var(--space-3)",
        "4": "var(--space-4)",
        "5": "var(--space-5)",
        "6": "var(--space-6)",
        "8": "var(--space-8)",
        "10": "var(--space-10)",
        "12": "var(--space-12)",
        "16": "var(--space-16)",
      },
      borderRadius: {
        card: "var(--radius-card)",
        control: "var(--radius-control)",
      },
      boxShadow: {
        popover: "var(--shadow-popover)",
      },
      transitionDuration: {
        fast: "var(--duration-fast)",
        base: "var(--duration-base)",
      },
      transitionTimingFunction: {
        out: "var(--ease-out)",
      },
    },
  },
  plugins: [require("tailwindcss-animate")],
};

export default config;
