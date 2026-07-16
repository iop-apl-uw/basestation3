# Convert glider_sampling MATLAB code to Python

## Context

`~/work/git/glider_sampling` contains a MATLAB analysis (`glider_sampling_5_dives_v3_GS.m` + 4 helper functions) that designs a WKB-stretched CTD sampling schedule for a Seaglider from the last 5 dives of NetCDF profile data, and plots the proposed vs. current sampling-interval-vs-depth curves plus a buoyancy-frequency profile. A Python scaffold (`pyproject.toml`, `Makefile`, `.venv`, `claude/CLAUDE.md` conventions) already exists but has no source code yet, and its metadata was copied from an unrelated sibling project. The goal is a working, typed, tested Python port using the packages already declared as dependencies (`xarray`, `netCDF4`, `gsw`, `scipy`, `plotly`, `numpy`) — critically, **`gsw` (TEOS-10) replaces the legacy `seawater` toolbox** (`sw_pres`/`sw_bfrq`) per explicit instruction, and `xarray`/`netCDF4` replace the hand-rolled `read_netcdf.m`.

`octave-cli` is now installed at `/opt/homebrew/bin/octave-cli` (11.3.0, no Octave packages installed). This makes it possible to generate golden reference output directly from the original `.m` files for the self-contained numeric helpers (`bindata_AS.m`, `conv2P.m`, `nanmean_luc.m`, `nanmedian_luc.m`), which take plain arrays and have no toolbox dependency — these will be used to produce hand-picked golden-value regression tests for `binning.bin_average` and `smoothing.nan_smooth`, rather than only hand-derived cases. Running the *full* original script end-to-end for a golden pipeline comparison is a separate question, since it depends on `read_netcdf.m` (MATLAB's `netcdf.*` low-level object API — not confirmed available under Octave, which has no packages installed) and the `seawater` toolbox (`sw_pres`/`sw_bfrq` — referenced via `addpath './seawater'` but no such folder exists in this project; not yet located on disk). That full-pipeline golden comparison is left as a stretch goal, attempted opportunistically during implementation if those pieces turn out to be available/obtainable, but not a blocking requirement — the structural/invariant-based integration test described below is the baseline plan regardless.

## Source → Target mapping

| MATLAB file | Fate |
|---|---|
| `read_netcdf.m` | Replaced by `xarray.open_dataset` (CF fill-value decoding already handles the `>1e30 → NaN` masking done manually in MATLAB). `ctd_time` decodes natively to `datetime64`, so the manual `datenum`-style `mtime` conversion is dropped. |
| `nanmean_luc.m` / `nanmedian_luc.m` | Dropped entirely — direct calls to `np.nanmean(x, axis=...)` / `np.nanmedian(x, axis=...)` (MATLAB `direction` 1/2 maps to numpy `axis` 0/1). No wrapper needed. |
| `bindata_AS.m` | Ported to `binning.bin_average(x, y, bin_centers)`. Only the mean output is used anywhere in the caller, so the port returns `(mean, count)` — the MATLAB `std` output (`s`) is never consumed and is dropped rather than carried along unused. |
| `conv2P.m` | Ported to `smoothing.nan_smooth(x, kernel)`, **restricted to the 1-D column-vector case** — the only case ever invoked (kernel lengths 5 and 10, i.e. both an odd and an even kernel are exercised, so both code paths must be preserved: mirror padding via reflect, `valid` convolution, and the half-sample `interp1` re-centering for even-length kernels). The full generic 2-D/`dim` argument machinery in the original is not needed and is not ported. |
| `sw_pres`, `sw_bfrq` | Replaced with `gsw`: `p = gsw.p_from_z(-Z, lat)`; `SA = gsw.SA_from_SP(S, p, lon, lat)`; `CT = gsw.CT_from_t(SA, T, p)`; `N2, p_mid = gsw.Nsquared(SA, CT, p, lat)`. `depth_mid = -gsw.z_from_p(p_mid, lat)` replaces the `depth` mid-point output of `sw_bfrq`. |
| `glider_sampling_5_dives_v3_GS.m` | Split into `io.py` (loading), `wkb.py` (the per-cast gridding + buoyancy-frequency + WKB-stretch schedule math), `plotting.py` (the two figures, via `plotly` instead of MATLAB figures), and `cli.py` (wires it together with the script's original hardcoded parameters as defaults). |

A subtlety to preserve exactly in the buoyancy-frequency block: MATLAB computes `sqrt(bfrq)` **before** interpolating (not after), so where `N²<0` (statically unstable water) this produces a complex value; `real()` is taken after interpolation and only *actually-negative real* residual values are then masked to NaN — near-zero unstable patches interpolate toward 0 rather than NaN. The port must interpolate the complex-valued `sqrt(N²)` (real and imaginary parts separately via two `np.interp` calls, since `np.interp` doesn't accept complex input) and take `.real` afterward, then mask `< 0` to NaN, to match this behavior rather than the more "obvious" interpolate-then-sqrt approach.

## Project layout (src layout, per your answer)

```
pyproject.toml         # name/description → "glider_sampling"; add [build-system] (hatchling) +
                        # [tool.hatch.build.targets.wheel] packages=["src/glider_sampling"];
                        # add [project.scripts] glider-sampling = "glider_sampling.cli:main";
                        # fix tool.pytest pythonpath -> ["src"]; fix tool.ruff include -> src/tests
src/glider_sampling/
  __init__.py
  binning.py            # bin_average()  (port of bindata_AS.m)
  smoothing.py           # nan_smooth()   (port of conv2P.m, 1-D case only)
  io.py                  # load_dive_variables()  (replaces read_netcdf.m via xarray)
  buoyancy.py             # buoyancy_frequency() via gsw (replaces sw_pres/sw_bfrq usage)
  wkb.py                  # GriddedDives dataclass, build_dive_stack(), compute_wkb_schedule()
                           # (the core science port of the main .m script, minus plotting)
  plotting.py              # plotly figures: sampling-interval-vs-depth (dive & climb),
                           # buoyancy-frequency profile
  cli.py                   # main(): argparse wrapper reproducing the script's default
                           # parameters (sg_label=167, latest_profile=97, dz=5,
                           # buckets_depths, relative_N=[0.8,1,1.5]), writes HTML figures
tests/
  fixtures/
    p1670093.nc ... p1670097.nc   # copies of the bundled sample dives, dedicated to tests
  test_binning.py
  test_smoothing.py
  test_buoyancy.py
  test_wkb.py             # integration: run build_dive_stack + compute_wkb_schedule on the
                           # tests/fixtures/p167009{3..7}.nc copies, assert shapes/invariants
  test_cli.py
```

The 5 bundled `p1670093.nc`...`p1670097.nc` files (already the exact 5-dive window the original script defaults to: `sg_label=167`, dives 93–97) are copied into `tests/fixtures/` and tests reference that copy, keeping fixtures self-contained under `tests/` rather than reaching up to the repo root. The originals at the repo root are left in place (not moved) since the CLI's own default run (verification step 3 below) also uses them. The two stray duplicate/legacy files (`conv2P (Geoff Shilling's conflicted copy...).m`, identical to `conv2P.m`) and all the original `.m` files are left in place untouched (not deleted) — this is a port, not a migration that removes the source.

## Key implementation notes

- **`GriddedDives` dataclass** (`wkb.py`) mirrors the MATLAB `sg` struct fields (`z`, `lon`, `lat`, `time`, `pd`, `T`, `S`, `w`, `Npoints`, `dt_sampling`, `N`, `BF`, `dTdz`) as typed `numpy.typing.NDArray[np.float64]` fields, built up cast-by-cast (down/up) across the 5 dive files — this keeps a direct, line-checkable correspondence with the `.m` file for review, rather than restructuring the algorithm.
- Time handling: `io.load_dive_variables` returns `ctd_time` as `datetime64[ns]` (no manual `datenum` math needed); `wkb.py` derives elapsed seconds via `(t - t.min()) / np.timedelta64(1, "s")` where the original used `*24*3600` on day-fraction values.
- 1-indexed → 0-indexed translation is the main source of risk in the WKB-stretch block (`i_max`, bucket loops, `N_top`/`NN` point counts) — ported block-by-block against the original line numbers, with inline comments only where an off-by-one is non-obvious.
- Plotting uses `plotly` (already a dependency; `matplotlib` is not) — figures are built with `plotly.graph_objects` and returned/saved as HTML rather than requiring an interactive display, since this needs to run headless. Visual layout (colors, legend, annotated point counts, depth gridlines) mirrors the original but is not pixel-identical.
- All new functions get full type hints + Google-style docstrings per `claude/CLAUDE.md`; `pathlib.Path` used for all file args.

## Testing strategy

- `binning.bin_average` / `smoothing.nan_smooth`: golden-value regression tests generated by running `bindata_AS.m` / `conv2P.m` under `octave-cli` on small hand-picked input arrays (script the Octave call, capture its printed output, hardcode it as the expected value in the test) — plus a couple of purely hand-derived edge cases (all-NaN input, single interior NaN gap) that are easiest to reason about directly.
- `buoyancy.buoyancy_frequency`: sanity-check against a synthetic linearly-stratified T/S profile (known-sign, monotonic N² expectation) rather than exact numbers, since the reference `seawater` toolbox isn't confirmed available to cross-check against `gsw` (different equation of state, TEOS-10 vs EOS-80, so exact parity isn't expected/meaningful anyway).
- `wkb` integration test: run the full pipeline on the `tests/fixtures/*.nc` copies and assert structural invariants — output shapes match `(len(Z), n_casts)`, `dt_new` stays within a sane positive range, `N_new` matches `round(N * relative_N)`, no unexpected all-NaN columns.
- `cli`: smoke test that `main()` runs end-to-end against `tests/fixtures/*.nc` and produces the expected HTML output file(s).
- Run `uv run ruff check --fix`, `uv run ruff format`, `uv run ty check`, and `uv run pytest --cov --cov-report term-missing` (per the existing `Makefile`) before calling this done; aim for the 85%/100% coverage targets in `claude/CLAUDE.md`.

## Verification

1. `cd ~/work/git/glider_sampling && uv sync`
2. `make all` (ruff fmt/lint, `ty check`, `pytest --cov`)
3. `uv run glider-sampling` (or `uv run python -m glider_sampling.cli`) against the bundled sample files → confirm it runs end-to-end and produces the two HTML figures; open one to visually sanity-check it resembles the original plot (sampling interval vs. depth curves, buoyancy frequency profile).
