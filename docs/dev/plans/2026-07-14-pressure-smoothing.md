# Add optional truck-pressure smoothing + auto slope-correction

## Coding standards

All new/modified Python in this task should have type hints (where practical — matching the
style already used in `Utils2.py`/newer parts of `Utils.py`) and Google-style docstrings
(`Args:`/`Returns:`/`Raises:` sections, matching e.g. `tests/testutils.py:run_mission` or
`MakeDiveProfiles.py:make_dive_profile`).

## Context

Seaglider dive processing (`MakeDiveProfiles.py`) derives the vehicle's ("truck") pressure
signal, `sg_press_v` (dbar), from raw depth/pressure counts. It is somewhat noisy at the raw
sample rate, and its calibration slope can drift. This task adds two related, independently
switchable post-processing steps, applied in a fixed order — **smooth, then slope-correct** —
right after `sg_press_v` is computed, before it becomes the netCDF `"pressure"`/`"depth"`
variables:

1. **Smoothing** (`smooth_truck_pressure`): a median-filter + Savitzky-Golay hybrid, based on
   the prototype in `dive_smooth10.py` (not the fancier multi-segment/derivative-split logic
   later in that script, which is explicitly left for a future pass on the `dz/dt` trace).
2. **Slope auto-correction** (`depth_slope_correction_gold_standard`): rather than the user
   hand-tuning `depth_slope_correction` by trial and error, they can instead name an existing
   netCDF pressure variable (e.g. `ad2cp_pressure`, from the AD2CP ADCP) to treat as ground
   truth, and the code fits + applies a multiplicative slope correction against it.

Both are opt-in (default off) via new `sg_calib_constants.m` variables. The original,
unmodified signal is preserved as a new `pressure_raw` netCDF variable whenever either step
actually changes it, so it can still be inspected/compared. `Plotting/DivePlot.py` needs a
`depth_raw` trace (derived from `pressure_raw`) and a `dz_dt_raw` trace (only when
`pressure_raw` is present), and the calib-constants example/help file
(`sg000/sg_calib_constants.m`) needs the new knobs documented.

**Important scope note**: `sg_press_v`/`sg_depth_m_v` are not just cosmetic display values —
they feed forward within `MakeDiveProfiles.py` into salinity/density corrections and sound
velocity (`seawater.svel`/`gsw.sound_speed`, via `ctd_press_v`/`ctd_sg_press_v` interpolations)
and into the GSM dead-reckoning flight model, and `"pressure"` is separately consumed
downstream by `FlightModel.py` (hydro parameter fits), `GliderDAC.py` (external delivery), and
`MakeMissionTimeSeries.py`. So enabling either new flag changes real oceanographic products,
not merely a plot trace — this is what the task explicitly asks for, but it must be documented
prominently (in the calib-const help text and the `pressure_raw` netCDF description) so a user
enabling a flag understands the full effect. Both flags default to off, so the change is
opt-in only.

## Implementation

### 1. New helpers — `Utils.py`

Add `import scipy.signal` at the top (scipy is already a project dependency;
`TempSalinityVelocity.py` already imports it this way elsewhere in the repo — the idiomatic
style to match, rather than `from scipy.signal import ...`). Add two functions near
`medfilt1`/`ctr_1st_diff` (the closest existing signal-processing helpers), fully type-hinted
with Google-style docstrings:

```python
def smooth_pressure(
    epoch_time_s_v: NDArray[np.float64],
    press_v: NDArray[np.float64],
    window_secs: float = 42.0,
    polyorder: int = 3,
) -> NDArray[np.float64]:
    """Smooths a pressure time series with a median-filter + Savitzky-Golay hybrid.

    Based on the padding/median/savgol approach prototyped in dive_smooth10.py, adapted
    to operate on a seconds time base rather than minutes.

    Args:
        epoch_time_s_v: sample times, seconds since epoch.
        press_v: pressure samples (dbar), same length as epoch_time_s_v.
        window_secs: Savitzky-Golay window length, in seconds.
        polyorder: Savitzky-Golay polynomial order.

    Returns:
        Smoothed pressure array, same shape as press_v. Returns press_v.copy() unchanged
        (with a logged warning) if the profile is too short for the requested window or
        contains NaNs.
    """
```

