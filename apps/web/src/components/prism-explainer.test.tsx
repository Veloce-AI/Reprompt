import { describe, it, expect } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { fireEvent } from "@testing-library/react";
import { PrismExplainer } from "./prism-explainer";

describe("PrismExplainer", () => {
  it("renders a 'How Prism works' trigger with the panel closed by default", () => {
    render(<PrismExplainer />);

    expect(screen.getByText("How Prism works")).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("opens the panel on click and shows the self-evolving explanation, including the no-cross-migration-memory caveat", async () => {
    render(<PrismExplainer />);

    fireEvent.click(screen.getByText("How Prism works"));

    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent("Prism is a self-evolving prompt optimizer");
    expect(dialog).toHaveTextContent("up to 3 rounds per stage");
    expect(dialog).toHaveTextContent("doesn't carry learnings between separate migrations");
  });

  it("closes the panel on Escape", async () => {
    render(<PrismExplainer />);

    fireEvent.click(screen.getByText("How Prism works"));
    const dialog = await screen.findByRole("dialog");

    fireEvent.keyDown(dialog, { key: "Escape", code: "Escape" });

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });
});
