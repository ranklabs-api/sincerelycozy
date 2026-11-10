#!/usr/bin/env python3
"""Tests for the Amazon price refresh (availability, per-ASIN keep/drop, commit wrapper).

Uses stdlib unittest and inline data only. Wrapper tests build a temporary
git repo and delete it in tearDown. No fixture files, no installs, no worktrees.
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SCRIPT = ROOT / "scripts" / "refresh-amazon-prices.py"
WRAPPER = ROOT / "scripts" / "refresh-amazon-prices-commit.sh"
ET = ZoneInfo("America/New_York")

SPEC = importlib.util.spec_from_file_location("refresh_amazon_prices", SCRIPT)
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)


NOW = dt.datetime(2026, 11, 10, 18, 40, tzinfo=ET)
FUTURE = "2026-11-12T18:40:00-05:00"
PAST = "2026-11-09T18:40:00-05:00"


def offer_payload(*offers):
    return {"Offers": list(offers)}


class TestAvailability(unittest.TestCase):
    def test_now_shipping_is_instock(self):
        payload = offer_payload(
            {
                "SubCondition": "New",
                "ShippingTime": {"availabilityType": "NOW"},
            }
        )
        self.assertEqual(mod._availability(payload), "https://schema.org/InStock")

    def test_buy_box_winner_fba_without_shipping_type_is_instock(self):
        payload = offer_payload(
            {
                "SubCondition": "New",
                "IsBuyBoxWinner": True,
                "IsFulfilledByAmazon": True,
            }
        )
        self.assertEqual(mod._availability(payload), "https://schema.org/InStock")

    def test_future_with_date_is_preorder(self):
        payload = offer_payload(
            {
                "SubCondition": "New",
                "IsBuyBoxWinner": True,
                "ShippingTime": {"availabilityType": "FUTURE_WITH_DATE", "availableDate": "2026-12-01"},
            }
        )
        self.assertEqual(mod._availability(payload), "https://schema.org/PreOrder")

    def test_backorder_is_preorder(self):
        payload = offer_payload(
            {
                "SubCondition": "New",
                "IsBuyBoxWinner": True,
                "ShippingTime": {"availabilityType": "NOW"},
                "Note": "Item is on backorder",
            }
        )
        self.assertEqual(mod._availability(payload), "https://schema.org/PreOrder")

    def test_total_offer_count_alone_is_out_of_stock(self):
        payload = {"Summary": {"TotalOfferCount": 4}, "Offers": []}
        self.assertEqual(mod._availability(payload), "https://schema.org/OutOfStock")

    def test_subcondition_new_alone_is_out_of_stock(self):
        payload = offer_payload({"SubCondition": "New"})
        self.assertEqual(mod._availability(payload), "https://schema.org/OutOfStock")

    def test_future_without_date_is_out_of_stock(self):
        payload = offer_payload(
            {
                "SubCondition": "New",
                "IsBuyBoxWinner": True,
                "ShippingTime": {"availabilityType": "FUTURE_WITHOUT_DATE"},
            }
        )
        self.assertEqual(mod._availability(payload), "https://schema.org/OutOfStock")

    def test_used_offer_with_now_shipping_is_out_of_stock(self):
        payload = offer_payload(
            {
                "SubCondition": "Used",
                "IsBuyBoxWinner": True,
                "ShippingTime": {"availabilityType": "NOW"},
            }
        )
        self.assertEqual(mod._availability(payload), "https://schema.org/OutOfStock")


def _ok_item(slug, until=FUTURE, price="29.99"):
    meta = next(m for m in mod.PRODUCTS if m["slug"] == slug)
    return {
        "asin": meta["asin"],
        "url": f"https://www.amazon.com/dp/{meta['asin']}",
        "status": "ok",
        "price": price,
        "priceCurrency": "USD",
        "availability": "https://schema.org/InStock",
        "priceValidUntil": until,
    }


def _err(slug, reason="HTTP 500"):
    meta = next(m for m in mod.PRODUCTS if m["slug"] == slug)
    return {
        "asin": meta["asin"],
        "url": f"https://www.amazon.com/dp/{meta['asin']}",
        "status": "error",
        "reason": reason,
    }


def _nobuy(slug):
    meta = next(m for m in mod.PRODUCTS if m["slug"] == slug)
    return {
        "asin": meta["asin"],
        "url": f"https://www.amazon.com/dp/{meta['asin']}",
        "status": "no_buy_box",
        "reason": "no BuyBoxPrices",
    }


class TestMergePerAsin(unittest.TestCase):
    def test_error_keeps_existing_offer_when_window_open(self):
        existing = {
            "priceValidUntil": FUTURE,
            "products": {"rose-petal": _ok_item("rose-petal", FUTURE, "29.99")},
        }
        results = {"rose-petal": _err("rose-petal")}
        for meta in mod.PRODUCTS:
            results.setdefault(meta["slug"], _err(meta["slug"]))
        # only rose-petal had a stored price
        merged = mod.merge_fetch_results(existing, results, NOW)
        kept = merged["rose-petal"]
        self.assertEqual(kept["status"], "ok")
        self.assertEqual(kept["price"], "29.99")
        self.assertEqual(kept["priceValidUntil"], FUTURE)
        dropped = merged["baby-blue"]
        self.assertEqual(dropped["status"], "error")
        self.assertIsNone(dropped["price"])

    def test_error_drops_offer_when_window_expired(self):
        existing = {
            "priceValidUntil": PAST,
            "products": {"rose-petal": _ok_item("rose-petal", PAST, "29.99")},
        }
        results = {meta["slug"]: _err(meta["slug"]) for meta in mod.PRODUCTS}
        results["rose-petal"] = _err("rose-petal", "QuotaExceeded")
        merged = mod.merge_fetch_results(existing, results, NOW)
        dropped = merged["rose-petal"]
        self.assertEqual(dropped["status"], "error")
        self.assertIsNone(dropped["price"])

    def test_falls_back_to_catalog_window_when_item_lacks_its_own(self):
        item = _ok_item("rose-petal")
        item.pop("priceValidUntil")
        existing = {"priceValidUntil": FUTURE, "products": {"rose-petal": item}}
        results = {meta["slug"]: _err(meta["slug"]) for meta in mod.PRODUCTS}
        merged = mod.merge_fetch_results(existing, results, NOW)
        self.assertEqual(merged["rose-petal"]["status"], "ok")
        self.assertEqual(merged["rose-petal"]["price"], "29.99")

    def test_no_buy_box_drops_even_if_window_open(self):
        existing = {
            "priceValidUntil": FUTURE,
            "products": {"rose-petal": _ok_item("rose-petal")},
        }
        results = {meta["slug"]: _err(meta["slug"]) for meta in mod.PRODUCTS}
        results["rose-petal"] = _nobuy("rose-petal")
        merged = mod.merge_fetch_results(existing, results, NOW)
        self.assertEqual(merged["rose-petal"]["status"], "no_buy_box")
        self.assertNotEqual(merged["rose-petal"].get("price"), "29.99")

    def test_successful_fetch_replaces_stored_price(self):
        existing = {
            "priceValidUntil": FUTURE,
            "products": {"rose-petal": _ok_item("rose-petal", FUTURE, "29.99")},
        }
        fresh = _ok_item("rose-petal", price="24.99")
        fresh.pop("priceValidUntil")
        results = {meta["slug"]: _err(meta["slug"]) for meta in mod.PRODUCTS}
        results["rose-petal"] = fresh
        merged = mod.merge_fetch_results(existing, results, NOW)
        self.assertEqual(merged["rose-petal"]["price"], "24.99")
        self.assertEqual(merged["rose-petal"]["status"], "ok")


class TestHtmlDiffGuard(unittest.TestCase):
    SAMPLE_OLD = """<!doctype html>
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "Product",
  "name": "Rose Petal",
  "url": "https://sincerelycozy.com/swaddles/rose-petal"
}
</script>
<body>
        <p>Keep me</p>
        <div class="hero-actions">Shop</div>
