import subprocess
import tempfile
import unittest
from pathlib import Path


DEPLOY = Path(__file__).resolve().parents[1] / "scripts" / "deploy"


class DeploymentEntrypointTests(unittest.TestCase):
    def invoke(self, *args):
        return subprocess.run([str(DEPLOY), *args], capture_output=True, text=True)

    def test_rejects_invalid_input(self):
        with tempfile.TemporaryDirectory() as directory:
            artifact = Path(directory) / "release.tar.gz"
            artifact.write_bytes(b"fixture")
            for args in [(), ("other", str(artifact)), ("staging", directory),
                         ("production", str(artifact) + ".missing")]:
                with self.subTest(args=args):
                    self.assertEqual(self.invoke(*args).returncode, 2)

    def test_unimplemented_deployment_fails_without_changing_artifact(self):
        with tempfile.TemporaryDirectory() as directory:
            artifact = Path(directory) / "release.tar.gz"
            artifact.write_bytes(b"fixture")
            for environment in ["staging", "production"]:
                with self.subTest(environment=environment):
                    result = self.invoke(environment, str(artifact))
                    self.assertEqual(result.returncode, 1)
                    self.assertIn("No deployment performed", result.stderr)
                    self.assertEqual(artifact.read_bytes(), b"fixture")


if __name__ == "__main__":
    unittest.main()
