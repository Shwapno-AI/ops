"""Exercise real static artifact packaging with synthetic private data."""
import subprocess
import tempfile
import unittest
from pathlib import Path


class PublicationTests(unittest.TestCase):
    def test_pages_artifact_keeps_dashboard_assets_but_excludes_customer_snapshots(self):
        script = Path(__file__).resolve().parents[1] / "scripts/prepare-pages.sh"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "assets").mkdir()
            (root / "data").mkdir()
            (root / "index.html").write_text("Synthetic dashboard")
            (root / ".nojekyll").touch()
            (root / "assets/app.js").write_text("/* Synthetic app */")
            (root / "data/data.json").write_text('{"public":true}')
            for suffix in ("", ".gz", ".br", ".tmp"):
                (root / ("data/ecom.json" + suffix)).write_text('{"private":"synthetic"}')
            subprocess.run(["sh", str(script)], cwd=root, check=True)
            self.assertTrue((root / "_site/assets/app.js").exists())
            self.assertTrue((root / "_site/data/data.json").exists())
            self.assertEqual(list((root / "_site/data").glob("ecom.json*")), [])
