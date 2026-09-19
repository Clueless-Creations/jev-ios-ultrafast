# Daybreak design brief

Daybreak turns one free Saturday into a small, unhurried plan. This local demo gives the runner seven meaningful choices and actions, with visible alternatives and a verifiable saved result. It has no network, accounts, purchases, or external assets.

## Source and study

Applied the [Appllama app design skill](https://github.com/Appllama/appllama-skills/blob/dd5caaec3d5d50ad7fc0324da238119c6b7c3707/skills/appllama-app-design-skill/SKILL.md), including native controls, motion, and simulator-loop references, at commit `dd5caaec3d5d50ad7fc0324da238119c6b7c3707`. The existing UIKit project uses the skill's explicit exception to its Expo baseline. No MCP was connected and no skill was installed globally.

Inspected two actual primary-source reference images on September 19, 2026:

- [Wanderlog mobile itinerary and map](https://wanderlog.com/p/images/67001eeeda9fb5ce113f3a4e_Itinerary%20builder-mobile.png), linked from its [trip planning page](https://wanderlog.com/plan-a-trip). The day is the dominant heading; stop names lead compact descriptions; times sit beside their stops; a numbered map explains the same itinerary spatially. Adopted the day/stop/time hierarchy and paired route overview, with far fewer controls for this narrow task.
- [Apple Maps guide detail](https://www.apple.com/v/maps/d/images/overview/guides_screen__cup3ndimps8y_large.jpg), linked from [Apple Maps](https://www.apple.com/maps/). A destination image leads into one strong guide title, a short contextual description, and a small set of native actions. Adopted place-first information and one clear next action. Daybreak substitutes an original vector route for photography.

This is a focused two-image study, not a claim to have inspected 20–30 Appllama screens. No competitor assets or layout were copied into the app. The source has standard UIKit navigation; simulator validation belongs to the integrating session.

## Visual rules

- One accent: burnt orange, brighter in dark mode. Warm neutral canvas and raised surfaces; semantic primary/secondary label colors. Accent foreground becomes dark in dark mode to preserve contrast.
- Native Dynamic Type hierarchy: Large Title on the root, compact navigator titles on drill-in pages, one display sentence, Headline, Body/Subheadline. Times use monospaced digits in a fixed, Dynamic Type-scaled column.
- Spacing follows an 8-point rhythm: 8, 16, 24, 32. Card inset 20 is the deliberate 4-point subdivision.
- Continuous corners: primary actions 14, destination/mood cards 20, route illustrations 24. Choice controls retain native medium corners.
- SF Symbols only. No emoji, gradients, ornamental shadows, decorative animation, or remote assets.
- Every page scrolls, respects safe areas, and allows Dynamic Type. Controls are at least 52 points; primary actions are at least 56 points.
- The map is an original `UIBezierPath` illustration of streets, one route, and three numbered stops. It is not a geographic navigation map.

## Flow and state

1. **Daybreak:** city cards expose Lisbon, Copenhagen, and Kyoto.
2. **Destination:** a route overview, neighborhood, pace, and **Plan a Saturday** action.
3. **Your kind of day:** choose Design & coffee, Art & gardens, or Food & markets.
4. **Make it yours:** choose transport and start time; defaults are Tram and 09:00 so Walking and 10:00 require actual choices.
5. **Your Saturday:** review the selected settings, original route, and three-stop timeline; **Save weekend** writes only this app's local preferences.
6. **Your weekend:** the saved city and full selection summary are distinct accessible labels. Saving replaces the completed editing stack; **Done** returns home without reopening the save action.

The intended showcase takes seven meaningful taps: Lisbon, Plan a Saturday, Design & coffee, Walking, 10:00, Build itinerary, Save weekend. Scrolling can add an action on smaller screens. The scenario contains a goal and final assertions, not a tap script or action allowlist. Alternate cities, moods, times, and transport remain functional.

Native push/pop supplies spatial continuity. Reduce Motion disables explicit animated pushes and completion transitions. Selection and success haptics accompany visible feedback. There are no timers or delayed decorative updates, so a screen remains stable until input. Rapid second navigation taps cannot push another page once the first page loses top-of-stack ownership.

## Verification boundary

After the first simulator pass, drill-in titles were made explicitly compact to remove empty large-title space, and timeline times were constrained to their intrinsic width with a 56-point minimum. The native source compiles with `swiftc -O` for arm64 iOS Simulator and passes ad-hoc code-signing verification. Compilation is not visual proof. The integrating session must inspect the live flow, light/dark mode, larger text, scroll reachability, back paths, and full-motion recording. No measured 60 fps or device-matrix claim is made here. The demo performs synchronous local work, so it has no network loading or connection-error state to imitate.
