# Stability and Popularity Gates

## Goal

Install only skills with enough real-world usage and maintenance signals.

## Default minimum thresholds

Use these as baseline unless user requests stricter values:

- `downloads >= 300`
- `last_update <= 180 days`
- popularity signal present (likes/stars/reviews/trending rank)
- source repo activity in last 180 days (commit/release/changelog update)

## Scoring model (0-100)

- Download volume: 0-30
- Recency of updates: 0-20
- Source maintenance health: 0-20
- Community signal quality: 0-15
- Metadata completeness: 0-15

Recommended decision:

- `>= 75`: eligible for security gates
- `60-74`: manual approval required
- `< 60`: reject

## Rejection examples

- Newly uploaded with near-zero downloads and no maintainer history
- Large download numbers but stale/unmaintained source
- Popular listing with no verifiable source repository

