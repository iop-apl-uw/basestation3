#! /usr/bin/env python3
"""Daily journal scan for the MakeKML SSH jobs' errors, emailed to ioplog@uw.edu.

Since aviso-fetch-worker.service and makekml-ssh-worker.service (see those
unit files) log to the systemd journal instead of /var/log/MakeKML.log,
this is journalctl's answer to
~/work/git/basestation/bin/scan_makekml_errors.py, which scanned that log
file. It pulls each worker's journal entries for a trailing window, groups
them into the same ERROR/WARNING/CRITICAL-plus-traceback blocks that tool
used, and emails one combined report via the local `mail` command --
matching the old setup where both cron jobs wrote to the same
MakeKML.log and were scanned by a single daily run.

It also scans each job's *-trigger.service journal for overlap-protection
refusals (see aviso-fetch-trigger.service / makekml-ssh-trigger.service) --
cycles skipped because the previous run was still active -- since those
never appear in the worker's own log output.

Meant to run once a day out of systemd (makekml-error-report.timer); see
makekml-systemd-setup.md for installation and for running this by hand.

Example:
    python3 report_makekml_errors.py --dry-run
    python3 report_makekml_errors.py --since -2days --only-if-errors
"""

from __future__ import annotations

import argparse
import json
import re
import socket
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime

# BaseLog.py's timestamp style, e.g.:
#   22:10:06 23 Aug 2023 UTC: ERROR: Could not process inbox:
# journald wraps each physical line of a worker's stdout in its own journal
# entry, but `journalctl -o cat` reprints just the MESSAGE field one per
# line, so the resulting text stream matches the old log file's layout
# closely enough to reuse the same block-grouping approach.
_TIMESTAMP_LINE_RE = re.compile(
    r"^(?P<ts>\d{2}:\d{2}:\d{2} \d{2} \w{3} \d{4}) UTC: (?P<level>[A-Z]+): (?P<message>.*)$"
)
_BARE_LEVEL_LINE_RE = re.compile(r"^(?P<level>DEBUG|INFO|WARNING|ERROR|CRITICAL): (?P<message>.*)$")
_EXCEPTION_LINE_RE = re.compile(r"^(?P<exc>[A-Za-z_][\w.]*): ?(?P<msg>.*)$")
_TRACEBACK_HEADER = "Traceback (most recent call last):"
_CHAIN_PHRASES = frozenset(
    {
        "During handling of the above exception, another exception occurred:",
        "The above exception was the direct cause of the following exception:",
    }
)

# Levels treated as errors worth reporting.
LEVELS = ("ERROR", "CRITICAL", "WARNING")

DEFAULT_TO_ADDR = "ioplog@uw.edu"
DEFAULT_SINCE = "-1days"


@dataclass(frozen=True)
class JobSpec:
    """One MakeKML SSH cron-replacement job to scan.

    Attributes:
        name: Short label for report sections, e.g. "aviso-fetch".
        unit: The worker systemd unit that does the actual work.
        trigger_unit: The trigger systemd unit that starts `unit` with
            `--job-mode=fail` (see e.g. aviso-fetch-trigger.service).
    """

    name: str
    unit: str
    trigger_unit: str


DEFAULT_JOBS: tuple[JobSpec, ...] = (
    JobSpec("aviso-fetch", "aviso-fetch-worker.service", "aviso-fetch-trigger.service"),
    JobSpec("makekml-ssh", "makekml-ssh-worker.service", "makekml-ssh-trigger.service"),
)


@dataclass
class TriggerRefusal:
    """One systemd-logged failure of a trigger unit -- normally because
    `--job-mode=fail` refused to start the worker while a previous run was
    still active (see e.g. aviso-fetch-trigger.service).
    """

    timestamp: datetime
    message: str


@dataclass
class ErrorEntry:
    """One matched error block: a header line plus any raw lines
    (tracebacks, chained exceptions) that followed it before the next
    header line.
    """

    timestamp: datetime | None
    timestamp_approx: bool
    level: str
    summary: str
    has_traceback: bool
    detail: str


def parse_timestamp(raw: str) -> datetime:
    """Parses a BaseLog.py-style UTC timestamp.

    Args:
        raw: Timestamp text matched by `_TIMESTAMP_LINE_RE`'s `ts` group,
            e.g. "22:10:06 23 Aug 2023".

    Returns:
        A timezone-aware UTC datetime.

    Raises:
        ValueError: If `raw` doesn't match the expected format.
    """
    return datetime.strptime(raw, "%H:%M:%S %d %b %Y").replace(tzinfo=UTC)