Logic: compute median sample interval from `epoch_time_s_v`; convert `window_secs` (and a
median pre-filter window, a fixed fraction of it, e.g. `window_secs / 3`) to odd point counts,
clamped to `<= len(press_v)`; guard the `polyorder < window_length` constraint required by
`savgol_filter`. If the profile is too short to support the window, or contains any NaNs (the
median/savgol filters propagate NaNs through the whole padded window), log a warning and
return `press_v.copy()` unchanged rather than raising. Otherwise pad both ends via linear
extrapolation using the mean slope over a small window at each end, run
`scipy.signal.medfilt`, then `scipy.signal.savgol_filter(..., mode="constant")`, then strip
the padding back off.

```python
def fit_pressure_slope(
    time_a_s_v: NDArray[np.float64],
    press_a_v: NDArray[np.float64],
    time_b_s_v: NDArray[np.float64],
    press_b_v: NDArray[np.float64],
) -> float | None:
    """Fits a multiplicative slope correction between two pressure time series.

    Interpolates press_b onto time_a's grid (restricted to the overlapping time range),
    then fits press_b_interp = slope * press_a + intercept via np.polyfit (matching the
    linear-fit idiom already used elsewhere in this repo, e.g. QC.py/TempSalinityVelocity.py),
    keeping only the slope (an intercept/offset is depth_bias's job, not this feature's).

    Args:
        time_a_s_v: epoch seconds for press_a_v (the signal to be corrected).
        press_a_v: pressure (dbar) to be corrected.
        time_b_s_v: epoch seconds for press_b_v (the "gold standard" reference).
        press_b_v: reference pressure (dbar).

    Returns:
        The fitted slope, or None if there's insufficient time overlap to fit (logs a
        warning in that case).
    """
```

### 2. New optional calib constants — `MakeDiveProfiles.py`

In the defaults dict inside `sg_config_constants()` (the dict starting around line 320,
alongside `"use_auxpressure": 1,` at line 367), add:

```python
"smooth_truck_pressure": 0,                    # enable flag (non-zero to enable)
"smooth_truck_pressure_window_secs": 42.0,     # Savitzky-Golay window length, seconds
"smooth_truck_pressure_polyorder": 3,          # Savitzky-Golay polynomial order
"depth_slope_correction_gold_standard": "",    # name of a netCDF pressure var to treat as ground truth
```

These get auto-populated via the existing `update_calib_consts` closure (lines 173-189), so
downstream code can safely read `calib_consts["smooth_truck_pressure"]` etc. without a
KeyError even if the mission's `sg_calib_constants.m` doesn't set them.

### 3. Unified pressure post-processing helper — `MakeDiveProfiles.py`

`sg_press_v` is computed and stored into `results_d` (as `"pressure"`/`"depth"`) at exactly
4 places, each with the identical tail:

```python
sg_press_v *= dbar_per_psi  # convert to dbar
if not base_opts.use_gsw:
    sg_depth_m_v = seawater.dpth(sg_press_v, latitude)
else:
    sg_depth_m_v = -1.0 * gsw.z_from_p(sg_press_v, latitude, 0.0, 0.0)
results_d.update({"pressure": sg_press_v, "depth": sg_depth_m_v})
```

- Legato branch: `sg_press_v *= dbar_per_psi` at line 4249, `results_d.update` at 4255-4260
- Seabird/scicon (Kistler/truck) branch: line 4580, `results_d.update` at 4607-4612
- GPCTD (pumped) branch: line 4833, `results_d.update` at 4838-4843
- Exception/GSM-fallback branch: line 5008, `results_d.update` at 5014-5019

