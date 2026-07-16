# Migrate ctd_sampling (formerly glider_sampling) into basestation3 (chore/update-python) as a per-dive plot

## Context

`glider_sampling` (this repo) designs a WKB-stretched CTD sampling schedule
from a stack of recent Seaglider dives and currently produces standalone
Plotly HTML via its own CLI (`glider-sampling --data-dir ... --show`). The
goal is to surface the same Plotly figures inside basestation3's existing
per-dive plotting pipeline (`Plotting/`), as a plot triggered on every dive,
using a configurable trailing window of N previous dives, styled to match
basestation3's existing plots — while keeping the package self-contained
(its own `pyproject.toml`, tests, CLI) so it can still be run and tested
standalone, rather than flattening its modules into basestation3's already
crowded top-level directory.

The package is being renamed **`glider_sampling` → `ctd_sampling`** as part
of this move (directory, Python package, distribution name, console script,
and all internal imports) — applied both in this source repo and carried
through to the copy.

Target repo/branch: `~/work/git/basestation3`, branch `chore/update-python`
(close to merging to `master`). Dependency pins were confirmed compatible
(`gsw` already matches exactly; numpy/scipy/xarray/netCDF4/pydantic/plotly
were bumped forward in this repo to match this branch exactly — done and
committed already, all 25 tests passing). `ctd_sampling` will be **tracked**
in the basestation3 repo (not gitignored like `adcp/` or `Plotting/local/`),
via a fresh copy + single commit (no shared git history).

## Step -1: feature branches in both repos

This work touches two repos; neither should land on a mainline/near-merge
branch directly. Both use the same branch name, `feature/wkb_sampling`:

- **glider_sampling** (this repo): currently on `master`, where the pin-bump
  commit already landed. Create `feature/wkb_sampling` off `master` for
  Step 0 (rename) and Step 0b (legend fix), so those land as a reviewable
  unit before being copied into basestation3.
- **basestation3**: `chore/update-python` is close to merging to `master` —
  branching `feature/wkb_sampling` off it keeps the workspace wiring, bridge
  module, and help pages as their own reviewable unit that can merge
  independently after (or alongside) `chore/update-python`, rather than
  piling onto an already-near-done branch.

## Step 0: rename glider_sampling → ctd_sampling (this repo)

- `src/glider_sampling/` → `src/ctd_sampling/`
- `pyproject.toml`: `name = "ctd_sampling"`, `packages = ["src/ctd_sampling"]`,
  `[project.scripts] ctd-sampling = "ctd_sampling.cli:main"`
- `cli.py`'s cross-module imports (`from glider_sampling.plotting import ...`,
  `from glider_sampling.wkb import ...`) → `from ctd_sampling....`
- `wkb.py`'s imports of `binning`/`buoyancy`/`io`/`smoothing` → same treatment
- `tests/*.py` import updates to match
- Commit this rename on its own before the basestation3 copy, and re-run
  `uv run pytest --cov=src --cov-report=term-missing` to confirm still green.

## Step 0b: show every WKB-schedule trace in the legend (plotting.py)

In `_add_direction_traces` (`src/ctd_sampling/plotting.py`, post-rename),
several traces currently hide themselves from the legend to avoid duplicate
entries across the dive/climb subplots and the 3 sampling options:
- `"current sampling"` — `showlegend=show_legend` (only shown for the dive row)
- `"wkb sampling"` — `showlegend=show_legend and option == 0` (only option 0, dive row)
- the thick `"{n} points"` highlight trace — `showlegend=False` always, never shown

Per your request, every trace on the sampling-schedule figure should appear
in the legend individually — so the dedup logic goes away and each trace
gets a name that's distinguishing on its own (direction + option), e.g.:

```python
def _add_direction_traces(
    fig: go.Figure,
    row: int,
    direction_label: str,          # "dive" | "climb" — replaces show_legend
    z: NDArray[np.float64],
    direction: WkbDirectionResult,
    depth_labels: Sequence[float],
) -> None:
    ...
    fig.add_trace(go.Scatter(
        ...,
        name=f"current sampling ({direction_label})",
        showlegend=True,
        ...
    ), row=row, col=1)

    for option in range(direction.n_new.size):
        ...
        fig.add_trace(go.Scatter(
            ...,
            name=f"wkb sampling, option {option} ({direction_label})",
            showlegend=True,
            ...
        ), row=row, col=1)
        fig.add_trace(go.Scatter(
            ...,
            name=f"{int(direction.n_new[option])} points ({direction_label})",
            showlegend=True,
            ...
        ), row=row, col=1)
```
and the two call sites in `build_sampling_schedule_figure` drop `show_legend=`
in favor of `direction_label="dive"` / `direction_label="climb"`. The
`legendgroup` kwargs are dropped too, since they existed only to support the
old show/hide-duplicates behavior. This only touches `plotting.py`; `wkb.py`
and the rest of the pipeline are unaffected, and the buoyancy figure's
existing `showlegend=(k == 0)` on the per-cast "5-m buoyancy frequency"
traces is left as-is (that's deduplicating ~10 identically-named raw casts
into one legend entry, not hiding a distinct trace).