def _representative_exception(block_lines: list[str]) -> str | None:
    """Finds the final raised exception described within an error block.

    Args:
        block_lines: Raw lines belonging to one error block, in order.

    Returns:
        `"<ExceptionClass>: <message>"` (or just `"<ExceptionClass>"` if it
        had no message), or None if no exception line was found.

    Raises:
        None.
    """
    last: str | None = None
    for line in block_lines:
        if line.startswith((" ", "\t")):
            continue
        match = _EXCEPTION_LINE_RE.match(line)
        if match is None:
            continue
        msg = match.group("msg").strip()
        last = f"{match.group('exc')}: {msg}" if msg else match.group("exc")
    return last


def _classify_header(line: str) -> tuple[datetime | None, str, str] | None:
    """Classifies a line as a log-record header, timestamped or bare.

    Args:
        line: A single line from the journal text stream.

    Returns:
        `(timestamp, level, message)` if `line` is a record header (`None`
        for `timestamp` when the header has no timestamp), or None if
        `line` is not a record header at all (e.g. traceback body text).

    Raises:
        None.
    """
    match = _TIMESTAMP_LINE_RE.match(line)
    if match is not None:
        return parse_timestamp(match.group("ts")), match.group("level"), match.group("message")
    match = _BARE_LEVEL_LINE_RE.match(line)
    if match is not None:
        return None, match.group("level"), match.group("message")
    return None


def _consume_block(lines: list[str], start: int, seed_is_traceback: bool = False) -> tuple[list[str], int]:
    """Collects the lines following a block's header line, up to the next
    record header, an unchained Traceback header, or end of input.

    Args:
        lines: All lines of the journal text stream.
        start: Index of the first line *after* the block's header line.
        seed_is_traceback: True if the block's own header line (not scanned
            by this function) was itself a Traceback header.

    Returns:
        `(block_lines, next_index)`: the collected lines and the index to
        resume top-level scanning from.

    Raises:
        None.
    """
    n = len(lines)
    j = start
    block_lines: list[str] = []
    seen_traceback = seed_is_traceback
    while j < n:
        line = lines[j]
        if _classify_header(line) is not None:
            break
        if line.strip() == _TRACEBACK_HEADER:
            if seen_traceback:
                preceding = next((bl.strip() for bl in reversed(block_lines) if bl.strip()), None)
                if preceding not in _CHAIN_PHRASES:
                    break
            seen_traceback = True
        block_lines.append(line)
        j += 1
    while block_lines and not block_lines[-1].strip():
        block_lines.pop()
    return block_lines, j


def parse_entries(text: str) -> list[ErrorEntry]:
    """Extracts ERROR/WARNING/CRITICAL blocks (plus orphaned tracebacks)
    from a block of worker journal text.

    Args:
        text: Journal text, one physical log line per line (as produced by
            `journalctl -u <worker-unit> -o cat`).

    Returns:
        Matched error entries, in the order they appeared in `text`.

    Raises:
        None.
    """
    entries: list[ErrorEntry] = []
    lines = text.split("\n")
    n = len(lines)
    last_ts: datetime | None = None
    i = 0
    while i < n:
        line = lines[i]
        header = _classify_header(line)

        if header is not None:
            ts, level, header_message = header
            if ts is not None:
                last_ts = ts

            if level not in LEVELS:
                i += 1
                continue

            block_lines, j = _consume_block(lines, i + 1)
            full_block = [header_message, *block_lines]

            has_traceback = any(bl.strip() == _TRACEBACK_HEADER for bl in block_lines)
            summary = header_message.strip() or _representative_exception(full_block) or header_message
            entries.append(
                ErrorEntry(
                    timestamp=ts if ts is not None else last_ts,
                    timestamp_approx=ts is None and last_ts is not None,
                    level=level,
                    summary=summary,
                    has_traceback=has_traceback,
                    detail="\n".join(full_block),
                )
            )
            i = j
            continue

        if line.strip() == _TRACEBACK_HEADER:
            block_lines, j = _consume_block(lines, i + 1, seed_is_traceback=True)
            full_block = [line, *block_lines]

            summary = _representative_exception(full_block) or "Unhandled traceback"
            entries.append(
                ErrorEntry(
                    timestamp=last_ts,
                    timestamp_approx=last_ts is not None,
                    level="ERROR",
                    summary=summary,
                    has_traceback=True,
                    detail="\n".join(full_block),
                )
            )
            i = j
            continue

        i += 1

    return entries


