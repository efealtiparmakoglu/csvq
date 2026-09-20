# Contributing to csvq

Thanks for your interest!

## Ground rules

- **Zero runtime dependencies.** Python standard library only — the
  tokenizer, parser and engine are hand-written and must stay that way.
- **Grammar changes are spec changes.** The supported SQL subset is
  documented in the README; any new syntax needs parser support, engine
  semantics, tests and a README update in the same PR.
- **Deterministic output.** Same query, same files, same output — row order
  is only undefined without ORDER BY, and even then it must be stable for
  identical inputs.
- **Clear errors.** Syntax errors exit 2 with a position; semantic errors
  (unknown column, bad file) exit 1 with a precise message.

## Workflow

```sh
python3 -m unittest discover -s tests
```

## Pull requests

1. One feature or fix per PR.
2. New syntax: grammar + engine + tests + README, all in one PR.
3. Match the existing code style; keep functions small and messages precise.

## Reporting bugs

Open an issue with the query, a minimal CSV sample, the output you got and
the output you expected. Wrong-result bugs are prioritized over crashes.
