# Proposed sampling-scheme text on the WKB schedule plot (PLAN.md Task 4)

## Context

This is the item split out of Task 1 into its own Task 4 in
`basestation3/.claude/PLAN.md`: show each WKB option's proposed CTD sampling
schedule as cut-and-paste text a pilot can drop into the live mission control
file, with the format depending on whether the CT is truck-mounted or
scicon-mounted.

Research done to unblock this (all confirmed against real code/data, not
guessed):

- **Truck-vs-scicon detection**: reuse the exact pattern `DiveCTD.py`/
  `DiveLegatoData.py` already use — `dive_nc_file.variables["sg_cal_sg_ct_type"]
  .getValue() == 4` means Legato; a non-Legato Seabird CT (`sg_ct_type` 0/1/2)
  is always truck-mounted. For a Legato, `"legato_time" in dive_nc_file
  .variables` means scicon-mounted; `"eng_rbr_temp" in dive_nc_file.variables`
  (no separate `legato_time`) means truck-mounted.
- **Scicon format** (`mission_dir/"scicon.sch"`, validated by
  `validate.sciconsch`): a `ct = { ... }` block of bare `depth,seconds` pairs,
  confirmed from `testdata/sg272_NANOOS_Feb26_tools/pt2720005.cap` via
  `ScienceGrid.find_scicon_sch`:
  ```
  ct = {
   50,5.000000
   200,5.000000
   1000,20.000000
  }
  ```
- **Truck format** (`mission_dir/"science"`, validated by `validate.science`):
  space-separated `depth key=value key=value ...` lines (Rev E), e.g.:
  ```
  100.0 gc=120.0 seconds=5.0 turn=0 sensors=0 compass=1 pressure=1 network=0,0,0,0 dest=-1 retries=0,0 rate=1
  ```
  `seconds=` is a **shared** sample interval for the whole depth bin (CT,
  compass, pressure together) — there's no CT-isolated field the way scicon
  has its own `ct` block. "Updating just the CTD section" for the truck case
  means: regenerate the depth-bin lines with new `depth`/`seconds` values,
  carrying over the other fields (`gc=`, `turn=`, `sensors=`, `compass=`,
  `pressure=`, `network=`, `dest=`, `retries=`, `rate=`) unchanged from the
  current file, since WKB has no opinion on GC timing or which sensors fire.

Three UX decisions confirmed with you:
1. Generate text for **all three** WKB options (not just one "the proposal"),
   swapped in per-option.
2. **Replace** the file's existing depth bins outright with the WKB
   schedule's own `buckets_depths`, rather than preserving old bins and only
   updating intervals at those depths.
3. Show **just the changed section** (the `ct = {...}` block, or only the
   regenerated depth-bin lines) — not the whole file.

**Placement**: not a legend-adjacent annotation (Plotly.js computes legend
item positions client-side — not queryable from Python at figure-build time,
and the three options' dive/climb entries aren't even contiguous in the
current legend order, so "under that option's group" isn't reliably
targetable). Instead: extend the existing "Option 0/1/2" toggle buttons
(`Plotting/DiveWkbSchedule.py` → `ctd_sampling/plotting.py`'s
`build_sampling_schedule_figure`) from `"method": "restyle"` to
`"method": "update"`, whose `args` take a 3-element form
`[restyle_dict, relayout_dict, trace_indices]` — so one click both
shows/hides that option's traces (as today) *and* toggles the visibility of
a pre-built text annotation for that option, via
`relayout_dict = {"annotations[K].visible": True/False, ...}`. "All"
(and "Current") hide all three text annotations. This reuses the button the
user already clicks, with no new UI element and no legend-position
guessing.

## Where the new code lives

The truck/scicon detection, file reading, and format-specific text
generation are all basestation3-specific concepts (`sg_cal_sg_ct_type`,
`mission_dir/"science"`, `validate.py`/`ScienceGrid.py` conventions) with no
analog in the self-contained `ctd_sampling` package — this logic does **not**
belong in `ctd_sampling` (kept generic/reusable, per the original migration
decision). New module: **`WkbConfigText.py`** at the basestation3 top level
(sibling to `PlotUtils.py`/`Utils.py`, not under `Plotting/` since it's a
text-generation utility, not a plot):

```python
def detect_ct_mount(dive_nc_file) -> Literal["truck", "scicon"]:
    """sg_cal_sg_ct_type==4 (Legato) + legato_time present -> scicon;
    otherwise truck (classic Seabird CT is always truck-mounted)."""

def scicon_ct_block(buckets_depths: NDArray, sampling_rate: NDArray) -> str:
    """Builds a `ct = { depth,seconds ... }` block from one option's
    buckets_depths/buckets_sampling_rate."""

def truck_science_lines(current_science_text: str, buckets_depths: NDArray, sampling_rate: NDArray) -> str:
    """Parses one representative Rev-E line from current_science_text (same
    key=value grammar as validate.science) to get the shared non-interval
    fields (gc=, turn=, sensors=, compass=, pressure=, network=, dest=,
    retries=, rate=), then emits one new line per WKB bucket with those
    fields carried over and only `depth`/`seconds=` replaced."""

def proposed_config_text(dive_nc_file, base_opts, buckets_depths, sampling_rate) -> str | None:
    """Dispatches on detect_ct_mount; reads mission_dir/"science" or
    mission_dir/"scicon.sch"; returns None (skip, no crash) if the relevant
    file doesn't exist yet."""
```

