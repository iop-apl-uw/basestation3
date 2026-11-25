# Changelog

All notable changes to this project are documented in this file.

## [3.0.9] - 2026-11-25

### Breaking / Upgrade Notes
- **Python 3.14 is now required** (`requires-python = ">=3.14,<3.15"`), along with major dependency updates: numpy 2.5, scipy 1.18, plotly 6.8, kaleido 1.3, xarray 2026.7, pydantic 2.13 (`ead188c`, `31a415e`)
- Chromium/Playwright are no longer runtime dependencies - thumbnails render without Chrome; Chromium is only needed for CI (`1fc0ee7`, `914b510`, `8b087be`)
- FlightModel's default plot engine is now plotly; the two plot-timeout options are deprecated (`914b510`)
- `BaseLogin.py` merged into `GliderEarlyGPS.py` (`e95698f`)
- A config-file value that won't convert (boolean, path) is now an error rather than being silently dropped (`9966030`); option definitions are checked for bad types and conflicts (`c5227fb`); `--mission_dir` must be an existing, readable directory (`02772d4`)
- `rawrcv` read timeout raised from 20 s to 40 s - rebuild/redeploy `rawxfer` to ride through ~30 s RUDICS gateway stalls (`97feda4`)

### User-Facing Changes

#### Data processing / calibration
- Malformed GPS date/times (e.g. under-ice `DDMM,HHMM` nav fixes) are marked invalid instead of guessed at; MakeDiveProfiles times such a fix from `$RAFOS_FIX` and marks it bad; CommLog drops it for that call (`548b654`)
- A `$GPS2` without magnetic variation takes `$GPS1`'s or `$GPS`'s, instead of failing the dive (`798de20`); a missing `$GPS` falls back correctly (`fda58d2`)
- FlightModel:
  - `hydro_model` converges in up to 100 iterations (was 61), fixing long runs of "Unable to determine vbdbias" (`037e35a`)
  - A dive earlier than every dive in the flight database starts from the defaults instead of stopping FlightModel for the rest of the mission (`0199f09`); fixed a crash on out-of-order dives (`a69cd4c`)
  - The flight database is rebuilt when `sg_calib_constants.m` assumptions change (`3a830be`)
  - Uses `velo_NNNN.mat` files (reshape bug) and fixed decimation without salinity QC (`ddf909f`)
- Truck sensor timeout counts/times now reach the netCDF for WETlabs and QSP2150 (`03044eb`) and RBR Tridente (`e5f442e`)
- Partial dives: interpolated and binned even when later depths are still NaN, kept consistent, and GSM surface drift guarded (`4d3b1b4`, `8362ae5`)
- `solve_flare_apogee_speed` no longer fails the dive on short flare/apogee intervals; fixed auxB pressure, `interp_gc_temperatures` and garbled GPS line handling (`71cec1f`, `d651513`)
- Interpolated depth/lat/lon are marked `QC_INTERPOLATED` in GliderDAC output (`40fd0d5`); GliderDAC templates are validated and later templates override earlier ones (`5f6b91a`, `8b96da7`)
- Non-numeric calibration constants are rejected where they're read; `mass` is checked (`ac48d88`); a `legato_sealevel` mismatch is flagged as critical in the selftest calib check (`4941da8`)
- `mission_title` falls back to `UNKNOWN` when missing from `sg_calib_constants.m` (`e45c1aa`)
- Damaged data is skipped with one logged error instead of a traceback: garbled scicon rows, cast headers and logger header times, data files and sensors with missing columns or header lines, malformed `.nlog` lines (`f152d37`, `4886185`, `bbbdfd4`, `1091b3f`, `d6b4f08`, `d3cded7`)
- NaN-safe energy estimates, endurance, magcal and `$GC` handling (`ebec012`, `d0c63e6`, `95247cd`, `1917788`, `390b922`, `133285b`, `18e283b`, `fcee1bc`)
- Legacy multi-valued log strings are split when reloading dive netCDFs (`474660a`); fixed an orphaned `_qc` variable when the glider did not dive (`661ec3c`)

#### Sensor / driver support
- **QSP2150 PAR** sensor extension: calibration-mode metadata (modes A-D), in-water `qsp_PAR`, a dedicated plot, and `tools/GetQSPConstants.py` to pull the constants from a selftest capture (`38c414a`)
- Truck-mounted **RBR Tridente** processed to netCDF (compressed names expanded) (`e5f442e`)
- Network profile files (`.npro_ct.dat`/`.npro_wl.dat`) handled and plotted, with a sanity checker for `.nlog` files to catch converter mismatches (`a9114f1`, `46be8c9`, `9c55012`)
- Ignored truck Legato columns are kept in the netCDF without errors (`6c1b48c`); SBE43 fixes (`c007a6b`)
- Magcal gained dive/climb phase-splitting switches and a copy button (`f059631`, `2f24667`)

