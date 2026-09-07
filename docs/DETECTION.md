# Detection and brand matching

These are the public matching rules used by the HECAVEX-operated [radar.hecavex.com](https://radar.hecavex.com) service. The same registry and hostname checks govern CertStream collection, URLScan hunting, and snapshot synchronization. They identify possible impersonation of reviewed Lithuanian brands; they do not prove that a site is phishing.

## Matching rules

1. Normalize the hostname and reject malformed input. Suppress every reviewed official or excluded domain and its subdomains, along with documented Microsoft Defender for Cloud Apps certificate rewrite zones.
2. Match an alias only as a complete hyphen-delimited token, or as a complete sequence of tokens within one DNS label. The same label must also contain a reviewed suspicious word, unless a non-ASCII code point inside the matched alias span produces the reviewed alias skeleton. An A-label marker, Unicode decoration elsewhere in the label, or a threat word in a separate label is not context: `login.revolut.example` does not qualify.
3. Short aliases of at most four canonical characters always require those token boundaries. Their boundary-delimited suspicious-context candidates retain the default CertStream threshold, while joined forms such as `secureseb` are rejected. A narrow exception covers a longer alias joined directly to one suspicious prefix or suffix, such as `securerevolut` or `revolutlogin`. It also folds hyphen-delimited pieces inside that same label, allowing `rev-olut-login` while rejecting cross-label context. After folding, the remaining prefix or suffix must exactly equal one word in the suspicious-word set; arbitrary substrings such as `revolut` in `revolution` do not match. Registry entries cannot supply executable regular expressions.
4. One-edit matching uses restricted Damerau-Levenshtein distance, so insertion, deletion, substitution, or one adjacent transposition can qualify. It remains opt-in and applies only to a single-word alias listed in that brand's `fuzzyAliases`, with suspicious context in the same label. Digit-bearing aliases must preserve their digits.
5. Apply the brand's `excludedTerms` before scoring. These narrowly reviewed collisions prevent mappings such as Sberbank to Swedbank or `maximo` to MAXIMA.
6. Reject ambiguous evidence. If a hostname or title matches more than one brand, or a declared brand conflicts with the current hostname match, no brand is selected.

A different top-level domain or repeated hyphens can increase a score only after valid brand evidence exists. The default minimum for CertStream collection and URLScan domain hunts is 80. Confidence is a ranking score from the public rules, not a probability.

## Unicode handling

Internationalized hostnames are normalized with the pinned `idna==3.19` implementation of UTS #46 in nontransitional mode with STD3 rules. Confusable and script evidence is derived from the pinned `confusable-homoglyphs==3.3.1` UTS #39 data. This makes Unicode behavior reviewable and repeatable across the collectors, archive revalidation, and synchronization.

The public matcher can emit three bounded Unicode-related reason codes only when a non-ASCII code point contributes to the matched alias span:

- `unicode-confusable` means an internal confusable skeleton matched a reviewed alias;
- `mixed-script` means the relevant identifier combines scripts; and
- `restricted-identifier` means Radar's conservative alias-confusable heuristic observed an identifier outside the expected Latin-only profile.

The confusable skeleton is internal comparison material and is never displayed or published. `restricted-identifier` is not an implementation of Unicode's formal restriction-level algorithm and must not be described as one. A genuine alias-span substitution can establish brand resemblance without a generic threat word; the A-label marker alone cannot. Unicode evidence never establishes phishing, malicious intent, or a review disposition by itself.

CertStream and URLScan observations remain `suspected`. A CertStream candidate does not need a corresponding URLScan report: after it passes the current brand rules and CertStream match-score threshold, it is eligible for the public candidate list with evidence fields left empty. A later URLScan observation can enrich and merge with that row. A URLScan phishing verdict can raise `matchScore` and `evidenceTier` but cannot establish current liveness or replace same-brand evidence. Only a configured HECAVEX export can publish lifecycle states such as `active`, `offline`, or `mitigated`; only an explicitly exported analyst assessment can set review disposition.

## Archive revalidation

Archived observations do not keep an old match indefinitely. A CertStream hostname must produce one current brand match; synchronization uses that current match rather than trusting the archived brand label.

URLScan archives record whether brand evidence came from the domain, page title, or provider verdict. A primary-HTML hash label may also record how a related report was found, but it cannot establish the target brand by itself.

Twice-daily official-asset pivots follow the same rule. A stable, first-party favicon or JavaScript SHA-256 from any reviewed official domain can locate a public URLScan report, but the candidate must still independently match the same brand through its own domain or a provider brand verdict. Title evidence is accepted only with a URLScan phishing verdict. Cross-run ownership memory blocks hashes shared across registry brands; hashes without two current supporting scans, mismatched resource types, and official final pages are rejected.

If the current hostname matcher selects a brand, it must select the row's declared brand. If it finds no brand, the row may remain only with typed title or verdict evidence. Every retained row must still resolve to a current registry brand and pass official-domain, exclusion, and collision checks. Older or untyped archive rows are rejected.

## Review decisions

The public review export can suppress an exact host or a deliberately approved domain subtree. A brand-scoped suppression applies only when the current row resolves to that same brand, which prevents a correction for one target from hiding another target on shared infrastructure. Subtree allowlists require an explicit CLI confirmation and should not be used for shared hosting platforms.

An operator-added candidate is not a verdict override. It must independently produce exactly one current domain match, is published as `HECAVEX` and `suspected`, and cannot receive a `matchScore` above the current matcher result. An operator addition therefore cannot bypass the registry, establish a lifecycle state, or turn missing URLScan evidence into confirmation. Confirmation is a separate, expiring append-only review action with controlled evidence metadata.

## Maintaining precision

- Record every verified first-party domain in `data/brands-lt.json`, regardless of TLD, with an authoritative source.
- Add `excludedTerms` only for demonstrated lexical collisions, and validate the full false-positive hostname before publication.
- Enable `fuzzyAliases` only after reviewed positive and negative validation cases succeed.
- Do not globally allowlist shared hosting services such as `pages.dev` or `workers.dev`; attackers can obtain subdomains there.

Every registry entry carries `lastReviewedAt`, making the age of the official-domain and alias review explicit. The deterministic ledger at `data/coverage/brand-coverage.json` combines that registry state with bounded CT/CertStream activity, URLScan asset support, matcher-corpus coverage, and public review outcomes. It makes a zero-signal brand interpretable; it does not measure phishing prevalence or prove complete source coverage.

The deterministic worklist at `data/review/review-queue.json` balances current public candidates across source, brand, score band, evidence tier, reason code, and age. It is not a random sample and does not become a decision until an analyst separately records and intentionally exports an assessment.

## Matcher regression corpus

`data/matcher/lithuanian-brands-v1.json` is the versioned CI contract for the public matcher. It contains only reserved-domain synthetic examples and reviewed official domains, never active victim URLs. Each case declares the expected brand, score range, reason codes, or an explicit rejection reason. CI executes the corpus through the same matcher used by collection and synchronization, including collision, fuzzy, Unicode, and official-domain suppression cases. Generated CI checks additionally exercise every registry alias with boundary-delimited context, every short alias with joined and delimited forms, one neutral IDN-decoration case per brand, and every reviewed official-domain subtree.

The corpus is a bounded regression set, not proof that every Lithuanian brand, spelling variation, script combination, or future false positive is covered. New matcher behavior should add both positive and negative cases before it is accepted.

The September 2026 expansion contains 319 explicit cases covering all 46 reviewed registry brands. Every brand has an accepted boundary-delimited lure, a rejected neutral context, and official-domain/subdomain suppression examples. Existing diacritic, confusable, short-alias and collision cases remain. These are regression expectations, not analyst decisions about live candidates and not an estimate of detection precision. This expansion does not change the matcher algorithm or historical candidate scores.

Microsoft documents the suppressed rewrite zones in [Defender for Cloud Apps proxy troubleshooting](https://learn.microsoft.com/en-us/defender-cloud-apps/troubleshooting-proxy-url).