</body>
"""

    def test_offer_and_price_markers_are_confined(self):
        new = mod.patch_product_json_ld(
            self.SAMPLE_OLD,
            {
                "@type": "Offer",
                "url": "https://www.amazon.com/dp/B08N2T6RCQ",
                "priceCurrency": "USD",
                "price": "29.99",
                "availability": "https://schema.org/InStock",
                "priceValidUntil": "2026-11-12",
                "itemCondition": "https://schema.org/NewCondition",
            },
        )
        new = mod.upsert_visible_price(new, "29.99")
        self.assertTrue(mod.html_changes_are_confined(self.SAMPLE_OLD, new))

    def test_copy_change_is_not_confined(self):
        new = self.SAMPLE_OLD.replace("Keep me", "Changed copy")
        self.assertFalse(mod.html_changes_are_confined(self.SAMPLE_OLD, new))


def _run(args, cwd, check=True, env=None):
    merged = os.environ.copy()
    if env:
        merged.update(env)
    return subprocess.run(
        args,
        cwd=cwd,
        check=check,
        capture_output=True,
        text=True,
        env=merged,
    )


def _git(cwd, *args, check=True):
    return _run(["git", *args], cwd, check=check)


MIN_HTML = """<!doctype html>
<html><head>
<script type="application/ld+json">
{"@context": "https://schema.org", "@type": "Product", "name": "%(name)s", "url": "https://sincerelycozy.com/swaddles/%(slug)s"}
</script>
</head>
<body>
        <p>Keep me</p>
        <div class="hero-actions">Shop</div>