Covered by the existing `tests/test_cli.py` end-to-end test and a
`plotting`-focused assertion (extend `tests/test_wkb.py` or add
`tests/test_plotting.py` if one doesn't already assert on trace count/legend
visibility) — re-run the full suite after this change, before the rename
commit in Step 0.

## File layout after the move

```
basestation3/
├── pyproject.toml                  # add [tool.uv.workspace] + [tool.uv.sources]
├── Plotting/
│   ├── __init__.py                 # register DiveWkbSchedule
│   └── DiveWkbSchedule.py          # NEW bridge module
├── html/plothelp/
│   ├── dv_wkb_buoyfreq.html         # NEW help page
│   └── dv_wkb_schedule.html         # NEW help page
└── ctd_sampling/                   # copied from this repo (renamed), tracked as-is
    ├── .claude/CLAUDE.md           # scoped standards, NOT merged into repo root
    ├── Makefile, Readme.md
    ├── pyproject.toml              # own deps/build-system, no uv.lock (workspace-managed)
    ├── src/ctd_sampling/
    │   ├── __init__.py, binning.py, buoyancy.py, cli.py, io.py,
    │   │   plotting.py, smoothing.py, wkb.py     # untouched (post-rename)
    │   └── PLAN.md
    └── tests/                      # untouched, still run standalone
```

Copy the same tracked file set this repo has (post-rename), **except**
`uv.lock` — workspace members are resolved into the root's single lockfile,
so a member-local lock is stale/unused. `.claude/CLAUDE.md` moves to
`ctd_sampling/.claude/CLAUDE.md` rather than basestation3's root: its
mandates (strict pathlib, PEP 695 generics, Google docstrings) are specific
to this package's style and don't match basestation3's existing conventions
(heavy `os.path` use, most files exempted from `ANN` in its ruff config) —
Claude Code respects nested CLAUDE.md scoping, so this keeps the standards
local to the subtree they apply to.

## Workspace wiring (basestation3/pyproject.toml)

Add:
```toml
[tool.uv.sources]
ctd_sampling = { workspace = true }

[tool.uv.workspace]
members = ["ctd_sampling"]
```
and add `"ctd_sampling"` to the root `dependencies` list. basestation3's root
has no `[build-system]` table (it's an unpackaged "virtual" project run via
`uv run` against loose scripts) — uv supports a virtual workspace root with a
packaged member, which is what `ctd_sampling` already is (it has
`[build-system]` = hatchling). No precedent for `[tool.uv.workspace]` exists
yet in this repo; this is the first use of it.