(A 5th, transient `sg_press_v` computation at lines 3060-3121, used only for aux-compass
calibration and `del`eted at line 3121, is never stored in `results_d` — leave it alone.)

`MakeDiveProfiles.py` is one large function body from `make_dive_profile` (line 2805) through
all 4 sites (no nested `def`s in between), so `explicit_calib_consts` — the dict of *only* the
values the user actually wrote in `sg_calib_constants.m`, before defaults are merged into
`calib_consts` (see `calib_consts = explicit_calib_consts.copy()` at lines 2931-2933) — is
directly in scope everywhere it's needed, with no threading required. This is exactly the
"was `depth_slope_correction` explicitly specified" check the precedence rule needs.

Add one combined helper (near `compute_kistler_pressure`, line ~1279) that does smoothing
then slope-correction, in that order, and reports whether anything actually changed (so
`pressure_raw` is only stored when it would differ from `"pressure"`):

```python
def process_truck_pressure(
    calib_consts: dict,
    explicit_calib_consts: dict,
    epoch_time_s_v: NDArray[np.float64],
    press_v: NDArray[np.float64],
    results_d: dict,
) -> tuple[NDArray[np.float64], NDArray[np.float64] | None]:
    """Applies optional truck-pressure smoothing, then optional slope auto-correction.

    Order matters: smoothing (if enabled) runs first, then slope correction (if applicable)
    runs on the (possibly smoothed) result — matching the sg_calib_constants.m-documented
    processing order.

    Args:
        calib_consts: calibration constants, with defaults already merged in.
        explicit_calib_consts: only the calib consts the user actually set, used to check
            whether depth_slope_correction was explicitly specified (which always wins over
            auto-correction).
        epoch_time_s_v: truck sample times, epoch seconds, for press_v.
        press_v: truck pressure (dbar) to process.
        results_d: the in-progress results dict, consulted for the gold-standard reference
            variable (e.g. "ad2cp_pressure"/"ad2cp_time") if depth_slope_correction_gold_standard
            is set.

    Returns:
        (press_v, press_raw_v): press_v is the (possibly smoothed/slope-corrected) pressure;
        press_raw_v is a copy of the original input, or None if neither step changed anything
        (so callers can skip adding a redundant pressure_raw result).
    """
    press_raw_v = press_v.copy()
    changed = False

    if calib_consts["smooth_truck_pressure"]:
        press_v = Utils.smooth_pressure(
            epoch_time_s_v,
            press_v,
            window_secs=calib_consts["smooth_truck_pressure_window_secs"],
            polyorder=int(calib_consts["smooth_truck_pressure_polyorder"]),
        )
        changed = True

    gold_standard = calib_consts["depth_slope_correction_gold_standard"]
    if gold_standard and "depth_slope_correction" not in explicit_calib_consts:
        gold_standard_time = gold_standard.replace("_pressure", "_time")
        if gold_standard in results_d and gold_standard_time in results_d:
            slope = Utils.fit_pressure_slope(
                epoch_time_s_v, press_v, results_d[gold_standard_time], results_d[gold_standard]
            )
            if slope is not None:
                log_info(
                    "Applying auto-computed depth_slope_correction=%.5f from %s"
                    % (slope, gold_standard)
                )
                press_v = press_v * slope
                changed = True
        else:
            log_warning(
                "depth_slope_correction_gold_standard=%s specified, but %s/%s not found"
                % (gold_standard, gold_standard, gold_standard_time)
            )

    return press_v, (press_raw_v if changed else None)
```

At each of the 4 sites, right after `sg_press_v *= dbar_per_psi` and before computing
`sg_depth_m_v` (so `depth` reflects the fully processed pressure), insert:

```python
sg_press_v, sg_press_raw_v = process_truck_pressure(
    calib_consts, explicit_calib_consts, sg_epoch_time_s_v, sg_press_v, results_d
)
```

(`sg_epoch_time_s_v` is defined once at line 3274, well before all 4 sites.)

