# Changelog

All notable changes to this project are documented in this file.

## [3.0.8] - Unreleased

### User-Facing Changes

#### Data processing / calibration
- Added a `sg_calib_constants.m` validator (new `CalibConstCheck.py`), wired into the selftest HTML output as a new "sg_calib_constants.m validation" section; migrated the CTD-configuration cross-checks previously buried in `selftest.sh` into this checker, and expanded the `sg000/sg_calib_constants.m` reference file to document all known variables with improved formatting (`3b6d8c0`)
- Fixed a bug where, when reprocessing from an existing netCDF file, an edit to `sg_calib_constants.m` (or the `.log`/`.eng`/directives files) made in the same filesystem timestamp tick as the netCDF file could be silently ignored, because the reload check required a strictly-newer mtime (`9e92f1c`)
- Fixed a regression in parsing old-style `tcm2mat.cal` files where magnetometer calibration returned before constructing the pitch-dependent PQR correction, so the correction was never applied (`3b6d8c0`)
- Added optional pressure smoothing and auto-calibration parameters in `sg_calib_constants.m` to smooth noisy truck pressure readings and auto-correct sensor drift against a reference sensor (e.g. AD2CP); original unsmoothed data is preserved as `pressure_raw` (`c98379d`, `759a0c0`, `ab471c5`)
- `depth_raw` is now visible by default in output (`88aace4`)
- Added `sigma_t` as a migratable vector (`e53e664`)
- Added direct specification of output precision in `.eng` files (`16d25ef`)
- Fixed compass calibration output formatting (`1f7124b`)
- Fixed a bug in science file creation (`846cc9f`)
- Fixed minute formatting for `nc_ISO8601_date` (`02095ea`)
- Issue a clear error instead of a traceback when there are no valid depth points (`1892f14`)

#### Sensor / driver support
- Handle the new `legatoPollv4` driver (`76f2e03`)
- Handle the mission `coordinateSystem` variable in AD2CP `.mat` files (`23e6bc2`, `aa7d5fe`, `713114c`)
- Added compressed namespace support for serdev Tridente (`7ecd684`)
- Added new Suna columns; fixed Suna color/traces (`f2ddfc9`, `c4ba83d`)
- New extension to correct a slow SciCon clock, and to propagate SciCon eng file start/stop times to the netCDF (`4187c0b`, `88a773a`)
- New extension hook for handling sensor data issues during dive-profile load (`54cad00`)

#### CLI / workflow behavior
- `.ftps` support added (`2193ad7`)
- Removed the `--reprocess` and `--make_dive_profiles` options — dive-profile reprocessing is now always on, simplifying the CLI (`7200f04`, `ecb9193`)
- Removed `FullPath`/`FullPathTrailingSlash`; general CLI interface cleanup (`7d35f67`)
- Base now exits cleanly if it can't open/process `comm.log`, instead of failing obscurely (`c1314f2`)
- File backup moved to `GliderEarlyGPS`; default comm-session selection changed to "last comm session" rather than "last complete comm session" (`24df2f7`)
- Login now cleans up stray `upload_files` in place and reports errors for problem files (`aacfcdd`)
- Removed the data mask that filtered points before plotting, improving deck-dive and diagnostic plots (`eb2cdba`)
- Added timeouts around plot generation so a single bad plot can't hang a run (`38fcfd5`, `3978018`)

#### Visualization (map/plots)
- Added an option to generate FlightModelSystem plots as interactive plotly figures, in addition to the existing matplotlib output (`96c71b4`)
- Added help links across all plot files, plus plot-help cleanup (`d252982`, `ab929ce`)
- Timeline scrubber switched to a double-handled time slider; extended to glider tracks (`d573f93`, `297bcca`)
- Map app: glider icons/tails now show color info from notifications; active mission used as default when otherwise unspecified (`fab176b`)
- Improved toolbar aesthetics (`297bcca`)
- Added total bytes/dive, total seconds/dive, and total session seconds traces (`63ee2ce`)
- Various glider-track fixes (`3c66a99`)
- Fixed parquet-directory variable dumping and handling of stray files in that directory (`b18256e`, `e992cbb`)
- Corrected a channel name (`dad390a`)

#### Documentation
- New sensor integration guide, with formatting fixes for GitHub rendering (`0711f02`, `bff76d9`, notes on configurable plotting services `f324c30`, plus several markdown/link fixes)
- Added an example extension demonstrating plot generation (`a7a675c`)

### Engineering / Internal Changes

- **Large-scale `pathlib` migration**: replaced string/`os.path`-based path handling across the codebase (`MoveData`, `netcdf_filename`, config, `base_log`, `mission_dir`, and many call sites) — roughly 20+ commits from May through June
- **Typing pass**: added type coverage across extensions and core modules, removed the `mypy` toolchain in favor of `ruff`'s type checking, multiple rounds of type fixes (`bda4151`, `4872738`, `a8c1f2f`, `dc0e5f8`, `b7d85d5`, `c143ca5`, etc.)
- Updated `ruff` version and did a full type-annotation pass; removed the blanket `unresolved-attribute` ignore rule, handling `BaseOptions` as a special case (`9f75a7f`, `79799b3`, `7b8d5fa`)
- Added substantial new test coverage, including CLI interface tests, pressure-smoothing test cases, Legato selftest variants, the new calib-constants checker, FlightModel plotly plots, and a system-dependencies check (`7d35f67`, `759a0c0`, `96c71b4`, `3b6d8c0`)
- CI pipeline, `Dockerfile`, and `Readme.md` updated to install `tcsh`, `bc`, and `dos2unix` — runtime dependencies of `selftest.sh` that were previously undocumented and missing from a minimal install (`3b6d8c0`)
- Removed a completed dev-plan doc (`0a726bc`)
- Removed `notify_vis` from `BaseRunner`; added an option to suppress vis notifications to support unit tests (`ffb8089`, `3ec07f3`)
- Backup naming fix for files with existing extensions (`2d229f9`)
- Misc. cleanup: removed unused arguments, unneeded pathlib constructors, debug logging, symlink resolution fix (`.absolute` → `.resolve`) (`e35647a`, `975eb82`, `d5b19c7`, `9d464ef`, `339a1f0`)
- `.gitignore` tightened to local-only directories; updated sample `.conf` file (`4114b21`, `1552aae`, `f893824`)
- Documentation build added (`e4f0290`)
- Version bumped to 3.0.8 (`d8aa29b`, `bea719f`, `96be24b`)

## [3.0.7] and earlier

See git history prior to this file's introduction.