#### Alerts / notifications
- Glider `$WARN` events are counted per dive and alert per kind only above a threshold (`GLIDER_TIMEOUT`, `FUEL_GAUGE_MISSED`, `CT_PARSE_ERRORS`, `TCM2MAT_ERROR`) instead of one alert line per event (`9c45497`)
- Sensor timeouts alert only above `--timeout_alert_threshold` (default 5) (`416f54e`)
- Passwords, webhook URLs and ntfy topics are redacted from logs; binary file content is kept out of logs and notifications (`7bf2bbc`, `f830f9a`, `47abe64`)
- Multi-line Slack/Mattermost output is fenced as a code block (`3519283`); `.mailer` gzip attachments, email format and pagers endpoint checks fixed (`4904e06`, `4e372a9`)

#### Configuration validation (pydantic)
- `pagers.yml` validated with errors at file:line, bad entries dropped (not the whole file), a `PAGERS_YML` alert, check commands and a `.pagers` converter (`babf890`, `b659571`, `baef652`, `dd8b1cc`)
- New validators/checkers for `divescience.yml`, `NODC.yml`, `sites.yaml`, `sections.yml` (extensions can check their own variables), `missions.yml`, `users.yml` and the whole-mission config (`WHOLE_MISSION_CONFIG` alert) (`803e322`, `a9c4c77`, `73c0fef`, `0ca8d3b`, `64a831d`, `5ba745a`, `0f9eebb`, `b43bcf2`, `a167437`)

#### Comms / runtime
- **BaseRunnerMulti**: one multi-tenant watcher replaces per-site BaseRunner processes, with a privileged exec helper, per-site cgroup CPU throttling, per-job memory limits/tracking, job completion tracking and systemd units (`e600ba8`, `ed24ad6`, `96366e3`, `06b07be`, `7ee76e8`, `b0f8fea`, and fixes)
- SSH/KML and AVISO cron jobs converted to systemd timers; multi-site SSH KML generation runs as each site's runner (`052428d`, `b6ea648`)
- The commit ID is read directly from `.git` and logged by GliderEarlyGPS (`c474525`)
- Plotting no longer holds the mission db write lock; locked sessions are retried (`98e7dee`, `f39880b`)
- A glider call without a GPS fix is a warning, not an error, and isn't retried (`e295cb4`, `bb7ae7b`); a `comm.log` with no sessions no longer crashes Base (`1496ba5`)
- Mission product file lists, backups and `gzip_netcdf` names fixed (`ac90d97`, `b0f67be`, `70bf881`); network ncdfs no longer added to the mission db (`0098718`)

#### Visualization (map/plots)
- Vis SST overlay switched to GHRSST MUR, SSH overlay to Copernicus Marine DUACS SLA (`6a955b2`, `eb41f83`)
- Thumbnail ribbon (collapsible, smaller thumbnails), mission menu pulldown, ESRI ocean basemap, map index tile, ship TTG and JSON ship markers, RAFOS piloting parameters, more robust next-call estimates (Jason Gobat: `83f2e90`, `e9ce098`, `6bf5b4d`, `dc1147e`, `a03542a`, `7098b99`, `7314cea`, and others)
- Selftest summarizer lists installed batch files and highlights auto-exec ones (`a116335`, `c5bcc58`)
- `--gliderdac_plot_dives` quick-check plots (`1f3fbd9`); WKB sampling tools and schedule plot (opt-in) (`ead188c`, `9f719d8`); hidden max depth trace on `mission_int_sensors` (`9144c78`); `reduced_ts` in priority plots (`8dab8a0`)
- Plots skip missing or degenerate data with one error instead of a traceback (`5725ec2`, `a05ed35`, `1785463`, `c640a7f`, `f0e17e1`); fixed the single-pack MissionEnergy fuel gauge trace (`2c8574b`)

#### Documentation
- Documentation site (mkdocs, Material): Readme, `docs/` guide and a per-module API reference (`make doc`) (`a0ab0fc`, `0dd8db5`)
- BaseRunnerMulti documentation and service files (`18d7b08`, `7ee76e8`)

### Engineering / Internal Changes
- Full type-checking pass with `ty`, fixing dozens of latent bugs it found (`c423819`, `b9a2495`, `4e5070e`, `33cf834`, `6c30229`, `5bac155`, and others)
- Test suite runs in parallel with pytest-xdist (~3.5x faster) (`dcecbfd`)
- Kaleido/Chrome server management removed; thumbnails via a custom webp/matplotlib path (`1fc0ee7`, `914b510`)
- Subprocess exit-status checks fixed (`6b5f7a4`); `BaseGZip.compress` Python 2 leftovers fixed (`fb9bcc0`)
- CI builds numcodecs with `-std=gnu17` on ubuntu-26.04 (`bf8a2e8`)
- Version bumped to 3.0.9 (`5d4765a`, `5c36ff3`)

## [3.0.8] - 2026-07-23

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
