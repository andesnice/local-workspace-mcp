"""Exercise the exact-file watcher API used by md-to-pdf after the v4 override."""
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(
    not (ROOT / "node_modules").exists(), reason="Run npm ci first"
)


def test_pdf_dependency_load_and_literal_file_watch(tmp_path):
    script = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const {createRequire} = require('node:module');
const pdfRequire = createRequire(require.resolve('md-to-pdf'));
const {watch} = pdfRequire('chokidar');
assert.equal(typeof require('md-to-pdf').mdToPdf, 'function');
(async () => {
  // Braces are literal filename characters, not a request for pattern expansion.
  const file = path.join(process.argv[1], 'literal{a,b}.md');
  await fs.writeFile(file, '# Before');
  const watcher = watch([file], {ignoreInitial: true});
  const deadline = setTimeout(() => { console.error('watch timeout'); process.exit(1); }, 8000);
  try {
    await new Promise((resolve, reject) => watcher.once('ready', resolve).once('error', reject));
    const changed = new Promise((resolve, reject) => watcher.once('change', resolve).once('error', reject));
    await fs.writeFile(file, '# After');
    assert.equal(await changed, file);
    assert.equal(await fs.readFile(file, 'utf8'), '# After');
  } finally {
    clearTimeout(deadline);
    await watcher.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
"""
    subprocess.run(["node", "-e", script, str(tmp_path)], cwd=ROOT, check=True, timeout=15)
