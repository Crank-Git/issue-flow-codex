"""Tests for skills/project-planner/scripts/render-spec.py.

Ported from upstream scripts/test-render-spec.py.

Runs the renderer the way the planner tells the user to run it: copied into a
docs/specs/ directory and executed as a script, against a throwaway spec package. The
render is a multi-page site (a spec.html index plus one html/ page per feature and per
`pages:` entry). Relative markdown links rewrite so they resolve from every generated
page. Diagrams and mockups stay self-contained. The suite passes offline.
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

RENDERER = (Path(__file__).resolve().parent.parent / "skills" / "project-planner" / "scripts"
            / "render-spec.py")

SPEC_MD = """---
name: Widget Tracker
slug: widget-tracker
status: draft
created: 2026-08-16
html_generated: null
branch_model: trunk
features:
  - id: intake
    file: features/01-intake.md
pages:
  - id: plan
    file: pages/plan.md
---

# Widget Tracker

## Overview

The tracker records every widget the shop receives. Details in
[the intake feature](features/01-intake.md) and [the plan](pages/plan.md).

## Architecture & stack

```mermaid
flowchart LR
  ui[Web UI] --> api[API] --> db[(Postgres)]
```

The API owns all database access.

## Assumptions

- The shop has one location.
"""

FEATURE_MD = """---
id: intake
feature: Widget Intake
epic: Epic 1
status: planned
issues: []
mockups: [mockups/01-intake.html]
---

## Purpose

An operator registers an arriving widget in under a minute. See
[the index](../spec.md) and [the form mockup](mockups/01-intake.html).

## User flows

```mermaid
flowchart TD
  start[Scan widget] --> form[Intake form] --> save{Valid?}
  save -- yes --> done[Stored]
  save -- no --> form
```

1. The operator scans the widget barcode.
2. The form pre-fills the serial number.

## Behaviour rules

| Field | Rule |
| --- | --- |
| serial | unique, required |
| state | `pending | running | stored` |

- top rule
  - nested two-space rule
    - nested four-space child
- second top rule

A [strange link](x"onmouseover="alert1) survives escaping.
"""

PAGE_MD = """---
id: plan
title: Implementation plan
---

## Ordering

Intake ships first — see [the intake feature](../features/01-intake.md).
"""

MOCKUP_HTML = "<h1>Intake form mockup</h1>"

REVIEW_MD = """# Review comments

<!-- exported header -->

## [index] overview
status: open
date: 2026-08-16
Say which shop.

## [feature-intake] intake-purpose
status: resolved
date: 2026-08-16
Answered.

