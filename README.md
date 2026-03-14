# ARH

ARH is a small CLI for autoresearch-style deep learning iteration.

## Install

From this repo:

```bash
uv pip install -e .
```

Or inside another research repo:

```bash
pip install -e /path/to/arh
```

## Basic flow

Inside your training repo:

```bash
arh contract
arh setup
arh research
arh feedback
```

For continuous looping:

```bash
arh research-loop
```

## What each command does

- `arh contract`: creates or updates `research.md`
- `arh setup`: inspects the train entrypoint, patches smoke markers, and runs setup smoke
- `arh research`: creates the next experiment, commits it, and launches it in `tmux`
- `arh feedback`: reads the latest finished run and appends feedback to `results.md`
- `arh research-loop`: alternates `feedback` and `research` until stopped or a stop condition is reached

## Files created in your research repo

- `research.md`: research contract
- `results.md`: experiment and feedback log
- `.autoresearch/logs/`: smoke and experiment logs