Then extend each `results_d.update({...})` call to conditionally include the raw vector:

```python
result_vars = {"pressure": sg_press_v, "depth": sg_depth_m_v}
if sg_press_raw_v is not None:
    result_vars["pressure_raw"] = sg_press_raw_v
results_d.update(result_vars)
```

This keeps netCDF output byte-for-byte unchanged for the default (both features disabled)
case — no spurious duplicate `pressure_raw` variable when it would just equal `pressure`.

**Feature interaction / precedence**: if the user explicitly sets `depth_slope_correction` in
`sg_calib_constants.m`, it always wins — it's already been applied to the raw eng-depth-counts
conversion at the top of each branch's formula (unchanged), and `process_truck_pressure` skips
auto-correction entirely (`"depth_slope_correction" not in explicit_calib_consts` guards it).
If only `depth_slope_correction_gold_standard` is set, the auto-fitted slope is applied as a
post-hoc multiplicative correction on the (possibly smoothed) `sg_press_v` — this works
uniformly across all branches/sub-cases, including the one where `sg_press_v` comes directly
from onboard-computed pressure counts and never touches `depth_slope_correction` at all today.

**Feasibility note**: `ad2cp_pressure`/`ad2cp_time` (and `cp_pressure`/`cp_time`) are read from
`results_d` already, deeper in the same Seabird/scicon branch (`MakeDiveProfiles.py:4690-4692`,
for a different purpose — CTD pressure-source selection), confirming scicon/ADCP instrument
data is loaded into `results_d` before the CT-type dispatch (Legato/Seabird/GPCTD/fallback are
mutually-exclusive alternatives for the same dive, not sequential steps), so the reference
variable is available at all 4 sites when present in a mission at all.

### 4. Register new netCDF variable/calib metadata — `BaseNetCDF.py`

Next to the existing `"pressure"` entry (line 2918-2926), add:

```python
"pressure_raw": [
    "f",
    "d",
    {
        "units": "dbar",
        "description": "Uncorrected sea-water pressure at pressure sensor, prior to "
        "smooth_truck_pressure/depth_slope_correction_gold_standard processing (present "
        "only when one of those was applied). Note: when either is enabled, the primary "
        "pressure/depth variables (and downstream salinity, density, sound-velocity "
        "corrections and FlightModel fits) reflect the processed signal, not this raw one.",
    },
    (nc_sg_data_info,),
],
```

Next to `"sg_cal_legato_use_truck_pressure"` (lines 1519-1526), add 4 sibling scalar entries
(3 for smoothing, `"d"` double type; 1 for the gold-standard reference name, `"c"` char type —
matching the existing string-valued `"sg_cal_calibcomm"`/`"sg_cal_mission_title"` convention):

```python
"sg_cal_smooth_truck_pressure": [
    False, "d",
    {"description": "Enable median+Savitzky-Golay smoothing of the truck pressure/depth signal (non-zero to enable; default 0/off). This also affects downstream salinity/density/sound-velocity corrections and FlightModel fits, not just the displayed depth/pressure — the pre-processing signal is preserved as pressure_raw."},
    nc_scalar,
],
"sg_cal_smooth_truck_pressure_window_secs": [
    False, "d",
    {"description": "Savitzky-Golay smoothing window length, in seconds, used when smooth_truck_pressure is enabled (default 42)."},
    nc_scalar,
],
"sg_cal_smooth_truck_pressure_polyorder": [
    False, "d",
    {"description": "Savitzky-Golay polynomial order used when smooth_truck_pressure is enabled (default 3)."},
    nc_scalar,
],
"sg_cal_depth_slope_correction_gold_standard": [
    False, "c",
    {"description": "Name of a netCDF pressure variable (e.g. ad2cp_pressure) to treat as ground truth and auto-fit a depth_slope_correction against (applied after smooth_truck_pressure, if also enabled). Ignored if depth_slope_correction is explicitly set — that always wins."},
    nc_scalar,
],
```