## Malformed heading block
must survive as an index comment
"""

STAMP = re.compile(r"^html_generated: \d{4}-\d{2}-\d{2}$", re.M)


def make_spec_dir(with_mermaid_asset):
    root = tempfile.mkdtemp(prefix="render-spec-test-")
    spec = os.path.join(root, "docs", "specs")
    for sub in ("features", "pages", "mockups"):
        os.makedirs(os.path.join(spec, sub))
    for name, text in (("spec.md", SPEC_MD), ("features/01-intake.md", FEATURE_MD),
                       ("pages/plan.md", PAGE_MD), ("mockups/01-intake.html", MOCKUP_HTML)):
        with open(os.path.join(spec, name), "w") as handle:
            handle.write(text)
    if with_mermaid_asset:
        os.makedirs(os.path.join(spec, "assets"))
        with open(os.path.join(spec, "assets", "mermaid.min.js"), "w") as handle:
            handle.write("window.mermaid={initialize:function(){}};/*VENDORED-SENTINEL*/")
    shutil.copy(RENDERER, os.path.join(spec, "render-spec.py"))
    return root, spec


def render(spec):
    return subprocess.run([sys.executable, os.path.join(spec, "render-spec.py")],
                          capture_output=True, text=True)


def read(path):
    return Path(path).read_text() if os.path.exists(path) else ""


class VendoredMermaidTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root, cls.spec = make_spec_dir(with_mermaid_asset=True)
        with open(os.path.join(cls.spec, "review-comments.md"), "w") as handle:
            handle.write(REVIEW_MD)
        os.makedirs(os.path.join(cls.spec, "html"))
        with open(os.path.join(cls.spec, "html", "feature-old.html"), "w") as handle:
            handle.write("stale")
        cls.result = render(cls.spec)
        cls.index = read(os.path.join(cls.spec, "spec.html"))
        cls.feature = read(os.path.join(cls.spec, "html", "feature-intake.html"))
        cls.page = read(os.path.join(cls.spec, "html", "page-plan.html"))
        cls.body = cls.feature.split("</aside>")[-1]

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.root)

    def test_exits_0(self):
        self.assertEqual(self.result.returncode, 0, self.result.stderr)

    def test_writes_the_index_and_one_page_per_feature_and_supplement(self):
        self.assertNotEqual(self.index, "")
        self.assertNotEqual(self.feature, "")
        self.assertNotEqual(self.page, "")

    def test_removes_a_stale_html_page_and_says_so(self):
        self.assertFalse(os.path.exists(os.path.join(self.spec, "html", "feature-old.html")))
        self.assertIn("stale", self.result.stderr)

    def test_renders_the_spec_content_in_place_on_the_index(self):
        self.assertIn("records every widget the shop receives", self.index)

    def test_renders_a_feature_in_full_on_its_page(self):
        self.assertIn("registers an arriving widget in under a minute", self.feature)

    def test_links_the_index_to_the_feature_page_not_the_markdown(self):
        self.assertIn('href="html/feature-intake.html"', self.index)
        self.assertNotIn('href="features/01-intake.md"', self.index)

    def test_links_the_index_to_the_supplement_page(self):
        self.assertIn('href="html/page-plan.html"', self.index)

    def test_renders_the_supplement_page_with_its_title_and_content(self):
        self.assertIn("Implementation plan", self.page)
        self.assertIn("Intake ships first", self.page)

    def test_rewrites_a_page_link_to_a_feature_to_the_generated_page(self):
        self.assertIn('href="feature-intake.html"', self.page)

    def test_rewrites_a_feature_link_back_to_the_spec_to_the_index(self):
        self.assertIn('href="../spec.html"', self.feature)

    def test_re_bases_a_feature_link_to_a_mockup_from_the_html_directory(self):
        self.assertIn('href="../mockups/01-intake.html"', self.feature)

    def test_lists_the_sections_of_the_spec_in_the_index_sidebar(self):
        self.assertIn('class="sub" href="#overview"', self.index)

    def test_threads_the_pager_from_index_to_page_to_feature(self):
        self.assertIn('href="../spec.html"', self.page)
        self.assertIn('href="feature-intake.html"', self.page)
        self.assertIn('href="page-plan.html"', self.feature)

    def test_renders_numbered_steps(self):
        self.assertIn("pre-fills the serial number", self.body)

    def test_renders_a_table(self):
        self.assertIn("<th>Field</th>", self.body)
        self.assertIn("<td>serial</td>", self.body)

    def test_keeps_a_pipe_inside_a_code_span_in_one_cell(self):
        self.assertIn("<td><code>pending | running | stored</code></td>", self.body)

    def test_opens_a_nested_list_inside_the_parent_item(self):
        self.assertIn("<li>top rule\n<ul>", self.body)

    def test_never_places_a_list_directly_inside_a_list(self):
        self.assertNotIn("<ul>\n<ul>", self.body)
        self.assertNotIn("<ul><ul>", self.body)

    def test_nests_a_four_space_indent_one_level_not_two(self):
        # One outer list plus two nested levels. A fabricated empty list would make it 4.
        self.assertEqual(self.body.count("<ul>"), 3)

    def test_escapes_quotes_in_an_href(self):
        self.assertNotIn('onmouseover="alert1', self.body)
        self.assertIn("onmouseover", self.body)

    def test_renders_one_diagram_per_page(self):
        self.assertEqual(self.index.count('<pre class="mermaid">'), 1)
        self.assertEqual(self.feature.count('<pre class="mermaid">'), 1)

    def test_references_mermaid_relatively_instead_of_inlining_it(self):
        self.assertIn('<script src="assets/mermaid.min.js">', self.index)
        self.assertIn('<script src="../assets/mermaid.min.js">', self.feature)
        self.assertNotIn("VENDORED-SENTINEL", self.index)

    def test_initializes_mermaid_on_each_page(self):
        self.assertIn("mermaid.initialize", self.index)
        self.assertIn("mermaid.initialize", self.feature)

    def test_embeds_a_mockup_in_a_frame_and_as_a_fallback_link_with_a_re_based_path(self):
        self.assertIn('iframe src="../mockups/01-intake.html"', self.feature)
        self.assertIn('target="_blank">Open ../mockups/01-intake.html', self.feature)

    def test_calls_out_the_assumptions(self):
        self.assertIn('class="callout-h"', self.index)

    def test_makes_no_external_request(self):
        for page in (self.index, self.feature):
            self.assertNotIn('src="http', page)
            self.assertNotIn("<link ", page)

    def test_adds_the_review_layer_with_a_spec_keyed_store(self):
        self.assertIn('id="rv-embedded"', self.index)
        self.assertIn('data-rvkey="widget-tracker"', self.index)

    def test_embeds_the_review_comments_on_every_page(self):
        self.assertIn('"section": "overview"', self.index)
        self.assertIn('"section": "overview"', self.feature)

    def test_keeps_a_malformed_review_block_as_an_index_comment(self):
        self.assertIn("must survive as an index comment", self.index)
        self.assertIn('"page": "index"', self.index)

    def test_round_trips_a_resolved_status(self):
        self.assertIn('"status": "resolved"', self.index)

    def test_stamps_html_generated(self):
        self.assertRegex(read(os.path.join(self.spec, "spec.md")), STAMP)


class WithoutMermaidAssetTest(unittest.TestCase):
    def setUp(self):
        root, self.spec = make_spec_dir(with_mermaid_asset=False)
        self.addCleanup(shutil.rmtree, root)
        self.result = render(self.spec)

    def test_exits_0(self):
        self.assertEqual(self.result.returncode, 0, self.result.stderr)

    def test_degrades_diagrams_to_readable_source(self):
        index = read(os.path.join(self.spec, "spec.html"))
        feature = read(os.path.join(self.spec, "html", "feature-intake.html"))
        self.assertIn('<pre class="mermaid">', index)
        self.assertIn("classList.add('raw')", index)
        self.assertIn("classList.add('raw')", feature)

    def test_reports_the_missing_asset(self):
        self.assertIn("not vendored", self.result.stdout)


class MissingStampKeyTest(unittest.TestCase):
    def setUp(self):
        root, spec = make_spec_dir(with_mermaid_asset=False)
        self.addCleanup(shutil.rmtree, root)
        self.spec_md = os.path.join(spec, "spec.md")
        Path(self.spec_md).write_text(read(self.spec_md).replace("html_generated: null\n", ""))
        self.result = render(spec)

    def test_exits_0(self):
        self.assertEqual(self.result.returncode, 0, self.result.stderr)

    def test_inserts_the_key_instead_of_skipping_it(self):
        self.assertRegex(read(self.spec_md), STAMP)

    def test_warns_about_the_insertion(self):
        self.assertIn("was missing", self.result.stderr)


class MissingSpecTest(unittest.TestCase):
    def test_fails_with_a_message_when_spec_md_is_missing(self):
        root = tempfile.mkdtemp(prefix="render-spec-test-")
        self.addCleanup(shutil.rmtree, root)
        shutil.copy(RENDERER, os.path.join(root, "render-spec.py"))
        result = subprocess.run([sys.executable, os.path.join(root, "render-spec.py")],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn("no spec.md", result.stderr)


if __name__ == "__main__":
    unittest.main()