</body></html>
"""


class TestCommitWrapper(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="sc-price-wrap-")
        self.repo = Path(self.tmpdir) / "repo"
        self.origin = Path(self.tmpdir) / "origin.git"
        self.repo.mkdir()
        self._init_repo()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _init_repo(self):
        (self.repo / "scripts").mkdir()
        (self.repo / "data").mkdir()
        (self.repo / "swaddles").mkdir()
        shutil.copy(SCRIPT, self.repo / "scripts" / "refresh-amazon-prices.py")
        shutil.copy(WRAPPER, self.repo / "scripts" / "refresh-amazon-prices-commit.sh")
        os.chmod(self.repo / "scripts" / "refresh-amazon-prices-commit.sh", 0o755)
        for meta in mod.PRODUCTS:
            html = MIN_HTML % {"name": meta["slug"], "slug": meta["slug"]}
            (self.repo / "swaddles" / f"{meta['slug']}.html").write_text(html)
        (self.repo / "data" / "amazon-prices.json").write_text("{}\n")
        (self.repo / "styles.css").write_text("/* css */\n")
        (self.repo / "README").write_text("readme\n")
        _git(self.repo, "init", "-b", "main")
        _git(self.repo, "config", "user.email", "test@example.com")
        _git(self.repo, "config", "user.name", "Test")
        _git(self.repo, "add", ".")
        _git(self.repo, "commit", "-m", "init")
        _run(["git", "init", "--bare", "-b", "main", str(self.origin)], self.tmpdir)
        _git(self.repo, "remote", "add", "origin", str(self.origin))
        _git(self.repo, "push", "-u", "origin", "main")

    def _stub(self, body: str) -> Path:
        path = Path(self.tmpdir) / "stub_refresh.py"
        path.write_text("#!/usr/bin/env python3\n" + body)
        os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)
        return path

    def _wrapper(self, stub: Path | None = None, check=False, extra_args=None, env=None):
        merged = {}
        if stub is not None:
            merged["PRICE_REFRESH_BIN"] = str(stub)
        if env:
            merged.update(env)
        cmd = ["bash", str(self.repo / "scripts" / "refresh-amazon-prices-commit.sh")]
        if extra_args:
            cmd.extend(extra_args)
        return _run(cmd, self.repo, check=check, env=merged)

    def _origin_sha(self):
        return _git(self.origin, "rev-parse", "refs/heads/main").stdout.strip()

    def _head_sha(self):
        return _git(self.repo, "rev-parse", "HEAD").stdout.strip()

    def _log_count(self):
        return int(_git(self.repo, "rev-list", "--count", "HEAD").stdout.strip())

    def test_refuses_when_not_on_main(self):
        _git(self.repo, "checkout", "-b", "topic")
        result = self._wrapper()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must be on main", result.stderr)
        _git(self.repo, "checkout", "main")
        self.assertEqual(self._log_count(), 1)

    def test_refuses_when_main_behind_origin(self):
        (self.repo / "README").write_text("ahead on origin\n")
        _git(self.repo, "add", "README")
        _git(self.repo, "commit", "-m", "origin only")
        _git(self.repo, "push", "origin", "main")
        _git(self.repo, "reset", "--hard", "HEAD~1")
        result = self._wrapper()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("!= origin/main", result.stderr)
        self.assertEqual(self._log_count(), 1)

    def test_refuses_when_tree_dirty(self):
        (self.repo / "README").write_text("dirty\n")
        result = self._wrapper()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not clean", result.stderr)
        self.assertEqual(self._log_count(), 1)

    def test_exit_1_reverts_and_does_not_commit(self):
        stub = self._stub(
            """
