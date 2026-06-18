# HANDBOOK — team standards

The authoritative conventions live in [`CLAUDE.md`](../CLAUDE.md). This document
expands on them as the project grows.

> **Note.** The link above points to `../CLAUDE.md` — the file at the repo root.

## Docstring template (math)

```python
def f(...) -> ...:
    r"""One-line summary.

    Algorithm:
        $$ ... LaTeX ... $$

        ASCII fallback: ...

    Args:
        x: ... [units].

    Returns:
        ... [units].
    """
```

## Layout

See [`ARCHITECTURE.md`](ARCHITECTURE.md) and the `src/pathwise/` tree. Tests mirror
`src/`. `pyproject.toml` is the single source of truth for tooling.

For how to build and ship the bundled assets (component libraries, value chains,
example workbooks), see [`AUTHORING.md`](AUTHORING.md).
