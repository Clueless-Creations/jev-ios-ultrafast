# Reference App Dissection

An agent skill for turning a reference mobile app into an evidence-backed design grammar that can guide a different product.

## What it produces

The skill captures and abstracts:

- screen/state graph
- navigation philosophy
- typography, spacing, surfaces, density, icon and imagery rules
- component families and states
- motion language
- gesture grammar
- haptics and audio behavior
- accessibility behavior
- content hierarchy and density
- reusable design patterns with evidence and acceptance tests
- optional target-product adaptation

It is deliberately not "copy this app." The reference's brand, proprietary assets, copy, and business model stay separate from the transferable design rules.

## Relationship to Jev

Jev can be used as a fast semantic scout for safe navigation and app mapping. It does not replace visual/motion/tactile analysis.

The current Jev runtime in this repository is iOS-Simulator focused. Physical iPhone and Android capture can still be used by this skill through owner-assisted capture or another approved transport, but should not be described as native Jev capabilities until implemented.

## Recommended workflow

1. Establish authorization, device, version, scope, and target.
2. Map states and transitions.
3. Capture representative evidence.
4. Measure foundations, components, motion, gestures, feedback, and content.
5. Write evidence-backed claims.
6. Extract cross-domain design patterns.
7. Create target adaptation decisions.
8. Hand the compact design grammar to the builder.
