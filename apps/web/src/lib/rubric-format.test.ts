import { describe, it, expect } from "vitest";
import {
  describeDeterministicCheck,
  describeDownstreamField,
  describeJudgeCriterion,
  isEditableCheckType,
} from "./rubric-format";

describe("describeDeterministicCheck", () => {
  it("translates required_keys into a plain sentence, not the raw object", () => {
    const sentence = describeDeterministicCheck({
      type: "required_keys",
      keys: ["currency", "revenue"],
    });
    expect(sentence).toBe("Must include: currency, revenue");
  });

  it("translates length_bounds with both min and max", () => {
    const sentence = describeDeterministicCheck({
      type: "length_bounds",
      min_length: 20,
      max_length: 800,
      unit: "chars",
    });
    expect(sentence).toBe("Length must be between 20 and 800 characters");
  });

  it("translates length_bounds with only a minimum, in words", () => {
    const sentence = describeDeterministicCheck({
      type: "length_bounds",
      min_length: 5,
      unit: "words",
    });
    expect(sentence).toBe("Length must be at least 5 words");
  });

  it("translates enum_values", () => {
    const sentence = describeDeterministicCheck({
      type: "enum_values",
      field: "status",
      allowed_values: ["approved", "rejected"],
    });
    expect(sentence).toBe("Field 'status' must be one of: approved, rejected");
  });

  it("translates json_schema without ever mentioning raw JSON schema syntax", () => {
    const sentence = describeDeterministicCheck({ type: "json_schema" });
    expect(sentence).not.toMatch(/schema_|properties|required\[/);
    expect(sentence).toBe("Must be valid JSON matching the expected structure");
  });

  it("translates no_hallucinated_ids", () => {
    const sentence = describeDeterministicCheck({ type: "no_hallucinated_ids" });
    expect(sentence).toBe("Must not mention ids or entities that aren't in the input");
  });

  it("prefers an explicit label over the auto-generated sentence", () => {
    const sentence = describeDeterministicCheck({
      type: "required_keys",
      keys: ["x"],
      label: "Custom label wins",
    });
    expect(sentence).toBe("Custom label wins");
  });
});

describe("describeJudgeCriterion", () => {
  it("combines name and description when both are present", () => {
    expect(
      describeJudgeCriterion({ name: "Tone: formal", weight: 0.4, description: "No casual phrasing." })
    ).toBe("Tone: formal — No casual phrasing.");
  });

  it("falls back to just the name with no description", () => {
    expect(describeJudgeCriterion({ name: "Tone: formal", weight: 0.4 })).toBe("Tone: formal");
  });
});

describe("describeDownstreamField", () => {
  it("renders a plain sentence for a field name", () => {
    expect(describeDownstreamField("currency")).toBe("Next stage reads: currency");
  });
});

describe("isEditableCheckType", () => {
  it("is true for required_keys and length_bounds", () => {
    expect(isEditableCheckType("required_keys")).toBe(true);
    expect(isEditableCheckType("length_bounds")).toBe(true);
  });

  it("is false for other check types", () => {
    expect(isEditableCheckType("json_schema")).toBe(false);
    expect(isEditableCheckType("regex")).toBe(false);
    expect(isEditableCheckType("enum_values")).toBe(false);
    expect(isEditableCheckType("no_hallucinated_ids")).toBe(false);
  });
});
