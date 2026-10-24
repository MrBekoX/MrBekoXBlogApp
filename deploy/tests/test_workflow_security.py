"""Guard publication privileges and private-context boundaries without running CI."""

from __future__ import annotations

import ast
from pathlib import Path
import re
import subprocess
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github/workflows"


def workflow(name: str) -> dict:
    # BaseLoader preserves GitHub's `on` key and boolean input expressions.
    return yaml.load((WORKFLOWS / name).read_text(), Loader=yaml.BaseLoader)


def condition_value(expression: str, *, requested: bool, ref: str) -> bool:
    expression = expression.replace("inputs.push_images", "requested").replace("github.ref", "ref")
    expression = expression.replace("&&", " and ").replace("||", " or ")
    tree = ast.parse(expression, mode="eval")
    allowed = (ast.Expression, ast.BoolOp, ast.And, ast.Or, ast.Compare, ast.Eq,
               ast.Name, ast.Load, ast.Constant)
    if any(not isinstance(node, allowed) for node in ast.walk(tree)):
        raise AssertionError("Publication conditions must use the reviewed boolean gate")
    return bool(eval(compile(tree, "publication-condition", "eval"), {"__builtins__": {}},
                     {"requested": requested, "ref": ref}))


class WorkflowSecurityTests(unittest.TestCase):
    def test_actions_are_immutable_and_checkout_does_not_persist_credentials(self):
        for path in sorted([*WORKFLOWS.glob("*.yml"), *WORKFLOWS.glob("*.yaml")]):
            document = workflow(path.name)
            self.assertEqual(document["permissions"], {"contents": "read"}, path.name)
            self.assertNotIn("pull_request_target", document["on"], path.name)
            for job_name, job in document["jobs"].items():
                self.assertNotIn("uses", job, "Reusable workflows require explicit security review")
                is_publisher = path.name == "image-build.yml" and job_name == "publish"
                permissions = job.get("permissions", document["permissions"])
                if not is_publisher:
                    self.assertNotIn("write", permissions.values())
                    runs = "\n".join(step.get("run", "") for step in job.get("steps", []))
                    self.assertNotRegex(runs, r"\bdocker\s+push\b|(?m:^\s*(?:ssh|scp)\s)|(?:\./|bash\s+)deploy\.sh")
                for step in job.get("steps", []):
                    if "uses" not in step:
                        continue
                    self.assertRegex(step["uses"], r"^[\w.-]+/[\w.-]+@[0-9a-f]{40}$")
                    if step["uses"].startswith("actions/checkout@"):
                        self.assertEqual(step.get("with", {}).get("persist-credentials"), "false")

    def test_only_manual_main_publication_can_receive_package_write(self):
        release = workflow("image-build.yml")
        self.assertEqual(set(release["on"]), {"workflow_dispatch"})
        inputs = release["on"]["workflow_dispatch"]["inputs"]
        self.assertEqual(inputs["push_images"]["default"], "false")
        self.assertFalse(any(re.search(r"profile|biography|bundle|password|secret|token|credential", name)
                             for name in inputs))
        publish = release["jobs"]["publish"]
        self.assertEqual(publish["permissions"], {"contents": "read", "packages": "write"})
        self.assertEqual(publish["needs"], "build")
        for requested in (False, True):
            for ref in ("refs/heads/main", "refs/heads/feature", "refs/pull/1/merge"):
                self.assertEqual(condition_value(publish["if"], requested=requested, ref=ref),
                                 requested and ref == "refs/heads/main")
        for name, job in release["jobs"].items():
            if name != "publish":
                self.assertEqual(job.get("permissions", release["permissions"]), {"contents": "read"})
        for job in workflow("ai-agent-ci.yml")["jobs"].values():
            self.assertNotIn("write", job.get("permissions", {}).values())

    def test_exact_new_image_archives_are_scanned_before_transfer(self):
        build = workflow("image-build.yml")["jobs"]["build"]
        steps = build["steps"]
        uploads = [(index, step) for index, step in enumerate(steps)
                   if step.get("uses", "").startswith("actions/upload-artifact@")]
        self.assertEqual(len(uploads), 1)
        upload_index, upload = uploads[0]
        self.assertEqual(upload["if"], "inputs.push_images")
        paths = {line.strip() for line in upload["with"]["path"].splitlines() if line.strip()}
        expected = {"${{ runner.temp }}/release-images/" + name
                    for name in ("api.tar", "agent.tar", "web.tar", "checksums.sha256")}
        self.assertEqual(paths, expected)
        scans = [(index, step) for index, step in enumerate(steps)
                 if step.get("uses", "").startswith("aquasecurity/trivy-action@")]
        self.assertEqual({step["with"]["input"] for _, step in scans},
                         expected - {"${{ runner.temp }}/release-images/checksums.sha256"})
        for index, step in scans:
            self.assertLess(index, upload_index)
            self.assertNotIn("if", step)
            self.assertNotEqual(step.get("continue-on-error"), "true")
            self.assertEqual(step["with"]["scan-type"], "image")
            self.assertEqual(step["with"]["exit-code"], "1")
            self.assertEqual(step["with"]["ignore-unfixed"], "false")
            self.assertTrue({"vuln", "secret"}.issubset(step["with"]["scanners"].split(",")))
        runs = "\n".join(step.get("run", "") for step in steps)
        self.assertIn("docker image save", runs)
        self.assertNotRegex(runs, r"docker\s+(login|push)\b")

    def test_publisher_verifies_build_outputs_without_executing_repository_source(self):
        publish = workflow("image-build.yml")["jobs"]["publish"]
        download = [step for step in publish["steps"]
                    if step.get("uses", "").startswith("actions/download-artifact@")]
        self.assertEqual(len(download), 1)
        self.assertEqual(download[0]["with"]["artifact-ids"], "${{ needs.build.outputs.artifact_id }}")
        self.assertNotIn("run-id", download[0]["with"])
        self.assertNotIn("repository", download[0]["with"])
        self.assertFalse(any(step.get("uses", "").startswith("actions/checkout@")
                             for step in publish["steps"]))
        runs = "\n".join(step.get("run", "") for step in publish["steps"])
        self.assertNotRegex(runs, r"docker\s+(?:image\s+)?build\b|\bnpm\b|\bpip\b")
        self.assertLess(runs.index("sha256sum --check --strict"), runs.index("docker login"))
        self.assertLess(runs.index('[[ "$actual_id" == "$expected_id" ]]'), runs.index("docker login"))
        verify = next(step for step in publish["steps"] if "EXPECTED_API_ID" in step.get("env", {}))
        for component in ("API", "AGENT", "WEB"):
            self.assertEqual(verify["env"][f"EXPECTED_{component}_ID"],
                             "${{ needs.build.outputs." + component.lower() + "_image_id }}")

    def test_local_builder_cannot_publish_and_legacy_workflow_is_absent(self):
        self.assertFalse((WORKFLOWS / "ci-cd.yml").exists())
        script = (ROOT / "deploy/deploy-to-hub.ps1").read_text()
        self.assertIn("if ($Push) { throw", script)
        self.assertNotRegex(script, r"docker\s+(login|push)\b|@\('push'")
        for path in ("private/publication-probe.env", "feature-prompts/source.md", "docker/.env",
                     ".github/workflows/local.env"):
            result = subprocess.run(["git", "check-ignore", "--quiet", path], cwd=ROOT)
            self.assertEqual(result.returncode, 0, path)
        result = subprocess.run(["git", "check-ignore", "--quiet", ".github/workflows/publication-probe.yml"], cwd=ROOT)
        self.assertEqual(result.returncode, 1, "Public workflows must use normal Git tracking")

    def test_base_images_are_immutable_and_private_contexts_cannot_be_reincluded(self):
        for component in ("backend", "frontend", "ai-agent-service"):
            dockerfile = ROOT / "docker" / component / "Dockerfile"
            for line in dockerfile.read_text().splitlines():
                if line.startswith("FROM "):
                    self.assertRegex(line.split()[1], r"@sha256:[0-9a-f]{64}$")
            patterns = {line.strip() for line in dockerfile.with_name("Dockerfile.dockerignore").read_text().splitlines()
                        if line.strip() and not line.lstrip().startswith("#")}
            self.assertTrue({"**/private", "**/feature-prompts", "**/author-profile.local",
                             "**/.agent_checkpoints", "**/*.env"}.issubset(patterns))
            self.assertFalse(any(pattern.startswith("!") for pattern in patterns))
        for job in workflow("ai-agent-ci.yml")["jobs"].values():
            for service in job.get("services", {}).values():
                self.assertRegex(service["image"], r"@sha256:[0-9a-f]{64}$")


if __name__ == "__main__":
    unittest.main()
