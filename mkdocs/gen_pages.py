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

"""Builds the documentation site's pages at mkdocs build time (mkdocs-gen-files).

Nothing is written to the repository - every page is a virtual file in the build:

- index.md: the Readme. Its links into docs/ point at the guide; its other
  repo-relative links point at the file on GitHub.
- guide/: every file under docs/, at the same relative path, so links between
  them keep working. docs/ itself stays plain markdown, read on GitHub and on
  disk in an installation; a link from a docs/ page to a file outside docs/
  (../sg000/sections.yml) is pointed at the file on GitHub.
- reference/: one page per module (mkdocstrings), grouped by directory.
- SUMMARY.md: the navigation (mkdocs-literate-nav).
"""

from __future__ import annotations

import pathlib
import re
from collections.abc import Callable

import mkdocs_gen_files

ROOT = pathlib.Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
GITHUB = "https://github.com/iop-apl-uw/basestation3"
BRANCH = "master"

# Area -> (source directory, how a module there is named for mkdocstrings)
AREAS: dict[str, tuple[pathlib.Path, Callable[[str], str]]] = {
    "Core": (ROOT, lambda stem: stem),
    "Plotting": (ROOT / "Plotting", lambda stem: f"Plotting.{stem}"),  # a package
    "Sensors": (ROOT / "Sensors", lambda stem: stem),  # on the mkdocstrings path
    "ssh": (ROOT / "ssh", lambda stem: stem),  # on the mkdocstrings path
}

_LINK = re.compile(r"(!?\[[^\]]*\]\()([^)\s]+)(\))")


def _github_url(repo_path: pathlib.Path, fragment: str) -> str:
    """The GitHub URL for a file or directory in the repository."""
    kind = "tree" if (ROOT / repo_path).is_dir() else "blob"
    return f"{GITHUB}/{kind}/{BRANCH}/{repo_path.as_posix()}{fragment}"


def _split(target: str) -> tuple[str, str]:
    """A link target as (path, #fragment), with a ?raw=true-style query dropped."""
    path, _, fragment = target.partition("#")
    path = path.split("?", 1)[0]
    return path, f"#{fragment}" if fragment else ""


def _is_relative(target: str) -> bool:
    return not (
        re.match(r"^[a-z][a-z0-9+.-]*:", target, re.I) or target.startswith(("#", "/"))
    )


def rewrite_links(text: str, page: pathlib.Path, site_root: pathlib.Path) -> str:
    """Points a page's relative links at the right place in the site.

    Args:
        text: The page's markdown.
        page: The page's source file (in the repository).
        site_root: The repository directory that maps to the page's site directory -
            links that stay inside it are left as they are (the files are copied
            alongside); links that leave it go to the file on GitHub.

    Returns:
        The markdown with its links rewritten.
    """

    def fix(match: re.Match[str]) -> str:
        target = match.group(2)
        if not _is_relative(target):
            return match.group(0)
        path, fragment = _split(target)
        if not path:
            return match.group(0)
        resolved = (page.parent / path).resolve()
        try:
            resolved.relative_to(site_root)
        except ValueError:
            pass
        else:
            return match.group(0)  # copied into the site at the same relative place
        try:
            repo_path = resolved.relative_to(ROOT)
        except ValueError:
            return match.group(0)  # outside the repository - leave it
        return f"{match.group(1)}{_github_url(repo_path, fragment)}{match.group(3)}"

    return _LINK.sub(fix, text)


def _title(page: pathlib.Path) -> str:
    """A markdown page's first heading, or its file name."""
    for line in page.read_text(errors="replace").splitlines():
        if line.startswith("#"):
            return line.lstrip("#").strip() or page.stem
    return page.stem


def write_index() -> None:
    """The Readme as the front page: links into docs/ go to the guide, other repo files to GitHub."""

    def fix(match: re.Match[str]) -> str:
        target = match.group(2)
        if not _is_relative(target):
            return match.group(0)
        path, fragment = _split(target)
        if not path:
            return match.group(0)
        resolved = (ROOT / path).resolve()
        try:
            in_docs = resolved.relative_to(DOCS)
        except ValueError:
            return f"{match.group(1)}{_github_url(resolved.relative_to(ROOT), fragment)}{match.group(3)}"
        return f"{match.group(1)}guide/{in_docs.as_posix()}{fragment}{match.group(3)}"

    with mkdocs_gen_files.open("index.md", "w") as f:
        f.write(_LINK.sub(fix, (ROOT / "Readme.md").read_text()))
    mkdocs_gen_files.set_edit_path("index.md", "../Readme.md")


def write_guide() -> list[tuple[str, str]]:
    """Every file under docs/ at guide/<same path>; returns (title, site path) for the pages."""
    pages = []
    for src in sorted(p for p in DOCS.rglob("*") if p.is_file()):
        rel = src.relative_to(DOCS)
        dest = pathlib.Path("guide") / rel
        if src.suffix == ".md":
            with mkdocs_gen_files.open(dest, "w") as f:
                f.write(rewrite_links(src.read_text(), src, DOCS))
            pages.append((_title(src), dest.as_posix()))
        else:
            with mkdocs_gen_files.open(dest, "wb") as f:
                f.write(src.read_bytes())
    return pages


def write_reference() -> dict[str, list[tuple[str, str]]]:
    """A ::: page per module, by area; returns area -> [(module, site path)]."""
    seen: dict[str, pathlib.Path] = {}
    areas: dict[str, list[tuple[str, str]]] = {}
    for area, (directory, identifier) in AREAS.items():
        for src in sorted(directory.glob("*.py")):
            if src.name == "__init__.py":
                continue
            name = identifier(src.stem)
            if name in seen:
                raise SystemExit(
                    f"gen_pages: {src} and {seen[name]} would both be documented as {name}"
                )
            seen[name] = src
            dest = pathlib.Path("reference") / area.lower() / f"{src.stem}.md"
            with mkdocs_gen_files.open(dest, "w") as f:
                f.write(f"::: {name}\n")
            mkdocs_gen_files.set_edit_path(
                dest, f"../{src.relative_to(ROOT).as_posix()}"
            )
            areas.setdefault(area, []).append((src.stem, dest.as_posix()))
    return areas


def main() -> None:
    """Writes the pages and the navigation."""
    write_index()
    guide = write_guide()
    reference = write_reference()
    nav = ["* [Home](index.md)", "* [Guide](guide/Docs.md)"]
    nav += [
        f"    * [{title}]({path})" for title, path in guide if path != "guide/Docs.md"
    ]
    nav.append("* Reference")
    for area, modules in reference.items():
        nav.append(f"    * {area}")
        nav += [f"        * [{name}]({path})" for name, path in modules]
    with mkdocs_gen_files.open("SUMMARY.md", "w") as f:
        f.write("\n".join(nav) + "\n")


main()
