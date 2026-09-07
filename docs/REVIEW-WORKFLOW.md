# Private review workflow

This is an operator-only HECAVEX maintenance workflow for corrections to [radar.hecavex.com](https://radar.hecavex.com). False-positive review is intentionally kept on an operator workstation; the public service remains read-only and contains no administration endpoint, authentication system, private notes, or direct write path.

## Storage boundary

`hecavex-review` creates an append-only SQLite database outside the Git repository. On Windows the default is `%LOCALAPPDATA%\HECAVEX\Radar\review.sqlite3`; on Linux it follows `XDG_DATA_HOME` or `~/.local/share`. Set `RADAR_REVIEW_DB` or pass `--database` to use another path. Paths inside the repository are rejected against the installed project root, independent of the current working directory.

The review CLI is a checkout-local HECAVEX operator tool, not a public administration product. Maintainers install this repository in editable mode (`python -m pip install -e ".[dev]"`) so its canonical project root, registry, snapshot, and sanitized-export directory remain the checked-out files. A standalone wheel install is not supported for review operations because its module path would point into `site-packages` rather than an operator checkout.

The event table has database triggers that reject updates and deletes. Restore, unallowlist, and remove operations append compensating events. Private notes are stored only in this database and are omitted from normal listings.

Back up this database as private working material. Do not put it in Git, a publicly shared folder, an issue, or a CI artifact.

Initialize or verify the empty ledger before the first review:

```sh
hecavex-review init
```

This command creates only the schema and append-only triggers at the private path. It does not add a decision or modify a public artifact.

## Public intake and proposal boundary

Four public Issue Forms accept sanitized false-positive, missed-candidate, registry-correction, and removal requests. Issue text is untrusted public input. It must never be passed to a shell, scanner, collector, or publication command.

The maintainer-only `Prepare sanitized review proposal` workflow accepts a small set of controlled fields, verifies that the initiating actor has `maintain` or `admin` permission, requires a fully defanged domain, and opens a draft pull request below `data/review/proposals/`. It links the issue by number but never reads or executes its title or body. A proposal is not a decision. CODEOWNERS review and the private ledger remain required.

Generate the current stratified review worklist without a network request:

```sh
hecavex-review-queue --generated-at 2026-08-26T12:00:00.000Z
```

The queue balances public, unassessed candidates across source, brand, score band, evidence tier, reason code, and candidate age. It is a worklist, not a statistically random sample. Generate the corresponding per-brand coverage ledger with:

```sh
hecavex-coverage-ledger --generated-at 2026-08-26T12:00:00.000Z
```

The ledger explains bounded collection and review coverage for every registry entry. A zero-signal value never means zero phishing.

The normal snapshot synchronization regenerates both artifacts using the snapshot's own canonical timestamp, then immediately verifies a byte-for-byte deterministic rebuild. CI runs deterministic verification against its coherent fixture rather than the latest independently advancing collector state. Per-brand CT state distinguishes completed, backlogged, failed, and never-attempted queries from their persisted query outcome and result cursor. URLScan's candidate cursor is scheduler-wide and therefore appears only under `globalCollectorState`; it is never repeated as if it described an individual brand.

## Source/data handling for local review

Registry changes, proposals and `data/review/public-decisions.json` remain reviewed source changes on `main`. Generated-data publishers cannot change them. The private SQLite ledger remains outside both branches.

For current review inputs, use trusted source tooling to materialize the validated `publication` view of `radar-data` into a disposable source checkout as documented in [Deployment](DEPLOYMENT.md#source-and-data-cutover). Do not check out or execute data-branch code. Record the selected source and data revisions with private review evidence. A plain source checkout can contain historical snapshots and must not be assumed current.

The generated review queue and coverage ledger belong to the data branch. Snapshot sync rebuilds and verifies them from its exact inputs. Source CI instead materializes a pinned coherent fixture and derives temporary quality artifacts for that source revision. That test fixture is not a public assessment or an operational publication. Keep imported generated files out of a review PR.

## Commands

Create a private pivot queue from the current published snapshot without performing any network request:

```sh
hecavex-handoff
```

The command writes `data/hecavex/pivot-candidates.json`. That directory is git-ignored and the output contains only bounded, defanged rows backed by CertStream or public URLScan evidence. Review it locally; do not commit it. A candidate selected after analysis must still pass the current public matcher before `hecavex-review add` accepts it.

Record an exact false positive and later restore it:

```sh
hecavex-review false-positive secure-swedbank-login.example --reason lexical-collision --note "private case context"
hecavex-review restore secure-swedbank-login.example
```

Maintain an allowlist:

```sh
hecavex-review allowlist legitimate.example --scope exact --reason legitimate-domain
hecavex-review allowlist official.example --scope subdomains --reason official-domain --yes
hecavex-review unallowlist official.example
```

Add or remove a manually observed candidate:

```sh
hecavex-review add secure-swedbank-login.example --brand Swedbank
hecavex-review remove secure-swedbank-login.example
```

An addition must independently pass the current public matcher. The CLI infers the matching brand, clamps confidence to the public score, and fixes status to `suspected`. Missing URLScan evidence is allowed; it is not converted into either benign or malicious evidence.

Record a time-bounded positive assessment only after examining evidence outside the public dashboard:

```sh
hecavex-review confirm support-vinted.ph \
  --reason credential-phishing \
  --evidence certificate-transparency \
  --evidence urlscan-page \
  --lt-relevance lithuanian-targeting \
  --analyst-confidence 85 \
  --expires-at 2026-09-25T12:00:00.000Z \
  --note "private evidence references"
```

The assessment target must already exist as an exact signal in the validated complete `radar.index.json` shard set or in bounded `history.json`. The dashboard prefix is not the admission boundary, and a current matcher hit by itself is insufficient. On the first lifecycle event, the CLI records the published signal ID, defanged domain, canonical brand, observation time, sorted collection sources, and a canonical SHA-256 integrity digest. The digest detects accidental mutation; it is not a signature or a maliciousness verdict. Corrections and retractions copy that original admission envelope byte-for-byte. A direct programmatic ledger event without this provenance remains private and cannot be exported or emitted as reviewed STIX.

`confirm` is the only action that can create an active `confirmed-suspicious` assessment and make the row eligible for the separate reviewed STIX Indicator feed. It requires a future expiry, a controlled disposition reason, and at least one controlled evidence code. The evidence code states what the analyst used; raw screenshots, case notes, identities, and evidence values stay private. `--analyst-confidence`, when supplied, is separate from the automated domain `matchScore`.

Correct public assessment metadata without changing its stable Indicator identity:

```sh
hecavex-review correct support-vinted.ph \
  --reason brand-impersonation \
  --evidence certificate-transparency \
  --evidence screenshot \
  --evidence urlscan-page \
  --expires-at 2026-10-25T12:00:00.000Z
```

A correction preserves the first confirmation time and advances the public modification time. It must replace at least one public field. When evidence no longer supports the Indicator, append a retraction instead of deleting history:

```sh
hecavex-review retract support-vinted.ph --reason incorrect-assessment --note "private correction context"
```

Retraction produces the same STIX Indicator ID with `revoked: true`. That terminal lifecycle remains in the sanitized export. A later `confirm` starts a new lifecycle with a new Indicator ID; it does not remove or un-revoke the earlier object. If a review never supported confirmation, record it as inconclusive:

```sh
hecavex-review inconclusive support-vinted.ph \
  --reason insufficient-evidence \
  --evidence certificate-transparency
```

When the evidence supports a dated negative classification, record it separately from suppression:

```sh
hecavex-review dismiss secure-swedbank-login.example \
  --state false-positive \
  --reason lexical-collision \
  --evidence certificate-transparency \
  --evidence rdap \
  --lt-relevance global-brand-reference \
  --analyst-confidence 95 \
  --expires-at 2026-09-25T12:00:00.000Z
```

Use `benign-brand-reference` when the brand reference is real but the reviewed evidence does not support impersonation.
`dismiss` creates a dated, expiring assessment and does not silently delete the candidate. Use the separate
`false-positive` command only when an exact suppression is also required. Negative assessments are excluded from the
reviewed STIX Indicator feed and remain available for aggregate quality measurement.

After a positive or negative assessment expires, the dashboard presents it as `needs-review`; expiry is not silently
represented as a false positive or STIX revocation. Renew an active positive assessment before expiry with
`correct --expires-at ...`. Record a fresh `dismiss` after rechecking an expired negative assessment. An already expired
positive assessment must be confirmed again so the new explicit review boundary is recorded.

Inspect active state, then export:

```sh
hecavex-review list
hecavex-review list --events
hecavex-review export
```

Recording a decision never edits the repository. `export` is the only command that writes `data/review/public-decisions.json`. Relative export paths are resolved below the installed project's canonical `data/review/` directory, so the same command is safe and predictable when invoked from another working directory. Absolute export paths are accepted only inside that directory.

## Export review

Before committing an export:

1. Inspect `git diff -- data/review/public-decisions.json`.
2. Confirm every indicator is defanged and every brand is correct.
3. Confirm subtree scope is necessary; prefer exact scope.
4. Search the diff for private notes, names, credentials, tokens, email addresses, and case references.
5. Run `pnpm check`.
6. Submit only the intentional sanitized export and any reviewed source changes through the source PR gate. Do not commit materialized generated data or private review evidence.
7. After merge, a fresh snapshot sync must consume the new source revision before Pages can publish it.

The version 3 public file contains only deterministic decision IDs, defanged domains and URLs, scope, resolved brand, controlled reason and evidence codes, observation/admission/review/expiry times, matcher and optional analyst scores, Lithuanian relevance, and explicit review/revocation state. Synchronization fails closed if the file is malformed, cross-brand, future-dated, oversized, duplicated, missing its assessment admission envelope, or if a new manual candidate is inconsistent with the current matcher. A dated assessment preserves the canonical brand and exact public observation recorded at review time; later matcher changes do not erase the historical decision, while its admission digest, domain, deterministic signal ID, evidence codes, and timestamps remain strictly validated. Version 2 is read only as an empty-assessment migration shape. Inspect `public/data/radar-reviewed.stix.json` as part of the publication diff whenever an assessment changes.
