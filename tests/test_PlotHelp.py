# -*- python-fmt -*-

## Copyright (c) 2026  University of Washington.
##
## Redistribution and use in source and binary forms, with or without
## modification, are permitted provided that the following conditions are met:
##
## 1. Redistributions of source code must retain the above copyright notice, this
##    list of conditions and the following disclaimer.
##
## 2. Redistributions in binary form must reproduce the above copyright notice,
##    this list of conditions and the following disclaimer in the documentation
##    and/or other materials provided with the distribution.
##
## 3. Neither the name of the University of Washington nor the names of its
##    contributors may be used to endorse or promote products derived from this
##    software without specific prior written permission.
##
## THIS SOFTWARE IS PROVIDED BY THE UNIVERSITY OF WASHINGTON AND CONTRIBUTORS “AS
## IS” AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
## IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
## DISCLAIMED. IN NO EVENT SHALL THE UNIVERSITY OF WASHINGTON OR CONTRIBUTORS BE
## LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
## CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE
## GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION)
## HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
## LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT
## OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

"""Guards against plot help links (PlotUtilsPlotly.add_help_link) pointing at a
missing or empty page under html/plothelp/.
"""

import pathlib
import re

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
PLOTTING_DIR = REPO_ROOT / "Plotting"
PLOTHELP_DIR = REPO_ROOT / "html" / "plothelp"

# Matches add_help_link("some_tag" ...) regardless of module prefix, keyword
# args, or how the call is wrapped/indented.
HELP_LINK_RE = re.compile(r"add_help_link\(\s*[\"'](?P<tag>[\w.]+)[\"']")


def _collect_help_link_tags() -> dict[str, list[str]]:
    """Maps each add_help_link tag used in Plotting/*.py to the file(s) that use it."""
    tags: dict[str, list[str]] = {}
    for py_file in sorted(PLOTTING_DIR.glob("*.py")):
        text = py_file.read_text()
        for m in HELP_LINK_RE.finditer(text):
            tags.setdefault(m.group("tag"), []).append(py_file.name)
    return tags


_HELP_LINK_TAGS = _collect_help_link_tags()


def test_found_at_least_one_help_link() -> None:
    """Sanity check that the scan itself is working (would false-pass an empty result otherwise)."""
    assert len(_HELP_LINK_TAGS) > 10


@pytest.mark.parametrize("tag,sources", sorted(_HELP_LINK_TAGS.items()))
def test_plot_help_link_has_page(tag: str, sources: list[str]) -> None:
    help_file = PLOTHELP_DIR / f"{tag}.html"
    assert help_file.exists(), (
        f"add_help_link({tag!r}) used in {sources} but {help_file} does not exist"
    )
    assert help_file.stat().st_size > 0, f"{help_file} exists but is empty"
