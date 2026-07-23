import { describe, it, expect } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { InfoTooltip } from "./info-tooltip";

describe("InfoTooltip", () => {
  it("renders the trigger with the panel closed by default", () => {
    render(<InfoTooltip label="What is this?">Explanation text.</InfoTooltip>);

    expect(screen.getByRole("button", { name: "What is this?" })).toBeInTheDocument();
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  });

  it("shows the explanation on hover and hides it again on mouse leave", () => {
    render(<InfoTooltip label="What is this?">Explanation text.</InfoTooltip>);

    const trigger = screen.getByRole("button", { name: "What is this?" });
    fireEvent.mouseEnter(trigger);
    expect(screen.getByRole("tooltip")).toHaveTextContent("Explanation text.");

    fireEvent.mouseLeave(trigger);
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  });

  it("toggles the explanation on click, for touch devices without hover", () => {
    render(<InfoTooltip label="What is this?">Explanation text.</InfoTooltip>);

    const trigger = screen.getByRole("button", { name: "What is this?" });
    fireEvent.click(trigger);
    expect(screen.getByRole("tooltip")).toBeInTheDocument();

    fireEvent.click(trigger);
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  });
});
