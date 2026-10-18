# Security policy

This policy covers the HECAVEX-operated service at [radar.hecavex.com](https://radar.hecavex.com) and its production repository. Please do not open a public issue for vulnerabilities, leaked indicators containing personal data, or exposed credentials.

Report them to [info@hecavex.com](mailto:info@hecavex.com) with:

- the affected file, workflow, or deployment URL;
- reproduction steps that do not contact a suspected phishing host;
- likely impact; and
- a safe way to verify a correction.

Do not include working secrets, victim-specific URLs, or sensitive query parameters in the report. HECAVEX will acknowledge reports as capacity permits.

## Removal and correction requests

An accepted removal or correction filters the live projections (current snapshot, history, observed hostnames and signal pages) and reaches feeds and exports from the next publication build. It cannot reach:

- the public `radar-data` Git history;
- the durable observation store;
- immutable weekly dataset releases and their attestations; or
- copies that STIX or MISP consumers have already ingested.

The same note is published in [English](https://radar.hecavex.com/docs/#data-terms) and [Lithuanian](https://radar.hecavex.com/lt/dokumentacija/#duomenu-salygos).
