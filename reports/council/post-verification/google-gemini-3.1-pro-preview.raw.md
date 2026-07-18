- ID and concise title: CP-UI-01: Ambiguous link text for evidence receipts
- severity: low
- confidence: high
- evidence: `entries/openai-build-week-2026/site/app/ContestPilot.tsx` line 178
- reproduction: Render the evidence section with multiple verified items containing URLs. Tab through the links or list links via a screen reader rotor.
- impact: accessibility consequence (multiple links simply read "Open receipt" without context, violating WCAG 2.4.4 Link Purpose).
- improvement: Add a descriptive `aria-label` to the link that includes the item's label: `aria-label={\`Open receipt for \${item.label}\`}`.
- verification: Run an accessibility tree inspection (e.g., axe-core) to confirm each receipt link has a unique, descriptive accessible name.

- ID and concise title: PF-UI-01: Missing alt text on dynamically loaded asset previews
- severity: medium
- confidence: high
- evidence: `entries/backblaze-generative-media-2026/app/static/app.js` lines 92 and 225
- reproduction: Complete a successful pipeline run or load the showcase. Inspect the `#asset-preview` and `#showcase-image` elements in the DOM.
- impact: accessibility consequence (screen reader users are not provided context for the dynamically loaded generated images).
- improvement: Explicitly set the `alt` attribute when setting the `src`, e.g., `document.querySelector("#asset-preview").alt = "Generated campaign asset preview";`.
- verification: Verify via DOM inspection or screen reader that the image has a descriptive `alt` attribute immediately after the `src` is updated.

ContestPilot: CONDITIONAL
ProofForge Media: CONDITIONAL

Top highest-leverage fixes:
1. Add `aria-label={\`Open receipt for \${item.label}\`}` to the receipt links in `ContestPilot.tsx` to ensure screen reader users have context for external links.
2. Dynamically assign descriptive `alt` text to `#asset-preview` and `#showcase-image` in `app.js` when their `src` attributes are updated.