### 5. `Plotting/DivePlot.py` — new traces

- After the existing `depth` load (lines ~320-332), read `pressure_raw` if present and derive a
  `depth_raw` array from it (dbar treated as ≈ meters — `DivePlot.py` has no `latitude`/`gsw`/
  `seawater` in scope for a proper pressure→depth conversion, and exactness isn't the point of
  this comparison trace; positive-down, matching `depth`'s own sign convention before its later
  negation for plotting):
  ```python
  depth_raw = None
  if "pressure_raw" in dive_nc_file.variables:
      depth_raw = dive_nc_file.variables["pressure_raw"][:]
  ```
- Right alongside the existing `dz_dt = Utils.ctr_1st_diff(-depth * 100, depth_time - start_time)`
  (line 341, computed **before** `depth` is rescaled for plotting), add:
  ```python
  dz_dt_raw = None
  if depth_raw is not None:
      dz_dt_raw = Utils.ctr_1st_diff(-depth_raw * 100, depth_time - start_time)
  ```
- After `zscl` is chosen and `depth` is rescaled (`depth = (depth * -1.0) / zscl` at line 359),
  rescale `depth_raw` the same way:
  ```python
  if depth_raw is not None:
      depth_raw = (depth_raw * -1.0) / zscl
  ```
- Add a `depth_raw` trace next to the existing guarded `ctd_depth` trace (lines 413-431),
  following the same guarded/`legendonly` pattern (label it clearly as derived from raw
  pre-processing pressure, given the dbar≈m approximation):
  ```python
  if depth_raw is not None:
      valid_i = np.logical_not(np.isnan(depth_raw))
      fig.add_trace({
          "y": depth_raw[valid_i],
          "x": depth_time[valid_i],
          "meta": (depth_raw * zscl)[valid_i],
          "name": f"Depth raw, pre-processing ({zscl:.0f}m)",
          "type": "scatter",
          "xaxis": "x1",
          "yaxis": "y1",
          "visible": "legendonly",
          "mode": "lines+markers",
          "marker": {"symbol": "cross", "size": 3},
          "line": {"dash": "solid", "color": "Gray"},
          "hovertemplate": "Depth raw (pre-smoothing/slope-correction pressure, dbar≈m)<br>%{meta:.1f} m<br>%{x:.2f} mins<br><extra></extra>",
      })
  ```
- Add a `dz_dt_raw` trace next to the existing `dz_dt` trace (lines 436-450):
  ```python
  if dz_dt_raw is not None:
      valid_i = np.logical_not(np.isnan(dz_dt_raw))
      fig.add_trace({
          "y": dz_dt_raw[valid_i],
          "x": depth_time[valid_i],
          "name": "Vert Speed dz/dt raw (cm/s)",
          "type": "scatter",
          "xaxis": "x1",
          "yaxis": "y1",
          "visible": "legendonly",
          "mode": "lines",
          "line": {"dash": "solid", "color": "CadetBlue"},
          "hovertemplate": "Vert Speed dz/dt raw<br>%{y:.2f} cm/sec<br>%{x:.2f} mins<br><extra></extra>",
      })
  ```

### 6. Document the new calib constants — `sg000/sg_calib_constants.m`

Near `depth_slope_correction` (line 19-21), add, following the file's existing
`%PARAM name = default;` convention:

```
% Smooth the truck (main pressure sensor) pressure/depth signal using a
% median + Savitzky-Golay hybrid filter. Set to 1 to enable. This also feeds
% forward into salinity/density/sound-velocity corrections and FlightModel
% fits, not just the displayed depth/pressure - the pre-processing signal is
% preserved as the pressure_raw netCDF variable.
%PARAM smooth_truck_pressure = 0;
%PARAM smooth_truck_pressure_window_secs = 42.0;
%PARAM smooth_truck_pressure_polyorder = 3;

% Rather than hand-tuning depth_slope_correction, name an existing netCDF
% pressure variable here (e.g. ad2cp_pressure, from an AD2CP ADCP) to treat as
% ground truth; a depth_slope_correction will be auto-fit against it (applied
% after smooth_truck_pressure, if that is also enabled). Ignored if
% depth_slope_correction is explicitly set above - that always wins.
%PARAM depth_slope_correction_gold_standard = 'ad2cp_pressure';
```