basestation3's own `[tool.pytest.ini_options] testpaths = ["tests"]` and
`[tool.ruff] include = ["./*py", "tests/*py"]` are both non-recursive /
scoped to `tests/`, so neither basestation3's root pytest nor ruff run will
pick up `ctd_sampling/`'s files — its own `[tool.pytest.ini_options]` /
`[tool.ruff]` blocks in `ctd_sampling/pyproject.toml` keep governing it
independently. Running `cd ctd_sampling && uv run ctd-sampling --data-dir
tests/fixtures --show` and `uv run pytest` continue to work unchanged (uv
workspace members remain independently runnable from their own directory,
sharing the root's resolved environment).

## New bridge module: Plotting/DiveWkbSchedule.py

Modeled on `Plotting/DiveCTD.py`'s `plot_CTD_series` for the "N-dives-back"
window pattern, and on `Plotting/DiveTS.py` for basestation3's standard plot
"look and feel" — mission/dive title via `PlotUtils.get_mission_dive`, and
the help-link annotation via `PlotUtilsPlotly.add_help_link`. Also follows
basestation3's plotly calling convention throughout `Plotting/*.py`: layout
and trace updates are built as plain dicts (`fig.update_layout({...})`,
`fig.add_trace({...})`), never `plotly.graph_objects` named-parameter
constructors or `update_layout(title=..., ...)` keyword form — the one
Plotly call the bridge itself makes (`fig.update_layout({...})` below)
already follows this. `ctd_sampling/plotting.py`'s own `go.Scatter(...)`
calls are untouched by this — that module keeps its existing, separate
style since it's reused as-is (see Step 0b) and isn't part of `Plotting/`.
Must match the
exact `plot_dive_single` structural signature checked by
`Plotting.plotdivesingle` (param *annotations*, not names, must align — the
second param is annotated `scipy.io._netcdf.netcdf_file` purely for that
structural check, even though the object passed at runtime is actually a
`netCDF4.Dataset` returned by `Utils.open_netcdf_file`, per
`BasePlot.py:plot_dives`).

```python
import BaseOptsType
import ctd_sampling.plotting as cs_plotting
import ctd_sampling.wkb as cs_wkb
import MakeDiveProfiles
import numpy as np
import PlotUtils
import PlotUtilsPlotly
from Plotting import add_arguments, plotdivesingle

_DEFAULT_BUCKETS_DEPTHS = (100.0, 200.0, 300.0, 400.0, 500.0, 600.0, 700.0, 800.0, 1200.0)
_DEFAULT_RELATIVE_N = (0.8, 1.0, 1.5)

_FIGURE_SPECS = (  # (builder, help-link slug, output tag, title suffix)
    ("_buoyancy_figure", "dv_wkb_buoyfreq", "wkb_buoyfreq", "Buoyancy Frequency"),
    ("_schedule_figure", "dv_wkb_schedule", "wkb_schedule", "WKB-Stretched Sampling Schedule"),
)

@add_arguments(additional_arguments={
    "wkb_dives_back": BaseOptsType.options_t(
        5, {"Base", "BasePlot", "Reprocess"}, ("--wkb_dives_back",), int,
        {"help": "How many dives back (inclusive of the current dive) to include "
                 "in the WKB-stretched sampling schedule plot",
         "section": "plotting", "option_group": "plotting"},
    ),
})
@plotdivesingle
def plot_wkb_schedule(
    base_opts: BaseOpts.BaseOptions,
    dive_nc_file: scipy.io._netcdf.netcdf_file,
    generate_plots=True,
    dbcon=None,
) -> tuple[list[plotly.graph_objects.Figure], list[pathlib.Path]]:
    """Plots a WKB-stretched CTD sampling schedule from the trailing dive window"""
    if not generate_plots:
        return ([], [])

    latest = dive_nc_file.dive_number
    sg_label = f"{dive_nc_file.glider:03d}"
    window_start = latest - base_opts.wkb_dives_back + 1

    # Same discovery MakeDiveProfiles.collect_nc_perdive_files / plot_CTD_series
    # already use, filtered to the trailing window and only dive numbers that
    # actually exist on disk (handles missions with < wkb_dives_back dives so
    # far, or gaps from reprocessing).
    all_nc = MakeDiveProfiles.collect_nc_perdive_files(base_opts)
    dive_numbers = sorted(
        n for f in all_nc
        if window_start <= (n := int(f.name[4:8])) <= latest
    )
    if len(dive_numbers) < 2:
        return ([], [])

    z = np.arange(0.0, 1000.0 + 5.0, 5.0)
    sg = cs_wkb.build_dive_stack(base_opts.mission_dir, sg_label, dive_numbers, z, 5.0)
    result = cs_wkb.compute_wkb_schedule(
        sg,
        buckets_depths=np.array(_DEFAULT_BUCKETS_DEPTHS),
        top_sampling_rate=5.0,
        relative_N=np.array(_DEFAULT_RELATIVE_N),
    )

    dives_str = (
        f"Dives {dive_numbers[0]} - {dive_numbers[-1]}"
        if len(dive_numbers) > 1
        else f"Dive {dive_numbers[0]}"
    )
    mission_dive_str = PlotUtils.get_mission_dive(dive_nc_file, dives_str=dives_str)

    built = {
        "_buoyancy_figure": cs_plotting.build_buoyancy_figure(sg, result),
        "_schedule_figure": cs_plotting.build_sampling_schedule_figure(
            result, sg_label, (dive_numbers[0], dive_numbers[-1])
        ),
    }

    figs = []
    ret_plots = []
    for key, help_slug, tag, title_suffix in _FIGURE_SPECS:
        fig = built[key]
        fig.update_layout({
            "title": {
                "text": f"{mission_dive_str}<br>{title_suffix}",
                "xanchor": "center",
                "yanchor": "top",
                "x": 0.5,
                "y": 0.95,
            },
            "margin": {"t": 150},
            "annotations": tuple(fig.layout.annotations or ()) + (
                PlotUtilsPlotly.add_help_link(help_slug),
            ),
        })
        figs.append(fig)
        ret_plots.extend(
            PlotUtilsPlotly.write_output_files(base_opts, f"dv{latest:04d}_{tag}", fig)
        )
    return (figs, ret_plots)
```

Key reused pieces (no reimplementation): `MakeDiveProfiles.collect_nc_perdive_files`
(dive-file discovery), `PlotUtils.get_mission_dive` / `PlotUtilsPlotly.add_help_link`
/ `PlotUtilsPlotly.write_output_files` (standard basestation3 plot chrome and
output), and `cs_wkb.build_dive_stack` / `cs_wkb.compute_wkb_schedule` /
`cs_plotting.build_*_figure` (unmodified from this repo aside from the
rename — this is the whole point of keeping ctd_sampling self-contained).
`build_dive_stack` already builds filenames as `p{sg_label}{dive_number:04d}.nc`,
matching basestation3's own `p%03d%04d.nc` convention exactly (confirmed
against `Base.py`/`FileMgr.py`), so no path translation is needed. The
`get_mission_dive(..., dives_str=...)` override for multi-dive titles mirrors
`Plotting/MissionProfiles.py`'s existing use of that same parameter.

