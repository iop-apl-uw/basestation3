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

"""Options set in a --config file: values that won't convert are errors, options left out keep their defaults."""

import pathlib

import pytest

import Base  # noqa: F401 - normal import order (registers Base's options)
import BaseOpts


def _options(tmp_path: pathlib.Path, conf_text: str) -> BaseOpts.BaseOptions:
    """Parses Base's options with a --config file holding conf_text.

    Args:
        tmp_path: The test's directory - the mission directory, and where the file goes.
        conf_text: The config file's contents.

    Returns:
        The options.
    """
    conf = tmp_path / "sg123.conf"
    conf.write_text(conf_text)
    return BaseOpts.BaseOptions(
        "test", cmdline_args=["--mission_dir", str(tmp_path), "--config", str(conf)], calling_module="Base"
    )


def test_good_values_set_and_missing_options_keep_defaults(tmp_path: pathlib.Path) -> None:
    """Values in the file are used, in [base] and in another section; options not in the file keep their defaults."""
    opts = _options(
        tmp_path,
        "[base]\nverbose = True\nglider_timeout_alert_threshold = 7\n"
        "[plotting]\nplot_raw = yes\ndive_plots = plot_CTD ,  plot_TS\n",
    )
    assert opts.verbose is True
    assert opts.glider_timeout_alert_threshold == 7
    assert opts.plot_raw is True
    assert opts.dive_plots == ["plot_CTD", "plot_TS"]  # split on commas, stripped
    defaults = BaseOpts.global_options_dict
    assert opts.fuel_gauge_alert_threshold == defaults["fuel_gauge_alert_threshold"].default_val
    assert opts.save_png == defaults["save_png"].default_val  # [plotting] option not in the file


def test_missing_section_keeps_defaults(tmp_path: pathlib.Path) -> None:
    """A file without an option's section is not an error."""
    opts = _options(tmp_path, "[base]\nverbose = True\n")
    assert opts.plot_raw == BaseOpts.global_options_dict["plot_raw"].default_val


@pytest.mark.parametrize(
    ("conf_text", "error", "message"),
    [
        # These two were dropped silently, keeping the default
        ("[base]\nverbose = notabool\n", ValueError, "Could not convert verbose from .*sg123.conf to boolean"),
        ("[plotting]\nplot_raw = sometimes\n", ValueError, "Could not convert plot_raw from .*sg123.conf to boolean"),
        ("[base]\nmagcalfile = ~nosuchuser_xyz_123/magcal.yml\n", ValueError, "Could not convert magcalfile .* to a path"),
        # These already raised
        ("[base]\nglider_timeout_alert_threshold = lots\n", ValueError, "Could not convert glider_timeout_alert_threshold"),
        ("[base]\nglider_timeout_alert_threshold = -1\n", IndexError, "-1 outside of range"),
    ],
)
def test_bad_values_raise(tmp_path: pathlib.Path, conf_text: str, error: type[Exception], message: str) -> None:
    """A value that won't convert (or is out of range) stops the parse, naming the option and the file."""
    with pytest.raises(error, match=message):
        _options(tmp_path, conf_text)
