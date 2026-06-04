# Authoring a sector pack

A *sector pack* maps one sector's vocabulary onto the generic optimisation
model. The generic core never imports a sector; a sector imports only the
core's public IR and the `DomainPack` Protocol. Adding a sector therefore
touches **only** a new folder under `src/pathwise/domains/<sector>/` plus one
registration line.

## Anatomy of a pack

```
src/pathwise/domains/<sector>/
  __init__.py        # register_domain(<Sector>Domain())
  pack.py            # DomainPack implementation
  schema.py          # workbook sheet/column schema for this sector
  mapping.py         # workbook rows -> core entities (OptimisationProblem)
  constraints.py     # (optional) sector-specific constraints
  metrics.py         # (optional) sector intensity/metric calculators
  defaults/          # bundled default data + blank workbook template
  terminology.json   # label overrides (asset->"Ship", technology->"Engine", …)
```

## The `DomainPack` contract

```python
class DomainPack(Protocol):
    name: str          # stable id used in options["domain"], e.g. "shipping"
    label: str         # UI label, e.g. "Shipping Fleet"
    def schema(self) -> dict: ...                 # workbook schema (drives UI + validation)
    def terminology(self) -> dict: ...            # label overrides
    def defaults(self) -> dict: ...               # default data + template
    def build_problem(self, model, scenario, options) -> OptimisationProblem: ...
    def domain_constraints(self) -> list: ...     # extra constraints beyond the generic set
    def extract(self, solution, problem) -> dict: ...  # sector-flavoured result sheets
```

## Worked example: adding **steel**

| Generic concept | Steel instance |
|---|---|
| Asset | plant / production line |
| Technology | BF-BOF / DRI-EAF / H2-DRI route |
| Carrier | coke, natural gas, hydrogen, scrap, electricity |
| Measure (MACC) | heat recovery, top-gas recycling, … |
| NewBuildOption | new EAF capacity |
| Target | sector CO2 cap per period |

1. Create `src/pathwise/domains/steel/` with the files above.
2. Implement `build_problem()` to read the steel workbook and emit an
   `OptimisationProblem`.
3. `register_domain(SteelDomain())` in `domains/steel/__init__.py` and import
   it from `domains/__init__.py`.
4. It now appears in `GET /api/domains` and the frontend domain selector — with
   **no change** to `core/`, `domains/shipping/`, the solver, the API, or the
   frontend.

`tests/domains/test_domain_independence.py` enforces this isolation.
