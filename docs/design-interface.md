# Radar interface contract

The September 2026 portfolio redesign changes presentation, not intelligence semantics or collection policy.

- Keep the HECAVEX logo, graphite canvas, mineral teal interaction and labelled semantic status colours.
- Keep the 94rem shell, 64px network row, 52px product row and 1160px mobile navigation transition. Header utility targets are 44px tall, centered within the unchanged product row. Navigation labels, order, routes and translated equivalents remain stable.
- Use an open home introduction aligned with the data column: no enclosing panel or top accent stripe, one bottom rule, zero horizontal inset and a 320px desktop minimum height. Narrow layouts grow naturally without clipping.
- Use self-hosted Space Grotesk for display headings, Inter at 16px/1.65 for reading, and IBM Plex Mono for dates, data and evidence identifiers. Descriptive labels and navigation are sentence case and at least 12px.
- Shared Research typography is defined in `src/styles/portfolio-typography.css`: body 400 with -.006em tracking; display headings 600 (h1 1.08/-.04em, h2 1.1/-.035em, h3 1.2/-.035em); section headings reach 32px. Navigation is Inter 12px/600, header descriptions 12px/500, hero leads up to 20px/1.45, eyebrows 12px/600/1.5 and buttons 14px/600/1.5. Heading sizes stay appropriate to their role; data and identifier fonts are not relabelled as prose.
- Currentness remains explicit beside the primary action. Delayed, unavailable and fallback snapshots must never be styled or labelled as current.
- Group metrics with spacing instead of repeated boxes. Filters have visible labels, keyboard focus and comfortable controls. A filtered empty event list offers a clear reset action.
- Keep signal counts, recorded schedule attempts, listening bounds and the planned listening ceiling visibly distinct. Missing collection is not zero threats; an expired partial-day cutoff remains incomplete.
- Preserve defanging, local-only free-text search, bounded exports, no-JavaScript publication, source attribution and all observation-versus-assessment caveats.

`scripts/verify-site.mjs` checks the source and rendered geometry, localized routes, responsive controls, accessibility and production behaviour. Performance budgets and analytical/data assertions remain release gates. A passing automated browser check does not assert manual screen-reader acceptance.