Each option's `buckets_sampling_rate` comes from `result.dive
.buckets_sampling_rate[:, option]` (the **dive** direction) — the science/
scicon.sch depth bins apply for the whole profile, not separately for dive
vs. climb, and dive is the primary/first phase, matching how the plot's
"current sampling" legend entries are already reported per-direction. Flag
for review: if you'd rather use climb's numbers, or the min/max of the two,
say so and I'll switch it — this is the one place I made a call without
asking, since three rounds of questions already covered the bigger
decisions.

## Bridge changes: Plotting/DiveWkbSchedule.py

After building the schedule figure (unchanged), for each option:
1. Call `WkbConfigText.proposed_config_text(dive_nc_file, base_opts,
   cs_wkb-derived buckets_depths, result.dive.buckets_sampling_rate[:, option])`.
2. If not None, build a monospace annotation (`<span style="font-family:
   monospace">` + `<br>`-joined lines, `xref`/`yref`="paper", positioned in
   the blank space below the two subplots, `visible=False` by default) and
   append it to the figure's annotations tuple, recording its index.
3. Extend each "Option N" button (built in `ctd_sampling/plotting.py`) from
   `"method": "restyle"` to `"method": "update"` with the 3-element args form,
   adding `{"annotations[idx_n].visible": True}` for its own text and
   `{"annotations[idx_other].visible": False}` for the other two, to both
   `args` and `args2`. "All" and "Current" buttons get relayout dicts that
   hide all three.

Since this annotation-building and button-extension work depends on both the
schedule figure's structure (`ctd_sampling/plotting.py`) and
basestation3-only data (`dive_nc_file`, `base_opts.mission_dir`), it's
easiest to keep entirely in the bridge — pass the built figure's existing
button list and annotation count into a small helper, rather than threading
basestation3 concepts into `ctd_sampling`.

## Verification

1. Add unit tests for `WkbConfigText.py`'s pure functions (`scicon_ct_block`,
   `truck_science_lines`, `detect_ct_mount`) against the real fixtures in
   `testdata/sg272_NANOOS_Feb26_tools/` (`scicon.sch`/`science` files or the
   `.cap`-derived equivalents) — confirm exact output text matches the known
   validator-accepted grammar (round-trip through `validate.science`/
   `validate.sciconsch` to confirm the generated text still validates
   cleanly, i.e. `errors == 0`).
2. Exercise `plot_wkb_schedule` end-to-end (same stand-in `base_opts`
   approach used throughout this work) against a mission directory that has
   a real `science` or `scicon.sch` file alongside the dive fixtures, and
   inspect the resulting figure's `annotations` list + button `args` for the
   three swap-in text blocks and their indices.
3. Render through headless Chrome (the reliable method established during
   the button-placement fix — kaleido was giving stale/cached static
   exports) and click through All/Current/Option 0/1/2 to confirm the text
   block appears/disappears correctly and reads as valid monospace text.
4. Full `ctd_sampling` test suite green in both repos; ruff/ty clean.
5. Copy `ctd_sampling` changes (if any land there) from glider_sampling into
   basestation3 following the established re-sync workflow; `WkbConfigText.py`
   and `Plotting/DiveWkbSchedule.py` changes are basestation3-only, committed
   there directly on `feature/wkb_sampling`.

## Outcome

Implemented as planned on `feature/wkb_sampling`, basestation3 commit
`b9b3b53` (no `ctd_sampling` changes were needed this round, so nothing to
re-sync into glider_sampling). Two deviations from the plan, both found
during verification:

- The annotation text uses Plotly's own `font: {family: "monospace"}`
  annotation property rather than an inline `<span style="font-family:
  monospace">` — Plotly's annotation text only supports a restricted HTML
  subset (`<br>`, `<b>`, `<i>`, `<a href>`, etc.), and arbitrary `<span
  style>` isn't guaranteed to be honored by its SVG text renderer.
- The initial `y=-0.05` placement (with 150px bottom margin) overlapped the
  climb subplot's "dive time [min]" x-axis title, caught by rendering
  through headless Chrome. Moved to `y=-0.13` with 320px of bottom margin,
  confirmed clear by the same method — kaleido's static image export was
  unusable for this (see the earlier button-placement fix), so all layout
  verification here went through headless Chrome screenshots, including
  literally applying each button's `args`/`args2` payload via injected JS
  to confirm the swap-in/out behavior end to end, not just the built figure
  structure.
