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

# A number of modules (Sensors, BaseNetCDF, FlightModel, Base) keep
# module-level singleton/accumulator state that's only ever initialized once,
# on import (each module's own set_globals(), called once at the bottom of
# that module). A real production run always gets a fresh process, so that
# single import-time initialization is all it ever needs.
#
# pytest doesn't give you a fresh process per test - the whole session runs
# in one process, so that state persists across every test unless something
# resets it. Some of it even guards against reinitialization outright:
# Sensors.init_extensions() logs an error and refuses to run a second time in
# the same process (Sensors.py). This is the thing that trips people up: a
# test can pass or fail depending on what ran before it in the same session,
# and the failure mode (or silent stale-state bug, for globals with no
# guard) only shows up under pytest, never in production.
#
# The actual fix for this repo lives in tests/testutils.py:run_mission() -
# it resets Sensors/BaseNetCDF/FlightModel/Base immediately before every
# main_func(cmd_line) call, since that call is the real "simulated fresh
# process" boundary tests use, and a single test can invoke it (or a
# main()-shaped function directly) more than once. See
# tests/test_FlightModelCLI.py for an example of a direct (non-run_mission)
# call adding its own explicit reset for the same reason.
#
# A pytest autouse fixture was tried here first and removed: it only resets
# once per *test function*, not once per simulated process within a test, so
# it didn't actually cover the case that broke (a test calling run_mission()
# twice), and once run_mission() had the real fix, nothing in the suite
# depended on the fixture at all. Kept here, commented out, as a ready
# example if a future test ever touches this state through some path other
# than run_mission()/an explicit reset - uncomment and add whichever modules'
# set_globals() that test needs.
#
# import pytest
#
# import Base
# import BaseNetCDF
# import FlightModel
# import Sensors
#
#
# @pytest.fixture(autouse=True)
# def _reset_module_globals():
#     """Resets module-level singleton state before every test."""
#     Sensors.set_globals()
#     BaseNetCDF.set_globals()
#     FlightModel.set_globals()
#     Base.set_globals()
#     yield
