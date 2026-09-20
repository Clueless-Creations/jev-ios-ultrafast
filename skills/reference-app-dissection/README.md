# Product Dissection

A standalone agent capability for reconstructing an authorized consumer app as a durable, evidence-backed **Reference Product Profile**.

The profile captures the whole observable product system: product entities and relationships; information architecture; onboarding and returning-user flows; core loops; profiles/accounts/settings; progression/rewards; social; subscriptions/paywalls; notifications; every observed surface/state; components; navigation; motion; gestures; haptics/audio; accessibility; content behavior; technical observations; evidence; confidence; and unknowns.

## Boundary

This skill ends at understanding the reference product.

It does not know whether somebody later wants "Duolingo for cooking," "Strava for reading," or anything else. It does not recommend adopting, adapting, or rejecting mechanics for a target product.

A downstream system such as Brigade can consume the Reference Product Profile and perform that translation independently.

## Relationship to Jev

Jev is optional instrumentation for fast bounded semantic scouting on supported iOS Simulator targets. It does not own the profile and its map does not establish visual, motion, gesture, tactile, audio, product-system, or exhaustive-coverage claims.

Profiles are versioned by product, platform, and observed app version/build so they can be reused and refreshed instead of re-researching the reference for every downstream task.
