# Tracked Vintage CORE Bundles

- `vintage-core-filtered/` is the immutable filtered reference bundle.
- `vintage-core-restyle/` is the canonical offline-repaired restyle bundle.

The exact pre-repair restyle is preserved in Git commit `c346dc2`; the filtered reference was
first tracked in `25c53a0`.

Validate the current restyle without network or model access:

```bash
python -m dev.vintage_core.bundle_validation
```

Use it with the evaluator:

```bash
python -m scripts.base_eval --eval-bundle-dir artifacts/vintage-core-restyle
```

See `dev/vintage_core/review/restyle_repair_report.md` for repair scope and coverage.
