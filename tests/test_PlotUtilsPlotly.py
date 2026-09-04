# -*- python-fmt -*-

## Copyright (c) 2024, 2025, 2026  University of Washington.
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

import pathlib
import types

import PlotUtilsPlotly


class _FakeFigure:
    """Stand-in for a plotly Figure: write_html() and write_image() are
    instant, but write_image() can be made to raise for a chosen format so a
    single write_output_files() call can exercise "one format fails, the
    others still succeed"."""

    def __init__(self, failing_formats: frozenset[str] = frozenset()) -> None:
        self.failing_formats = failing_formats
        self.written_images: list[str] = []

    def write_html(self, file, **kwargs) -> None:
        if hasattr(file, "write"):
            file.write("<div>fake</div>")
        else:
            pathlib.Path(file).write_text("<div>fake</div>")

    def write_image(self, output_stream, *, format, **kwargs) -> None:
        if format in self.failing_formats:
            raise RuntimeError(f"simulated render failure for {format}")
        self.written_images.append(format)
        if hasattr(output_stream, "write"):
            output_stream.write(b"fake-image-bytes")
        else:
            pathlib.Path(output_stream).write_bytes(b"fake-image-bytes")


def test_write_output_files_one_format_failure_does_not_block_others(
    tmp_path, monkeypatch
) -> None:
    """A format whose render raises is logged and skipped; sibling formats in
    the same call still complete."""
    logged: list[str] = []
    monkeypatch.setattr(
        PlotUtilsPlotly,
        "log_error",
        lambda msg, **kwargs: logged.append(msg),
    )

    fig = _FakeFigure(failing_formats={"png"})
    base_opts = types.SimpleNamespace(
        plot_directory=tmp_path,
        full_html=False,
        compress_div=False,
        save_png=True,
        save_jpg=False,
        save_webp=True,
        save_svg=False,
        thumbnail_webp=False,
    )

    output_files = PlotUtilsPlotly.write_output_files(base_opts, "test_plot", fig)

    # webp succeeded despite png (rendered first) failing.
    assert "webp" in fig.written_images
    assert "png" not in fig.written_images
    assert any(str(f).endswith(".webp") for f in output_files)
    assert not any(str(f).endswith(".png") for f in output_files)
    # .div always gets written (pure HTML, not kaleido/Chrome).
    assert any(str(f).endswith(".div") for f in output_files)

    assert any(
        "Failed to write out" in msg and "test_plot.png" in msg for msg in logged
    )