import pathlib, sys
root = pathlib.Path(sys.argv[sys.argv.index('--root') + 1])
(root / 'swaddles' / 'rose-petal.html').write_text('BROKEN')
(root / 'README').write_text('also dirty')
sys.exit(1)
"""
        )
        before = (self.repo / "swaddles" / "rose-petal.html").read_text()
        result = self._wrapper(stub)
        self.assertEqual(result.returncode, 1)
        self.assertIn("reverting the working tree", result.stderr)
        self.assertEqual((self.repo / "swaddles" / "rose-petal.html").read_text(), before)
        self.assertEqual((self.repo / "README").read_text(), "readme\n")
        self.assertEqual(self._log_count(), 1)

    def test_exit_2_alerts_and_does_not_commit(self):
        stub = self._stub("import sys\nsys.exit(2)\n")
        result = self._wrapper(stub)
        self.assertEqual(result.returncode, 2)
        self.assertIn("ALERT:SHEIK:price-refresh:exit=2", result.stderr)
        self.assertEqual(self._log_count(), 1)
        self.assertEqual(_git(self.repo, "status", "--porcelain").stdout, "")

    def test_exit_0_commits_only_allowed_files(self):
        stub = self._stub(
            r"""
import json, pathlib, sys
root = pathlib.Path(sys.argv[sys.argv.index('--root') + 1])
page = root / 'swaddles' / 'rose-petal.html'
text = page.read_text()
# confined Offer + price markers
if '"offers"' not in text:
    text = text.replace(
        '"url": "https://sincerelycozy.com/swaddles/rose-petal"',
        '"offers": {"@type": "Offer", "price": "29.99", "priceCurrency": "USD", "availability": "https://schema.org/InStock", "url": "https://www.amazon.com/dp/B08N2T6RCQ", "priceValidUntil": "2026-11-12", "itemCondition": "https://schema.org/NewCondition"}, "url": "https://sincerelycozy.com/swaddles/rose-petal"',
        1,
    )
    text = text.replace(
        '        <div class="hero-actions">Shop</div>',
        '<!-- amazon-price:start -->\n        <p class="product-price">$29.99 <span>on Amazon</span></p>\n        <!-- amazon-price:end -->\n        <div class="hero-actions">Shop</div>',
        1,
    )
    page.write_text(text)
(root / 'data' / 'amazon-prices.json').write_text(json.dumps({"ok": True}) + '\n')
sys.exit(0)
"""
        )
        result = self._wrapper(stub)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self._log_count(), 2)
        names = _git(self.repo, "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD").stdout.split()
        self.assertEqual(sorted(names), ["data/amazon-prices.json", "swaddles/rose-petal.html"])
        self.assertIn("Committed locally", result.stdout)
        self.assertIn("gated on an explicit GO", result.stdout)
        self.assertNotEqual(self._head_sha(), self._origin_sha())

    def test_exit_0_refuses_other_dirty_path(self):
        stub = self._stub(
            """
import pathlib, sys
root = pathlib.Path(sys.argv[sys.argv.index('--root') + 1])
(root / 'styles.css').write_text('changed css\\n')
(root / 'data' / 'amazon-prices.json').write_text('{"ok": true}\\n')
sys.exit(0)
"""
        )
        result = self._wrapper(stub)
        self.assertEqual(result.returncode, 1)
        self.assertIn("dirty path not allowed: styles.css", result.stderr)
        self.assertEqual(self._log_count(), 1)

    def test_exit_0_refuses_html_hunk_outside_markers(self):
        stub = self._stub(
            """
import pathlib, sys
root = pathlib.Path(sys.argv[sys.argv.index('--root') + 1])
page = root / 'swaddles' / 'rose-petal.html'
page.write_text(page.read_text().replace('Keep me', 'Changed copy'))
sys.exit(0)
"""
        )
        result = self._wrapper(stub)
        self.assertEqual(result.returncode, 1)
        self.assertIn("html diff outside Offer JSON-LD / amazon-price markers", result.stderr)
        self.assertEqual(self._log_count(), 1)

    def test_refuses_json_unlink(self):
        stub = self._stub(
            """
import pathlib, sys
root = pathlib.Path(sys.argv[sys.argv.index('--root') + 1])
(root / 'data' / 'amazon-prices.json').unlink()
sys.exit(0)
"""
        )
        result = self._wrapper(stub)
        self.assertEqual(result.returncode, 1)
        combined = result.stdout + result.stderr
        self.assertTrue(
            "required file is missing: data/amazon-prices.json" in combined
            or "deletion not allowed: data/amazon-prices.json" in combined,
            combined,
        )
        self.assertEqual(self._log_count(), 1)
        self.assertFalse(self._head_sha() != _git(self.repo, "rev-parse", "main").stdout.strip())

    def test_refuses_git_rm(self):
        stub = self._stub(
            """