Register it in `Plotting/__init__.py`'s per-dive import block (alongside
`DiveTS`, `DiveWetlabs`, etc.):
```python
from . import (
    ...
    DiveTS,
    DiveVertVelocityNew,
    DiveWetlabs,
    DiveWkbSchedule,
    DiveScience,
    ...
)
```

## Help pages (html/plothelp/)

`PlotUtilsPlotly.add_help_link(plot_name)` links to `/plothelp/{plot_name}.html`,
served from `basestation3/html/plothelp/`. Existing pages (`dv_ts.html`,
`dv_ctd.html`, `dv_legato.html`) follow a fixed template: `<title>`/`<h1>` plot
name + " Plot Help", an intro `<p>`, then one `<h2>` subsection per distinct
trace/figure element with a short `<p>` description and (once a real
screenshot exists) an example image under `images/<plot_name>_<subsection>.png`.

Two new files are needed, matching the two `add_help_link` slugs used in
`DiveWkbSchedule.py`:

**`html/plothelp/dv_wkb_buoyfreq.html`** — "WKB Buoyancy Frequency Plot Help":
intro paragraph explaining this shows buoyancy frequency (N) profiles gridded
across the trailing `--wkb_dives_back` dives, used as the basis for the WKB
stretching in the companion schedule plot; one `<h2>` per trace family
(per-dive buoyancy frequency profiles, smoothed/mean profile).

**`html/plothelp/dv_wkb_schedule.html`** — "WKB Sampling Schedule Plot Help":
intro paragraph explaining the plot proposes a CTD sampling interval that is
uniform in WKB-stretched (buoyancy-frequency-normalized) depth rather than in
raw depth, derived from the same trailing dive window; one `<h2>` per trace
(existing/current schedule vs. proposed schedule, per the option curves
`build_sampling_schedule_figure` draws).

Both follow the exact `<!DOCTYPE html>`/`<head>`/`style.css`/`<body>` skeleton
of `dv_ts.html`. No `<img>` example screenshots are included initially (no
rendered output exists yet to capture) — added later once the plot has run
against real mission data, following the `images/dv_wkb_<subsection>.png`
naming convention the other pages use.

## Open item to confirm during implementation

The default depth grid (`z_max=1000.0`, `dz=5.0`), `top_sampling_rate`, and
bucket depths are currently CLI defaults in `cli.py` — the bridge hardcodes
the same defaults rather than exposing every one as a new `--wkb_*` option.
If you want any of these tunable from basestation3's options too (beyond
`--wkb_dives_back`), say which, otherwise I'll leave them as fixed constants
matching the current CLI defaults.

## Verification

1. `uv run pytest --cov=src --cov-report=term-missing` in this repo after
   the rename (Step 0) — confirm still green before copying.
2. From `basestation3/`: `uv sync` — confirms the workspace resolves with
   `ctd_sampling` joined in, single lockfile, no version conflicts.
3. `cd basestation3 && uv run python -c "import ctd_sampling.wkb"` —
   confirms the package is importable from the basestation3 environment.
4. Exercise `plot_wkb_schedule` directly against `ctd_sampling/tests/fixtures/*.nc`
   (real per-dive files) with a minimal stand-in `base_opts`/opened
   `netCDF4.Dataset`, to confirm it returns two correctly-titled figures with
   help links and writes output files, before wiring it into a full
   basestation3 run.
5. `uv run ruff check ctd_sampling/ Plotting/DiveWkbSchedule.py` and
   `uv run ty check` (basestation3's root config) to confirm no new lint/type
   errors.