def _format_utc(dt: datetime | None) -> str:
    """Formats a UTC datetime as compact ISO8601 (`Z` suffix, not `+00:00`).

    Args:
        dt: A timezone-aware UTC datetime, or None.

    Returns:
        E.g. "2026-08-09T20:01:48Z", or "unknown" if `dt` is None.

    Raises:
        None.
    """
    if dt is None:
        return "unknown"
    return dt.isoformat().replace("+00:00", "Z")


def _signature(entry: ErrorEntry) -> str:
    """Normalizes an entry's summary into a grouping key for the summary table.

    Args:
        entry: An error entry.

    Returns:
        `entry.summary` with digit runs replaced by "N" so repeats of "the
        same" failure with different incidental numbers collapse together.

    Raises:
        None.
    """
    return re.sub(r"\d+", "N", entry.summary)[:100]


def format_job_section(
    job: JobSpec,
    entries: list[ErrorEntry],
    trigger_refusals: list[TriggerRefusal],
) -> list[str]:
    """Builds the report section for one job's matched entries/refusals.

    Args:
        job: The job being reported on.
        entries: Matched error entries for `job.unit`, in journal order.
        trigger_refusals: Overlap-protection refusals from
            `job.trigger_unit`'s journal, in chronological order.

    Returns:
        Report lines for this job's section (no trailing blank line).

    Raises:
        None.
    """
    lines: list[str] = [f"== {job.name} ({job.unit}) =="]

    lines.append(f"Overlap-protection refusals ({job.trigger_unit}): {len(trigger_refusals)}")
    if trigger_refusals:
        lines.append("(previous run still active -- that cycle was skipped, not queued or merged)")
        for r in trigger_refusals:
            lines.append(f"  [{_format_utc(r.timestamp)}] {r.message}")

    if not entries:
        lines.append("No ERROR/WARNING/CRITICAL entries found in this window.")
        return lines

    header = f"{'timestamp (UTC)':22}{'level':10}{'tb':4}  summary"
    lines.append(header)
    lines.append("-" * len(header))
    for e in entries:
        approx = "~" if e.timestamp_approx else " "
        tb = "yes" if e.has_traceback else ""
        lines.append(f"{approx}{_format_utc(e.timestamp):20} {e.level:9} {tb:3}  {e.summary}")

    return lines


def format_report(
    entries_by_job: dict[JobSpec, list[ErrorEntry]],
    refusals_by_job: dict[JobSpec, list[TriggerRefusal]],
    since: str,
    top: int = 20,
) -> str:
    """Builds the plain-text email body summarizing every job's matched
    error entries and trigger refusals.

    Args:
        entries_by_job: Matched error entries per job, in journal order.
        refusals_by_job: Overlap-protection refusals per job, in
            chronological order.
        since: The journalctl `--since` window that was scanned.
        top: Maximum number of distinct failure signatures to list in the
            grouped summary table.

    Returns:
        The full report text, ready to use as an email body.

    Raises:
        None.
    """
    lines: list[str] = [f"MakeKML SSH jobs error report (journalctl --since {since})", ""]

    all_entries: list[ErrorEntry] = []
    for job in entries_by_job:
        lines.extend(format_job_section(job, entries_by_job[job], refusals_by_job[job]))
        lines.append("")
        all_entries.extend(entries_by_job[job])

    if not all_entries:
        lines.append("No ERROR/WARNING/CRITICAL entries found in this window, across any job.")
        return "\n".join(lines)

    lines.append(f"Total across all jobs: {len(all_entries)}")
    lines.append("")

    counts: dict[str, int] = {}
    for e in all_entries:
        sig = _signature(e)
        counts[sig] = counts.get(sig, 0) + 1

    lines.append(f"Top {min(top, len(counts))} failure(s) by frequency (across all jobs):")
    sig_header = f"{'count':>8}  signature"
    lines.append(sig_header)
    lines.append("-" * len(sig_header))
    for sig, count in sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:top]:
        lines.append(f"{count:>8}  {sig}")

    lines.append("")
    lines.append("(~ = timestamp approximated from the nearest preceding log line)")
    lines.append("")
    lines.append("Full detail for entries with a traceback:")
    lines.append("-" * 40)
    for job, entries in entries_by_job.items():
        for e in entries:
            if e.has_traceback:
                lines.append(f"\n[{job.name}] [{_format_utc(e.timestamp)}] {e.level}: {e.summary}")
                lines.append(e.detail)

    return "\n".join(lines)


