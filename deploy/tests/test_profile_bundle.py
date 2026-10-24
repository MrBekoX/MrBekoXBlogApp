"""Private source packaging checks; no personal source data or AI simulation."""

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


spec = importlib.util.spec_from_file_location("profile_bundle", Path(__file__).resolve().parents[1] / "profile_bundle.py")
bundle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bundle)


class ProfileBundleTests(unittest.TestCase):
    def test_private_source_bytes_and_metadata_are_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "approved.md"
            raw = "# Ben Kimim: Deployment Owner\r\n\r\n## Kısaca\r\nApproved deployment biography.\r\n\r\n## Teknik yetkinliklerim\r\n- PostgreSQL\r\n".encode()
            source.write_bytes(raw)
            output = root / "private-bundle"
            bundle.build_bundle(source, output, as_of="2026-10-21", revision=1, approved=True)
            self.assertEqual((output / "source/author-profile.source.md").read_bytes(), raw)
            self.assertEqual(bundle.validate_bundle(output), [])
            profile = json.loads((output / "profile.json").read_bytes())
            self.assertEqual(profile["owner"]["name"], "Deployment Owner")
            self.assertEqual(profile["sections"][0]["title"]["en"], "Kısaca")
            profile["sections"][0]["body"] = "Tampered"
            (output / "profile.json").write_text(json.dumps(profile))
            self.assertIn("hash", " ".join(bundle.validate_bundle(output)))

    def test_repository_example_is_not_a_production_bundle(self):
        example = Path(__file__).resolve().parents[2] / "src/content/author-profile"
        self.assertTrue(bundle.validate_bundle(example))

    def test_approval_is_required_and_existing_output_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "approved.md"
            source.write_text("# Ben Kimim: Deployment Owner\n\n## Kısaca\nDeployment biography.")
            output = root / "output"
            with self.assertRaises(ValueError):
                bundle.build_bundle(source, output, as_of="2026-10-21", revision=1, approved=False)
            output.mkdir()
            sentinel = output / "existing.txt"
            sentinel.write_text("preserve")
            with self.assertRaises(ValueError):
                bundle.build_bundle(source, output, as_of="2026-10-21", revision=1, approved=True)
            self.assertEqual(sentinel.read_text(), "preserve")


if __name__ == "__main__":
    unittest.main()
