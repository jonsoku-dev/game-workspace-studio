"""Every engine runtime samples model-assets embers with the same contract as tools/ember.py."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
RUNTIMES = {
    'web': ROOT / 'engines/web/game.mjs',
    'godot': ROOT / 'engines/godot/studio_runtime.gd',
    'unity': ROOT / 'engines/unity/Assets/StudioRuntime.cs',
}


class EmberContractTests(unittest.TestCase):
    def test_runtimes_use_life_fraction_lateral_arc_and_sqrt_envelope(self):
        for name, path in RUNTIMES.items():
            source = path.read_text()
            with self.subTest(runtime=name):
                self.assertIn('ember contract', source)
                # Drift is scaled by the life fraction u, not by seconds of age.
                self.assertRegex(source, r'drift[^\n]*\*\s*u\b|addScaledVector\([^)]*drift\),u\)')
                self.assertNotRegex(source, r'drift\)?\s*\*\s*age')
                self.assertRegex(source, r'0\.35|\.35')
                self.assertRegex(source, re.compile(r'sqrt', re.IGNORECASE))


if __name__ == '__main__':
    unittest.main()
