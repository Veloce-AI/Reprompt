import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center rounded-control px-2 py-0.5 text-12 font-medium transition-colors duration-fast ease-out",
  {
    variants: {
      variant: {
        neutral: "bg-beam-soft text-beam",
        pass: "bg-parity-pass/10 text-parity-pass",
        near: "bg-parity-near/10 text-parity-near",
        fail: "bg-parity-fail/10 text-parity-fail",
        outline: "border border-line text-ink-soft",
      },
    },
    defaultVariants: {
      variant: "neutral",
    },
  }
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, ...props }: BadgeProps) {
  return (
    <div className={cn(badgeVariants({ variant }), className)} {...props} />
  );
}

export { Badge, badgeVariants };