import pathlib, subprocess, sys
root = pathlib.Path(sys.argv[sys.argv.index('--root') + 1])
subprocess.check_call(['git', '-C', str(root), 'rm', '--', 'data/amazon-prices.json'])
sys.exit(0)
"""
        )
        result = self._wrapper(stub)
        self.assertEqual(result.returncode, 1)
        combined = result.stdout + result.stderr
        self.assertTrue(
            "required file is missing: data/amazon-prices.json" in combined
            or "deletion not allowed: data/amazon-prices.json" in combined
            or "staged entry not allowed: data/amazon-prices.json" in combined,
            combined,
        )
        self.assertEqual(self._log_count(), 1)

    def test_refuses_unlink_plus_html_edit(self):
        stub = self._stub(
            r"""
import pathlib, sys
root = pathlib.Path(sys.argv[sys.argv.index('--root') + 1])
page = root / 'swaddles' / 'rose-petal.html'
text = page.read_text()
if '"offers"' not in text:
    text = text.replace(
        '"url": "https://sincerelycozy.com/swaddles/rose-petal"',
        '"offers": {"@type": "Offer", "price": "29.99", "priceCurrency": "USD", "availability": "https://schema.org/InStock", "url": "https://www.amazon.com/dp/B08N2T6RCQ", "priceValidUntil": "2026-11-12", "itemCondition": "https://schema.org/NewCondition"}, "url": "https://sincerelycozy.com/swaddles/rose-petal"',
        1,
    )
    text = text.replace(
        '        <div class="hero-actions">Shop</div>',
        '<!-- amazon-price:start -->\n        <p class="product-price">$29.99 <span>on Amazon</span></p>\n        <!-- amazon-price:end -->\n        <div class="hero-actions">Shop</div>',
        1,
    )
    page.write_text(text)
(root / 'data' / 'amazon-prices.json').unlink()
sys.exit(0)
"""
        )
        result = self._wrapper(stub)
        self.assertEqual(result.returncode, 1)
        combined = result.stdout + result.stderr
        self.assertTrue(
            "required file is missing: data/amazon-prices.json" in combined
            or "deletion not allowed: data/amazon-prices.json" in combined,
            combined,
        )
        self.assertEqual(self._log_count(), 1)
        names = _git(self.repo, "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD").stdout.split()
        self.assertEqual(names, [])  # still the init commit; no price commit

    def test_check_cached_index_rejects_staged_deletion(self):
        _git(self.repo, "rm", "--", "data/amazon-prices.json")
        problems = mod.check_cached_index(self.repo)
        joined = "\n".join(problems)
        self.assertTrue(problems, joined)
        self.assertIn("data/amazon-prices.json", joined)
        self.assertTrue("missing" in joined or "not allowed" in joined, joined)

    def test_push_updates_origin_main(self):
        stub = self._stub(
            r"""
import json, pathlib, sys
root = pathlib.Path(sys.argv[sys.argv.index('--root') + 1])
page = root / 'swaddles' / 'rose-petal.html'
text = page.read_text()
if '"offers"' not in text:
    text = text.replace(
        '"url": "https://sincerelycozy.com/swaddles/rose-petal"',
        '"offers": {"@type": "Offer", "price": "29.99", "priceCurrency": "USD", "availability": "https://schema.org/InStock", "url": "https://www.amazon.com/dp/B08N2T6RCQ", "priceValidUntil": "2026-11-12", "itemCondition": "https://schema.org/NewCondition"}, "url": "https://sincerelycozy.com/swaddles/rose-petal"',
        1,
    )
    text = text.replace(
        '        <div class="hero-actions">Shop</div>',
        '<!-- amazon-price:start -->\n        <p class="product-price">$29.99 <span>on Amazon</span></p>\n        <!-- amazon-price:end -->\n        <div class="hero-actions">Shop</div>',
        1,
    )
    page.write_text(text)
(root / 'data' / 'amazon-prices.json').write_text(json.dumps({"ok": True}) + '\n')
sys.exit(0)
"""
        )
        result = self._wrapper(stub, extra_args=["--push"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self._log_count(), 2)
        self.assertEqual(self._head_sha(), self._origin_sha())
        self.assertIn("Pushed HEAD to origin/main", result.stdout)
        names = _git(self.origin, "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD").stdout.split()
        # bare repo HEAD is the tip
        names = _git(self.origin, "diff-tree", "--no-commit-id", "--name-only", "-r", "refs/heads/main").stdout.split()
        self.assertEqual(sorted(names), ["data/amazon-prices.json", "swaddles/rose-petal.html"])

    def test_push_failure_non_fast_forward(self):
        stub = self._stub(
            r"""
