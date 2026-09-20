# Abstraction protocol

A useful study has three layers:

1. evidence
2. design rules
3. target choices

Never backfill target choices as facts about the source.

## Pattern quality test

A transferable pattern should answer:

- What user problem does this solve?
- In what situations should it apply?
- When should it not apply?
- What must remain invariant?
- What can vary by brand/domain/platform?
- Which observations support it?
- What would falsify the rule?
- How should a builder test it?

## Counterexamples matter

If pushes are generally used for deep tasks but one deep task uses a sheet, record the exception and inspect why. Exceptions often reveal the real rule.

## Example

Source-specific observation:

> An album preview opens in a draggable sheet and returns to the same list position.

Transferable rule:

> Secondary inspection should preserve discovery context when commitment is optional and reversible.

Target expression might be:

- recipe preview before adding to meal plan;
- property preview before saving;
- outfit preview before scheduling.

The target should not inherit album controls, source colors, source copy, or source imagery.
