# Find Radar data

This source branch owns trusted configuration, matcher fixtures and sanitized review policy. Its generated JSON/NDJSON copies are historical compatibility/CI inputs. They are not the current operational dataset.

| Need | Location |
| --- | --- |
| Current operational archives, durable facts and inventory | [radar-data branch](https://github.com/Hecavex/radar.hecavex.com/tree/radar-data) |
| Complete public observed-hostname cohort | [index](https://radar.hecavex.com/data/observed-hostnames-v1.json) and its digest-bound parts |
| Period totals and explicit recovery gaps | [period metrics](https://radar.hecavex.com/data/period-metrics-v1.json) |
| Versioned record/metric definitions | [public contract](../docs/DATA-CONTRACT.md), [observations](../docs/OBSERVATIONS.md), [metrics](../docs/PERIOD-METRICS.md) |
| Served source/data identity, trusted transport and recovery | [deployment](../docs/DEPLOYMENT.md) |

Do not execute the data branch. Materialize its allowlisted regular blobs with trusted `hecavex_radar.data_branch` tooling. Source history stopping at September7 reflects the source/data cutover; later operational observations are on `radar-data`.