## Testing

Follow the pattern in `tests/test_MakeDiveProfiles.py` / `tests/testutils.py::run_mission`,
but in a new test file, `tests/test_pressure_smoothing.py`. In addition to the mission-level
integration test below, add direct unit tests for `Utils.smooth_pressure`,
`Utils.fit_pressure_slope`, and `MakeDiveProfiles.process_truck_pressure` against synthetic
arrays (no netCDF/mission fixture needed) — a full mission reprocess can't cheaply exercise
every branch (short/NaN inputs, missing reference variable, explicit-const precedence), so
check coverage after the integration test and add whatever direct calls are needed to close
the gap. Aim for 100% line/branch coverage on these 3 functions; treat 95%+ as the acceptable
floor. Cases worth covering directly:

- `smooth_pressure`: normal case (smoothed output differs from input, same shape); profile
  shorter than the window (returns unchanged + warning); input containing NaNs (returns
  unchanged + warning).
- `fit_pressure_slope`: normal case (recovers a known injected slope from synthetic data);
  no time overlap between the two series (returns `None` + warning).
- `process_truck_pressure`: all 4 combinations of smoothing on/off × gold-standard on/off;
  gold-standard variable name missing from `results_d` (warns, no correction, `press_raw_v`
  reflects whatever else changed); explicit `depth_slope_correction` present in
  `explicit_calib_consts` suppresses auto-correction even when a gold-standard is set; neither
  feature enabled returns `press_raw_v is None`.

- New test data directory: `testdata/sg180_Shilshole_01Jul26_pressure_smoothing/`, populated
  from `/Users/gbs/work/seagliders/sg180_Shilshole_01Jul26/` by copying just `p1800001.nc`
  through `p1800006.nc`, `comm.log`, and `sg_calib_constants.m` (no raw `.eng`/`.log`/`.dat`
  files — confirmed the existing `p180*.nc` files already carry `ad2cp_pressure`/`ad2cp_time`,
  needed both for the slope-correction feature and as the "gold standard" comparison signal
  for validation).
