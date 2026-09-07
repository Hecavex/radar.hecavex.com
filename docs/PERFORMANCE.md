# Performance budgets

These budgets protect the production experience at [radar.hecavex.com](https://radar.hecavex.com). The HECAVEX maintainer gate, `pnpm check`, builds the service and measures its checked-in first-party output with deterministic level-9 gzip compression, catching asset and data growth without depending on a network, Lighthouse, or a variable benchmark connection.

The Python publisher separately limits each public live/history JSON artifact to 512 KiB uncompressed and the expanded STIX 2.1 projection to 2 MiB. Lazy signal-detail sidecars are limited to 16 KiB each and 3 MiB for the complete published set. The build gate cross-checks every `detailAvailable` signal against its exact sidecar path, rejects missing and orphan files, validates the bounded schemas, proves that STIX contains exactly one Domain Name and one linked Observed Data object per live row, and measures the complete generated tree against the total-output budget.

| Artifact | Budget | 2026-08-30 baseline |
| --- | ---: | ---: |
| Each HTML entry | 512 KiB gzip | 41,719 bytes gzip |
| Each JavaScript file | 225 KiB gzip | 62,520 bytes gzip |
| Each stylesheet | 48 KiB gzip | 13,119 bytes gzip |
| All JavaScript and CSS combined | 320 KiB gzip | 186,064 bytes gzip |
| Each public JSON data file | 1 MiB gzip | 16,088 bytes gzip |
| Each signal-detail sidecar | 16 KiB raw | 2,450 bytes raw |
| All signal-detail sidecars | 3 MiB raw | 163,337 bytes raw across 128 files |
| STIX 2.1 Bundle | 2 MiB raw | 175,943 bytes raw |
| Entire uncompressed `dist/` tree | 256 MiB | 16,475,175 bytes |

The verifier accounts for every byte in four diagnostic groups: bilingual signal pages, bilingual brand pages, the changes/trends/associations/tools/dataset route pairs, and all remaining files. These groups share one 256 MiB deployment limit. Individual groups have no separate aggregate ceiling. Per-response compressed budgets above still apply to every generated page and measured asset, so additional retained records do not raise the amount allowed in an individual response.

On 7 September 2026 this replaces the former 32 MiB artifact limit and fixed 12/4/8/8 MiB group allocations. Deployments had stopped when ordinary retained signal pages reached 13,484,134 bytes, despite small individual responses and a complete artifact below 32 MiB. Each retained signal produces separate English and Lithuanian routes. A 12 MiB aggregate cap therefore acted as an accidental limit on archive size. The 256 MiB operating limit gives the archive eight times the previous whole-site storage allowance while preserving a finite deployment gate. It is a storage allowance, not a visitor download budget or a promise that unlimited retention will fit. Existing record, JSON, sidecar, gzip, accessibility, and schema limits remain enforced.

Baseline measured on 2026-08-30 with the checked-in datasets and level-9 gzip:

| Measurement | Current |
| --- | ---: |
| Entire uncompressed `dist/` tree | 16,475,175 bytes |
| Largest HTML (`lt/pokyciai/index.html`) | 41,719 bytes gzip |
| Largest JavaScript (`assets/styles-BvMHKSJ_.js`) | 62,520 bytes gzip |
| Largest stylesheet (`assets/styles-NREVqccT.css`) | 13,119 bytes gzip |
| All JavaScript and CSS | 186,064 bytes gzip |
| Largest public JSON (`data/radar.stix.json`) | 16,088 bytes gzip |
| Signal-detail sidecars | 163,337 bytes across 128 files |
| Signal-page bytes | 7,773,715 bytes |
| Brand-page bytes | 1,882,642 bytes |
| Paired static-data page bytes | 3,591,805 bytes |
| Remaining-output bytes | 3,227,013 bytes |

Hashed asset names may change when their content changes. The verification output records the current largest file and aggregate groups on every run. Sidecars are fetched only when requested and are not embedded into HTML. Every generated page and sidecar belongs to exactly one measured group, and the complete `dist/` tree must stay within 256 MiB. Regression checks cover growth past both former limits, rejection above the new whole-site limit, and missing or double-counted bytes.

The HTML allowance covers the no-JavaScript, safely encoded snapshot used for hydration. The combined script/style gate is the primary interaction-cost guard. Font files remain covered by the total-output budget and separate integrity/size checks.

A budget increase requires a written reason in the change that introduces it. Prefer reducing data bootstrap size, splitting non-critical code, or removing unused assets before raising a threshold. These file-size gates complement the existing keyboard, responsive overflow, CSP, serious WCAG, and no-JavaScript checks; they do not claim to measure field Core Web Vitals.
