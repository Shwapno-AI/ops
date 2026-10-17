"""Check that the restored static deployment actually includes its data resource."""
import re
import subprocess
import tempfile
import unittest
from pathlib import Path


class StaticPackagingTests(unittest.TestCase):
    def test_pages_artifact_contains_the_snapshot_used_by_the_original_loader(self):
        workflow = (Path(__file__).resolve().parents[1] / '.github/workflows/deploy-pages.yml').read_text()
        command = re.search(r'      - name: Prepare the website\n        run: \|\n((?:          .+\n)+)', workflow)
        self.assertIsNotNone(command)
        script = '\n'.join(line[10:] for line in command.group(1).splitlines())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'assets').mkdir()
            (root / 'data').mkdir()
            (root / 'index.html').write_text('Synthetic dashboard')
            (root / '.nojekyll').touch()
            (root / 'assets/app.js').write_text('/* Synthetic loader */')
            (root / 'data/ecom.json').write_text('{"synthetic":true}')
            subprocess.run(['sh', '-eu', '-c', script], cwd=root, check=True)
            self.assertEqual((root / '_site/data/ecom.json').read_text(), '{"synthetic":true}')
