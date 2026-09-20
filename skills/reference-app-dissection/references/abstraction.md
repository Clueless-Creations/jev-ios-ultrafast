# Product abstraction protocol

A useful dissection has three layers:

1. evidence
2. claims about the reference
3. source-internal product rules and relationships

There is deliberately no target-product layer.

## From screens to systems

Do not summarize a product as a list of screens. Ask what persistent entities and systems explain behavior across those screens.

For each important event, ask:
- what state changed?
- which entities changed?
- which persistent systems changed?
- which other surfaces reflect the change?
- what is restored on return?
- what evidence supports each relationship?

## Pattern quality

A source-internal pattern should answer:
- In what context does the reference use this behavior?
- What invariant appears to hold?
- What exceptions exist?
- Which systems and states participate?
- Which observations support it?
- What would falsify the inferred rule?

Do not add advice about whether another product should copy or adapt it.

## Counterexamples matter

If pushes are generally used for deep tasks but one deep task uses a sheet, preserve the exception and inspect why. Exceptions often reveal the real reference rule.

## Product-profile rule

Prefer a smaller evidenced rule over a broad elegant theory. Unknown is a valid output.