def fetch_journal(unit: str, since: str) -> str:
    """Fetches journal message text for a systemd unit.

    Args:
        unit: Systemd unit name, e.g. "aviso-fetch-worker.service".
        since: A journalctl `--since` value, e.g. "-1days" or "yesterday".

    Returns:
        The unit's journal MESSAGE fields for the window, one per line, in
        chronological order (journalctl's default `-o cat` behavior).

    Raises:
        subprocess.CalledProcessError: If journalctl exits non-zero.
    """
    result = subprocess.run(
        ["journalctl", "-u", unit, "--since", since, "-o", "cat", "--no-pager"],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def fetch_trigger_refusals(unit: str, since: str) -> list[TriggerRefusal]:
    """Fetches overlap-protection refusals from a trigger unit's journal.

    Every failure of `unit` (job-mode=fail refusing to start the worker
    because a previous run was still active, per e.g.
    aviso-fetch-trigger.service) is logged by systemd itself at "warning"
    priority or higher against the trigger unit -- not written by any of
    our own code -- so this reads `-o json` records directly rather than
    the BaseLog-style text parsing `parse_entries` does for a worker's own
    output.

    Args:
        unit: The trigger systemd unit to scan, e.g.
            "aviso-fetch-trigger.service".
        since: A journalctl `--since` value, e.g. "-1days" or "yesterday".

    Returns:
        Matched refusals/failures, in chronological order.

    Raises:
        subprocess.CalledProcessError: If journalctl exits non-zero.
    """
    result = subprocess.run(
        ["journalctl", "-u", unit, "--since", since, "-p", "warning", "-o", "json", "--no-pager"],
        capture_output=True,
        text=True,
        check=True,
    )
    refusals: list[TriggerRefusal] = []
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        message = record.get("MESSAGE", "")
        if isinstance(message, list):
            message = bytes(message).decode("utf-8", errors="replace")
        timestamp = datetime.fromtimestamp(int(record["__REALTIME_TIMESTAMP"]) / 1_000_000, tz=UTC)
        refusals.append(TriggerRefusal(timestamp=timestamp, message=str(message)))
    return refusals


def send_report(to_addr: str, subject: str, body: str) -> None:
    """Emails a report via the local `mail` command.

    Args:
        to_addr: Destination email address.
        subject: Email subject line.
        body: Email body text.

    Returns:
        None.

    Raises:
        subprocess.CalledProcessError: If `mail` exits non-zero.
    """
    subprocess.run(["mail", "-s", subject, to_addr], input=body, text=True, check=True)


def main() -> int:
    """Parses CLI args, scans each job's journal, and emails (or prints)
    the combined report.

    Returns:
        Process exit code (always 0; journalctl/mail failures raise).

    Raises:
        subprocess.CalledProcessError: If journalctl or `mail` fails.
    """
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--since",
        default=DEFAULT_SINCE,
        help=f"journalctl --since window to scan (default: {DEFAULT_SINCE})",
    )
    parser.add_argument("--to", default=DEFAULT_TO_ADDR, help=f"report recipient (default: {DEFAULT_TO_ADDR})")
    parser.add_argument(
        "--only-if-errors",
        action="store_true",
        help="Send no email at all when nothing to report (no matching errors and no trigger refusals) "
        "(default: always send a daily report)",
    )
    parser.add_argument("--top", type=int, default=20, metavar="N", help="Number of failure signatures to summarize")
    parser.add_argument("--dry-run", action="store_true", help="Print the report instead of emailing it")
    args = parser.parse_args()

    entries_by_job: dict[JobSpec, list[ErrorEntry]] = {}
    refusals_by_job: dict[JobSpec, list[TriggerRefusal]] = {}
    for job in DEFAULT_JOBS:
        entries_by_job[job] = parse_entries(fetch_journal(job.unit, args.since))
        refusals_by_job[job] = fetch_trigger_refusals(job.trigger_unit, args.since)

    total_entries = sum(len(e) for e in entries_by_job.values())
    total_refusals = sum(len(r) for r in refusals_by_job.values())

    if total_entries == 0 and total_refusals == 0 and args.only_if_errors:
        return 0

    report = format_report(entries_by_job, refusals_by_job, args.since, top=args.top)
    hostname = socket.gethostname()
    status_parts = [
        "no errors" if total_entries == 0 else f"{total_entries} error(s)",
        f"{total_refusals} skipped run(s)" if total_refusals else None,
    ]
    status = ", ".join(p for p in status_parts if p is not None)
    subject = f"MakeKML SSH jobs daily error report ({hostname}): {status}"

    if args.dry_run:
        print(f"Subject: {subject}\n")
        print(report)
        return 0

    send_report(args.to, subject, report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