import json, os, pathlib, subprocess, sys
root = pathlib.Path(sys.argv[sys.argv.index('--root') + 1])
page = root / 'swaddles' / 'rose-petal.html'
text = page.read_text()
if '"offers"' not in text:
    text = text.replace(
        '"url": "https://sincerelycozy.com/swaddles/rose-petal"',
        '"offers": {"@type": "Offer", "price": "29.99", "priceCurrency": "USD", "availability": "https://schema.org/InStock", "url": "https://www.amazon.com/dp/B08N2T6RCQ", "priceValidUntil": "2026-11-12", "itemCondition": "https://schema.org/NewCondition"}, "url": "https://sincerelycozy.com/swaddles/rose-petal"',
        1,
    )
    text = text.replace(
        '        <div class="hero-actions">Shop</div>',
        '<!-- amazon-price:start -->\n        <p class="product-price">$29.99 <span>on Amazon</span></p>\n        <!-- amazon-price:end -->\n        <div class="hero-actions">Shop</div>',
        1,
    )
    page.write_text(text)
(root / 'data' / 'amazon-prices.json').write_text(json.dumps({"ok": True}) + '\n')
origin = os.environ['TEST_ORIGIN']
ident = {
    **os.environ,
    'GIT_AUTHOR_NAME': 'Test',
    'GIT_AUTHOR_EMAIL': 'test@example.com',
    'GIT_COMMITTER_NAME': 'Test',
    'GIT_COMMITTER_EMAIL': 'test@example.com',
}
head = subprocess.check_output(['git', '-C', origin, 'rev-parse', 'refs/heads/main'], text=True).strip()
tree = subprocess.check_output(['git', '-C', origin, 'rev-parse', head + '^{tree}'], text=True).strip()
new = subprocess.check_output(
    ['git', '-C', origin, 'commit-tree', tree, '-p', head, '-m', 'origin moved'],
    text=True,
    env=ident,
).strip()
subprocess.check_call(['git', '-C', origin, 'update-ref', 'refs/heads/main', new])
sys.exit(0)
"""
        )
        result = self._wrapper(
            stub,
            extra_args=["--push"],
            env={"TEST_ORIGIN": str(self.origin)},
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ALERT:SHEIK:price-refresh:push-failed", result.stderr)
        # fetch + reset --hard should land on the moved origin tip, dropping the local price commit
        self.assertEqual(self._head_sha(), self._origin_sha())
        log_msg = _git(self.repo, "log", "-1", "--format=%s").stdout
        self.assertIn("origin moved", log_msg)
        self.assertNotIn("refresh Amazon Buy Box prices", log_msg)

    def test_push_failure_missing_remote(self):
        stub = self._stub(
            r"""
import json, pathlib, subprocess, sys
root = pathlib.Path(sys.argv[sys.argv.index('--root') + 1])
page = root / 'swaddles' / 'rose-petal.html'
text = page.read_text()
if '"offers"' not in text:
    text = text.replace(
        '"url": "https://sincerelycozy.com/swaddles/rose-petal"',
        '"offers": {"@type": "Offer", "price": "29.99", "priceCurrency": "USD", "availability": "https://schema.org/InStock", "url": "https://www.amazon.com/dp/B08N2T6RCQ", "priceValidUntil": "2026-11-12", "itemCondition": "https://schema.org/NewCondition"}, "url": "https://sincerelycozy.com/swaddles/rose-petal"',
        1,
    )
    text = text.replace(
        '        <div class="hero-actions">Shop</div>',
        '<!-- amazon-price:start -->\n        <p class="product-price">$29.99 <span>on Amazon</span></p>\n        <!-- amazon-price:end -->\n        <div class="hero-actions">Shop</div>',
        1,
    )
    page.write_text(text)
(root / 'data' / 'amazon-prices.json').write_text(json.dumps({"ok": True}) + '\n')
subprocess.check_call(['git', '-C', str(root), 'remote', 'remove', 'origin'])
sys.exit(0)
"""
        )
        result = self._wrapper(stub, extra_args=["--push"])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ALERT:SHEIK:price-refresh:push-failed", result.stderr)
        # origin is gone, so reset may not drop the local commit; still must exit nonzero


if __name__ == "__main__":
    unittest.main()
