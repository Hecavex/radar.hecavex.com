# Weekly dataset releases

The Radar release workflow is designed to publish one ordinary point-in-time dataset package for each ISO week after its repository gates pass. A release exists only when it appears on the repository's [GitHub Releases page](https://github.com/Hecavex/radar.hecavex.com/releases); the checked-in workflow and schedule do not prove that any week has been published. A successful release complements the live hourly files but does not expand Radar's sampled collection coverage or turn a candidate into a maliciousness verdict.

## Release contract

New publications include the complete observed-hostname index/parts and period metrics declared by their feed manifest; unknown legacy clocks and recovered coverage remain explicit. An intentional historical weekly backfill may predate these additions. Only that archival workflow opts into `allow_legacy_observations`: both new top-level artifacts and all cohort parts must be absent. A partial new cohort still fails, and all pre-existing schema, IDN, digest, scope and manifest checks remain active. Live/sync validation always requires the new complete cohort. Backfill never rewrites historical observations to look like a newly captured release.

[`release-weekly-dataset.yml`](../.github/workflows/release-weekly-dataset.yml) runs at 06:29 UTC each Monday and can also be dispatched by a maintainer. A successful run creates the tag `radar-data-YYYY-Www` at the exact selected data-source commit and publishes four assets. The workflow code, Python package, schemas, validators, and dependency locks always come from the triggering current `main` commit; an optional historical source contributes data only.

| Asset | Purpose |
| --- | --- |
| `radar-data-YYYY-Www.tar.gz` | Reproducible archive of the checked-in static public data tree and validated bounded context-journal partitions |
| `radar-data-YYYY-Www.manifest.json` | Data-source and trusted-tooling commits, snapshot timestamp, exclusion statement, and SHA-256 digest and byte length for every packaged dataset and context file; the identical in-archive manifest cannot recursively inventory itself |
| `radar-data-YYYY-Www.spdx.json` | SPDX 2.3 software and dependency inventory derived from the exact Python runtime lock and complete pnpm package lock |
| `SHA256SUMS` | Download verification for the archive, standalone manifest, and SPDX document |

An immutable release cannot be edited after publication. If a material data-quality defect is discovered, a maintainer may dispatch a bounded correction revision from 1 through 999. That creates a new `radar-data-YYYY-Www-rN` tag and four independently attested assets. Its notes identify the ordinary weekly tag it supersedes; the original remains unchanged as an audit record. Correction revisions are exceptional and must not be used as rolling mutable snapshots.

The archive contains the canonical public dataset beneath a tag-named root: artifacts and checksum sidecars declared by the validated feed manifest, the feed manifest and its checksum, index-declared shards, and signal sidecars explicitly declared available by the snapshot. It can also contain the checked-in, validated, bounded partitions below `data/history/context/`. URLScan-derived context rows are included only when `URLSCAN_DERIVED_REDISTRIBUTION_CONFIRMED` is exactly `true`; an API key alone cannot make them releasable. It excludes `public/data/collection-health.json`: that bounded latest-attempt document is replaced independently of the synchronized snapshot and would misrepresent an atomic weekly cut. Its last synchronized aggregate remains available in `pipeline-health.json`.

Before packaging, current trusted tooling materializes only regular blobs below `public/data/` and `data/history/context/` from the selected commit into a new runner-temporary data root. Historical workflow files, Python, scripts, actions, manifests, package metadata, and dependency locks are neither copied nor executed. The current validator then compares the reference-derived allowlist with every regular file below the extracted `public/data/` tree and independently validates each eligible context-journal partition, including path, schema, record, age, size, and redistribution-gate boundaries. A missing public artifact, unexpected public-data file, non-regular Git entry, symlink, unsafe path, digest or length mismatch, or package-bound failure stops the release. This prevents stale, accidental, permission-gated, or executable historical content from being preserved in an immutable archive.

