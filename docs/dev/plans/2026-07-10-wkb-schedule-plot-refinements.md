# WKB schedule plot refinements (PLAN.md Task 1, items 1-4)

## Context

`basestation3/.claude/PLAN.md` (a repo-root backlog file, not authored by me)
lists follow-on refinements to the WKB sampling-schedule plot just added.
Task 1 has 5 sub-items; item 5 ("add the proposed updated sampling scheme"
as cut-and-paste text, in truck-vs-scicon command-file format, reading and
updating just the CTD section of the most recent config file) needs its own
investigation into `ScienceGrid.py`'s section-extraction machinery (which
only covers the scicon `.cap` format so far) and the truck-mounted command
format, which I haven't located yet — deferred to a separate follow-up per
your call. This plan covers items 1-4, which are self-contained changes to
the Plotly figure itself:

1. Group traces by sampling option
2. Add buttons (affecting both dive and climb subplots) to toggle all
   groups, or just individual options
3. Hover tips should reflect which group a trace belongs to
4. Legend should show the percent difference each option represents

All four live entirely in `ctd_sampling/plotting.py`
(`_add_direction_traces` / `build_sampling_schedule_figure`) — the same
figure-construction code already touched in the earlier legend-visibility
fix (Step 0b of the migration). None of this needs changes in
`Plotting/DiveWkbSchedule.py` (the basestation3 bridge just calls
`cs_plotting.build_sampling_schedule_figure(...)` unmodified and layers
title/help-link on top) or in `wkb.py` (the percent-diff numbers are already
available as existing `WkbDirectionResult` fields — no new computation
needed).

**Important consequence of the earlier "fresh copy, no shared history"
decision**: `basestation3/ctd_sampling/` is a frozen copy, not a live link
back to this repo. This work happens in `glider_sampling`
(`feature/wkb_sampling`, already checked out) same as before, verified
there, then the changed files are re-copied into
`basestation3/ctd_sampling/src/ctd_sampling/plotting.py` and re-verified
there too — mirroring the original copy step.

## Item 1 + 2: legend grouping and toggle buttons

Reuse the existing `updatemenus`/`restyle` button pattern already used
elsewhere in basestation3 (`Plotting/DivePlot.py`, `~line 990`): build
`traces = [d.name for d in fig.data]` after all traces are added, then for
each group compute the matching trace indices by name and add a toggle
button using the `args`/`args2` show/hide pair, e.g.:

```python
buttons = [
    {
        "args2": [{"visible": True}],
        "args": [{"visible": "legendonly"}],
        "label": "All",
        "method": "restyle",
    }
]
for option in range(n_options):
    idx = [i for i, name in enumerate(trace_names) if f"option {option}" in name]
    buttons.append({
        "args2": [{"visible": True}, idx],
        "args": [{"visible": "legendonly"}, idx],
        "label": f"Option {option}",
        "method": "restyle",
    })
fig.update_layout(updatemenus=[{
    "type": "buttons", "direction": "left", "buttons": buttons,
    "x": 0.0, "y": 1.12, "showactive": False,
}])
```

Trace names already carry `"option {option}"` / direction after Step 0b
(e.g. `"wkb sampling, option 1 (dive)"`, `"834 points (dive)"`), so an
`f"option {option}"` substring match against `trace_names` picks up both the
wkb-sampling line and the points-highlight line, across **both** dive and
climb rows in one pass — satisfying "affect both the dive and climb plots."
`current sampling (dive/climb)` traces get no dedicated button (no natural
"current" grouping was requested) — they stay visible by default and are
still covered by the "All" reset button.

For item 1's "group traces by sampling option" (as distinct from the
buttons), also set `legendgroup=f"option{option}"` on both traces per option
(matching across dive/climb too), and `fig.update_layout(legend={"groupclick":
"togglegroup"})` on the schedule figure, so clicking any one trace's legend
entry also toggles its whole option group together — complementary to the
buttons, not a replacement (every trace still gets its own individual
legend entry per the earlier Step 0b fix; this only changes what a legend
*click* does).

## Item 3: hover tips reflect the group

`_SAMPLING_HOVERTEMPLATE` is currently one shared template string. Simplest
fix, no per-trace special-casing needed: prepend `"%{fullData.name}<br>"`,
which Plotly resolves per-trace to that trace's own `name` (already
"wkb sampling, option 1 (dive)" etc. after Step 0b) — every hover tip then
leads with which trace/group/direction it belongs to, for free.

## Item 4: percent difference in the legend

`WkbDirectionResult.n_points` (already used in the subplot titles, e.g.
`"dive (556 points)"`) is the **current** actual point count for that
direction; `direction.n_new[option]` is the **proposed** WKB point count for
that option — both already exist, no new fields needed. Compute
`pct = (n_new[option] - direction.n_points) / direction.n_points * 100` (so a
negative value means fewer points than today, i.e. more efficient) and fold
it into the existing "points" trace name:

```python
pct = (int(direction.n_new[option]) - direction.n_points) / direction.n_points * 100
name=f"{int(direction.n_new[option])} points ({pct:+.0f}%) ({direction_label})"
```

## Verification

1. In `glider_sampling`: `uv run pytest --cov=src --cov-report=term-missing`
   — full suite green.
2. Regenerate the schedule figure against the bundled fixtures (same
   one-off script pattern used to verify Step 0b) and inspect:
   `fig.data[i].legendgroup`, `fig.data[i].hovertemplate`,
   `fig.layout.updatemenus`, and the `"points"` trace names for the `%`
   text — confirm all four items are present and the button trace-index
   lists are correct.
3. Commit in `glider_sampling` on `feature/wkb_sampling`.
4. Copy the updated `src/ctd_sampling/plotting.py` into
   `basestation3/ctd_sampling/src/ctd_sampling/plotting.py`, re-run
   `uv run pytest` there too (own copy, own test run), and re-exercise
   `Plotting.dive_plot_funcs['plot_wkb_schedule']` against the fixtures
   (same stand-in `base_opts` approach used before) to confirm the bridge
   still produces two figures with the new grouping/buttons/hover/percent
   intact end to end.
5. Commit in `basestation3` on `feature/wkb_sampling`.

## Outcome

Implemented as planned on `feature/wkb_sampling`: glider_sampling commit
`adc4eca`, basestation3 commit `a29d86c`. All verification steps passed
(both test suites green, button/legendgroup/hovertemplate/percent-diff
inspected directly against the bundled fixtures, ruff/ty clean). Item 5
(proposed sampling-scheme text) was split out into a new Task 4 in
`.claude/PLAN.md` for separate investigation.
