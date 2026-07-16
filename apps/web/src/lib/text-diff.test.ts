import { describe, it, expect } from "vitest";
import { diffWords, type DiffOp } from "./text-diff";

function reconstructAfter(ops: DiffOp[]): string {
  return ops
    .filter((o) => o.type === "equal" || o.type === "insert")
    .map((o) => o.text)
    .join("");
}

function reconstructBefore(ops: DiffOp[]): string {
  return ops
    .filter((o) => o.type === "equal" || o.type === "delete")
    .map((o) => o.text)
    .join("");
}

describe("diffWords", () => {
  it("returns a single equal op for identical strings", () => {
    const ops = diffWords("Summarize the report", "Summarize the report");
    expect(ops).toEqual([{ type: "equal", text: "Summarize the report" }]);
  });

  it("marks a fully different string as one delete + one insert", () => {
    const ops = diffWords("old prompt", "new prompt text");
    expect(ops.some((o) => o.type === "delete")).toBe(true);
    expect(ops.some((o) => o.type === "insert")).toBe(true);
  });

  it("isolates a single changed word, keeping the surrounding text as equal", () => {
    const ops = diffWords("Extract the revenue figure", "Extract the total figure");
    expect(ops).toEqual([
      { type: "equal", text: "Extract the " },
      { type: "delete", text: "revenue" },
      { type: "insert", text: "total" },
      { type: "equal", text: " figure" },
    ]);
  });

  it("marks pure additions as insert-only with the rest equal", () => {
    const ops = diffWords("Summarize the input", "Summarize the input carefully now");
    expect(ops[0]).toEqual({ type: "equal", text: "Summarize the input" });
    expect(ops.some((o) => o.type === "delete")).toBe(false);
    expect(ops.filter((o) => o.type === "insert").map((o) => o.text).join("")).toBe(
      " carefully now"
    );
  });

  it("marks pure removals as delete-only with the rest equal", () => {
    const ops = diffWords("Summarize the input carefully now", "Summarize the input");
    expect(ops.some((o) => o.type === "insert")).toBe(false);
    expect(ops.filter((o) => o.type === "delete").map((o) => o.text).join("")).toBe(
      " carefully now"
    );
  });

  it("handles an empty before string (pure insertion)", () => {
    const ops = diffWords("", "brand new prompt");
    expect(ops).toEqual([{ type: "insert", text: "brand new prompt" }]);
  });

  it("handles an empty after string (pure deletion)", () => {
    const ops = diffWords("old prompt gone", "");
    expect(ops).toEqual([{ type: "delete", text: "old prompt gone" }]);
  });

  it("round-trips: concatenating equal+insert ops reproduces `after` exactly", () => {
    const before = "Extract the revenue figure from the report, formatted as JSON.";
    const after = "Extract the total revenue and cost figures from the report as strict JSON.";
    const ops = diffWords(before, after);
    expect(reconstructAfter(ops)).toBe(after);
  });

  it("round-trips: concatenating equal+delete ops reproduces `before` exactly", () => {
    const before = "Extract the revenue figure from the report, formatted as JSON.";
    const after = "Extract the total revenue and cost figures from the report as strict JSON.";
    const ops = diffWords(before, after);
    expect(reconstructBefore(ops)).toBe(before);
  });
});