The package timestamp and file order are normalized. Building twice from the same selected data source with the same trusted tooling must produce the same archive bytes; the workflow performs that comparison before uploading anything. The SBOM binds its namespace and dependency inventory to the trusted-tooling commit, while the release manifest separately preserves the selected data-source commit. It records the release archive and manifest digests plus the exact Python runtime pins and direct and transitive packages from the current trusted-tooling locks. License fields that cannot be established from those pinned inputs remain `NOASSERTION`; the SBOM is a dependency inventory, not a vulnerability or phishing assessment.

## One-time repository control

Release immutability is enforced by GitHub at repository level and is not enabled by the workflow.

1. In the repository settings, under **Releases**, enable **Release immutability**. The protection applies only to future releases.
2. Add the repository variable `RADAR_IMMUTABLE_RELEASES_CONFIRMED` with the exact value `true`.
3. Dispatch **Release weekly radar dataset** once or wait for the next Monday run.

The variable is an intentional operator gate, not proof of the setting. After publishing, the workflow queries the release API and fails unless GitHub reports `immutable: true`. Do not set the variable before the repository control is active.

GitHub locks the published tag and release assets when immutability is enabled and creates its own release attestation. The workflow also generates a separate SLSA-style provenance attestation for the archive, standalone manifest, SPDX document, and checksum list with the fully pinned official `actions/attest` action. No additional secret is required; the job uses short-lived OIDC and the repository workflow token.

## Idempotency and recovery

- An existing published and immutable tag is treated as a successful no-op only after the workflow verifies its four required asset names, its full source commit, that commit's ancestry from current `main`, and the ISO week recorded by that commit's `feed-manifest.json`. A manually supplied source revision must match the existing target exactly.
- An interrupted draft can be refreshed only when it targets the same source commit. Unexpected assets block publication.
- A same-week draft targeting a different commit is never overwritten. A maintainer must inspect and deliberately resolve that draft before retrying.
- The workflow attaches every asset to a draft, generates the provenance attestation, and only then publishes. This follows GitHub's immutable-release publication guidance.
- Dataset releases are not marked as the repository's latest software release.

To recover a missed historical week, find a full 40-character commit SHA on `main` whose checked-in `public/data/feed-manifest.json` timestamp belongs to that ISO week. Manually dispatch the workflow with both `release_week` in canonical `YYYY-Www` form and that exact `source_sha`. The job keeps current `main` checked out as its trusted executable toolchain, verifies the requested commit's ancestry, and extracts only its bounded publication data into a separate temporary root. It refuses to publish if the snapshot belongs to another week. It never executes historical repository code or rebuilds a historical package from today's mutable data. Use the optional correction number only to supersede an already published base week after a documented material defect; it does not replace the ordinary backfill path.

If a run reports that a published release is not immutable, stop later releases, correct the repository setting, and review that mutable release before retrying. Immutability cannot be applied retroactively.

## Consumer verification

After downloading all four assets into one directory:

```sh
sha256sum --check SHA256SUMS
gh attestation verify radar-data-YYYY-Www.tar.gz --repo Hecavex/radar.hecavex.com
gh attestation verify radar-data-YYYY-Www.manifest.json --repo Hecavex/radar.hecavex.com
gh attestation verify radar-data-YYYY-Www.spdx.json --repo Hecavex/radar.hecavex.com
gh attestation verify SHA256SUMS --repo Hecavex/radar.hecavex.com
```

Releases attested before the 26 August 2026 repository rename retain the signed workflow identity `Hecavex/hecavex-radar`. Verify those historical assets with the former slug, which currently resolves to this repository:

```sh
gh attestation verify ARTIFACT --repo Hecavex/hecavex-radar
```

Do not recreate a different repository at the former slug while those attestations remain part of the public audit trail. Releases produced after the rename use `Hecavex/radar.hecavex.com` as shown above.

The checksum establishes byte integrity. The GitHub attestation binds those bytes to the repository workflow and source revision. Neither mechanism validates third-party observations or changes the terms in [`DATA-LICENSE.md`](../DATA-LICENSE.md).
