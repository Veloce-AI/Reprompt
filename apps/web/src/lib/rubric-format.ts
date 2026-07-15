/**
 * Plain-English translation for rubric checklist items (screen 4).
 *
 * A non-technical reviewer should never see a raw check object or the words
 * "JSON schema" - each `reprompt_core.deterministic` check type is rendered
 * as one readable sentence here instead. Pure functions, no React, so they're
 * trivial to unit test in isolation from the route component.
 */

export interface DeterministicCheckLike {
  type: string;
  label?: string;
  keys?: string[];
  min_length?: number;
  max_length?: number;
  unit?: string;
  field?: string;
  pattern?: string;
  must_match?: boolean;
  allowed_values?: unknown[];
  [key: string]: unknown;
}

export interface JudgeCriterionLike {
  name: string;
  weight: number;
  description?: string;
  [key: string]: unknown;
}

export function describeDeterministicCheck(check: DeterministicCheckLike): string {
  if (check.label) return check.label;

  switch (check.type) {
    case "required_keys": {
      const keys = check.keys ?? [];
      return `Must include: ${keys.join(", ")}`;
    }
    case "length_bounds": {
      const unit = check.unit === "words" ? "words" : "characters";
      const target = check.field ? ` for field '${check.field}'` : "";
      if (check.min_length != null && check.max_length != null) {
        return `Length must be between ${check.min_length} and ${check.max_length} ${unit}${target}`;
      }
      if (check.min_length != null) {
        return `Length must be at least ${check.min_length} ${unit}${target}`;
      }
      if (check.max_length != null) {
        return `Length must be at most ${check.max_length} ${unit}${target}`;
      }
      return `Length must be within bounds${target}`;
    }
    case "enum_values": {
      const allowed = (check.allowed_values ?? []).map(String).join(", ");
      return `Field '${check.field}' must be one of: ${allowed}`;
    }
    case "regex": {
      const target = check.field ? `field '${check.field}'` : "the output";
      return check.must_match === false
        ? `Must not match a disallowed pattern in ${target}`
        : `Must match a required pattern in ${target}`;
    }
    case "json_schema":
      return "Must be valid JSON matching the expected structure";
    case "no_hallucinated_ids":
      return "Must not mention ids or entities that aren't in the input";
    default:
      return `Format check: ${check.type}`;
  }
}

export function describeJudgeCriterion(criterion: JudgeCriterionLike): string {
  return criterion.description ? `${criterion.name} — ${criterion.description}` : criterion.name;
}

export function describeDownstreamField(field: string): string {
  return `Next stage reads: ${field}`;
}

/** True for check types with a purpose-built inline editor; everything else
 * falls back to delete-only (still shown via its plain-English sentence,
 * just not inline-editable field-by-field - see rubric-review.tsx). */
export function isEditableCheckType(type: string): boolean {
  return type === "required_keys" || type === "length_bounds";
}