- Since only netCDF files (not raw eng/log) are supplied, drive `MakeDiveProfiles.main` with a
  dive-number argument (not `--force`) to exercise the "Loading data from netCDF files"
  reprocess path (matching `test_MakeDiveProfiles.py`'s `("2", ["Loading data from netCDF
  files"], [""])` case) — this re-derives `sg_press_v` from data embedded in the existing
  `.nc` file, so no raw instrument files are needed.
- Write a mission-specific `sg_calib_constants.m` override (or edit the copied one via the
  test's `pre_test_hook`) enabling `smooth_truck_pressure = 1` for one run and
  `depth_slope_correction_gold_standard = 'ad2cp_pressure'` for another, then use
  `testutils.run_mission(...)` to process, then open the resulting netCDF directly
  (`netCDF4.Dataset`) and assert:
  - `pressure_raw` is present and equals the original (unsmoothed/uncorrected) `pressure`.
  - With smoothing on: `pressure` is smoother than `pressure_raw` (e.g. lower total variation
    / std of first differences) but still tracks it closely (e.g. correlation or max absolute
    deviation within a tolerance).
  - With gold-standard slope correction on: `pressure` (interpolated to `ad2cp_time`) is a
    closer match to `ad2cp_pressure` than `pressure_raw` was (e.g. lower RMS residual after
    interpolation), validating the fit actually improved slope agreement.
  - With neither flag set: output is unchanged from today (no `pressure_raw`, `pressure`
    identical to before) — a regression guard for the default path.

## Verification

- `make rufflint` — catch style/typo issues.
- Run the new `tests/test_pressure_smoothing.py` (and `make test` generally) before checkin.
- Check coverage on `Utils.smooth_pressure`, `Utils.fit_pressure_slope`, and
  `MakeDiveProfiles.process_truck_pressure` specifically (e.g. `pytest --cov=Utils
  --cov=MakeDiveProfiles --cov-report=term-missing`); add direct-call test cases for any
  uncovered branches until at least 95% (ideally 100%) is reached on these 3 functions.
- Run `DivePlot` (`plot_diveplot`) against both a default-processed and a
  smoothing/slope-corrected netCDF and visually confirm: no `depth_raw`/`dz_dt_raw` traces on
  the unprocessed file; both present (legend-only) and sensible on the processed one.
- Do not stage or commit changes — leave that to the user.

## Post-approval correction (found during test-writing)

The original design (above) planned to gate gold-standard auto-correction on
`"depth_slope_correction" not in explicit_calib_consts`, assuming that dict held only
user-set values. Testing against a real reprocess-from-netCDF mission showed this is false:
`load_dive_profile_data()` applies `sg_config_constants()` (merging in every default) onto the
very dict that becomes `explicit_calib_consts`, so the key is always present after defaults
merge - the auto-correction path was unreachable in practice.

**Fix actually implemented**: `process_truck_pressure` no longer takes an
`explicit_calib_consts` parameter. Instead, a module-level `DEPTH_SLOPE_CORRECTION_DEFAULT =
1.0` constant (matching the default already in `sg_config_constants()`'s config dict) is
compared against `calib_consts["depth_slope_correction"]`; auto-correction only runs if that
value still equals the default. All 4 call sites and the direct unit tests were updated to
match (`process_truck_pressure(calib_consts, epoch_time_s_v, press_v, results_d)`, no third
`explicit_calib_consts` argument).

Also found and fixed during testing: `Utils.fit_pressure_slope` crashed on masked arrays
(`scipy.interpolate.interp1d` rejects them outright), which is exactly what
`results_d[gold_standard]`/`results_d[gold_standard_time]` are when reprocessing from an
existing netCDF file. Fixed by normalizing all 4 input arrays via `np.ma.filled(x, np.nan)` at
the top of `fit_pressure_slope`, plus an added NaN-validity filter before the `np.polyfit` call.

## Second post-approval correction (found via user's manual `test_Base.py` run)

Giving `depth_slope_correction_gold_standard` a `""` (empty string) default in the
`sg_config_constants()` defaults dict was itself a bug: since that dict's defaults get merged
into `explicit_calib_consts` (see the first correction above), the empty default was present
for *every* mission, and the "write explicit sg_calib_constants to netCDF" loop
(`MakeDiveProfiles.py`, `for key, value in list(explicit_calib_consts.items())`) tried to write
it every time. `BaseNetCDF.create_nc_var` has a real, correct guard against creating
zero-length string netCDF variables (`BaseNetCDF.py:4328-4333`: "NetCDF libraries do not handle
empty string values and cause processing of netCDF files with such strings to crash/halt"), so
every single mission reprocess logged `ERROR: Must supply a non-empty value for string-valued
NC var (sg_cal_depth_slope_correction_gold_standard)` - which broke `tests/test_Base.py`,
`test_BaseHooks.py`, `test_Reprocess.py`, `test_BaseADCP.py`, and `test_BaseADCPMission.py`
(all of which fail their tests on any unexpected ERROR-level log line).

**Fix**: removed `"depth_slope_correction_gold_standard": ""` from the defaults dict entirely
(with a comment explaining why) - it's now simply *absent* from `calib_consts` unless a user
actually sets it in their `sg_calib_constants.m`. `process_truck_pressure` reads it via
`calib_consts.get("depth_slope_correction_gold_standard", "")` instead of direct indexing.
Confirmed fix by re-running the previously-failing test files - all now pass.
