# ctd_sampling

Designs a WKB-stretched CTD sampling schedule for a Seaglider from its most
recent dives, and compares it against the current sampling schedule.

Python port of the original MATLAB scripts (`glider_sampling_5_dives_v3_GS.m`
and helpers), using `xarray`/`netCDF4` for data loading and `gsw` (TEOS-10)
for buoyancy-frequency calculations. See `src/PLAN.md` for the conversion
plan.

## Usage

```sh
uv run ctd-sampling
```

## Development

```sh
uv sync
make all   # ruff format/lint, ty check, pytest --cov
```
