# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas <thiagodefreitas@gmail.com>
import os
import re

import ntpstats

ROOT = os.path.join(os.path.dirname(__file__), os.pardir)


def test_version_is_semver():
    assert re.fullmatch(r"\d+\.\d+\.\d+", ntpstats.__version__)


def test_changelog_has_entry_for_current_version():
    text = open(os.path.join(ROOT, "CHANGELOG.md"), encoding="utf-8").read()
    released = re.findall(r"^## \[(\d+\.\d+\.\d+)\]", text, re.M)
    assert released and released[0] == ntpstats.__version__, "add a CHANGELOG entry for the new version"


def test_citation_version_matches():
    text = open(os.path.join(ROOT, "CITATION.cff"), encoding="utf-8").read()
    assert f"version: {ntpstats.__version__}" in text
