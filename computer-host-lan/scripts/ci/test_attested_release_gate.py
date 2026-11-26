import copy
import unittest
from unittest.mock import patch

from attested_release_gate import (
    REPO, REPO_ID, check_approval, check_environment, check_jobs, check_ref,
    gate, release_identity, select_run, approval_mode, RC3_APPROVAL, MAINTAINER_ID,
)

SHA = "a" * 40
TAG = "computer-host-lan-v1.0.0-rc.3"
ENV = {"GITHUB_SHA": SHA, "EXPECTED_SHA": SHA, "EXPECTED_TAG": TAG,
       "GITHUB_REF": "refs/tags/" + TAG, "GITHUB_REPOSITORY": REPO,
       "GITHUB_REPOSITORY_ID": str(REPO_ID), "GITHUB_EVENT_NAME": "workflow_dispatch",
       "GITHUB_RUN_ATTEMPT": "1"}
MANIFEST = {"integration": "1.0.0-rc.3", "release_candidate_tag": TAG,
            "release_stage": "attestation-ready-v1.0.0-rc.3"}
RUN = {"head_sha": SHA, "head_branch": "main", "event": "workflow_dispatch",
       "head_repository": {"id": REPO_ID}, "run_number": 10, "run_attempt": 1,
       "status": "completed", "conclusion": "success"}
ENVIRONMENT = {"id": 99, "can_admins_bypass": False, "protection_rules": [{"type": "required_reviewers",
               "reviewers": [{"type": "User", "reviewer": {"id": 2}}],
               "prevent_self_review": True}], "deployment_branch_policy": {
                   "protected_branches": False, "custom_branch_policies": True}}
POLICIES = {"total_count": 1, "branch_policies": [{"type": "tag", "name": TAG}]}


class GateTests(unittest.TestCase):
    def test_identity(self):
        self.assertEqual(release_identity(ENV, MANIFEST), (SHA, TAG))
        for key, value in {"GITHUB_SHA": "b" * 40, "EXPECTED_SHA": "b" * 40,
                           "GITHUB_REPOSITORY": "other/repo", "GITHUB_REPOSITORY_ID": "0",
                           "GITHUB_REF": "refs/heads/main", "GITHUB_EVENT_NAME": "push",
                           "GITHUB_RUN_ATTEMPT": "2", "EXPECTED_TAG": "bad"}.items():
            with self.subTest(key=key), self.assertRaises(ValueError):
                release_identity(dict(ENV, **{key: value}), MANIFEST)
        for version in ("1.0.0-rc.2", "1.1.0", "1.0.0-rc.03"):
            tag = "computer-host-lan-v" + version
            with self.subTest(version=version), self.assertRaises(ValueError):
                release_identity(dict(ENV, EXPECTED_TAG=tag, GITHUB_REF="refs/tags/" + tag),
                                 dict(MANIFEST, integration=version, release_candidate_tag=tag,
                                      release_stage="attestation-ready-v" + version))
        with self.assertRaises(ValueError):
            release_identity(ENV, dict(MANIFEST, release_stage="rc-published"))

    def test_rc3_exception_identity(self):
        env = dict(ENV, GITHUB_ACTOR_ID=MAINTAINER_ID, CREATE_DRAFT="false")
        manifest = dict(MANIFEST, linux_attestation_approval=RC3_APPROVAL)
        self.assertEqual(approval_mode(env, manifest), RC3_APPROVAL)
        self.assertEqual(approval_mode(env, MANIFEST), "independent")
        for bad in (dict(env, GITHUB_ACTOR_ID="2"), dict(env, CREATE_DRAFT="true"),
                    dict(env, EXPECTED_TAG="computer-host-lan-v1.0.0")):
            with self.assertRaises(ValueError):
                approval_mode(bad, manifest)
        for version in ("1.0.0", "1.0.0-rc.4"):
            with self.assertRaises(ValueError):
                approval_mode(env, dict(manifest, integration=version))
        with self.assertRaises(ValueError):
            approval_mode(env, dict(manifest, linux_attestation_approval="unknown"))

    def test_rc3_exception_environment_and_approval(self):
        e = copy.deepcopy(ENVIRONMENT)
        e["protection_rules"][0]["prevent_self_review"] = False
        e["protection_rules"][0]["reviewers"][0]["reviewer"]["id"] = int(MAINTAINER_ID)
        check_environment(e, POLICIES, TAG, RC3_APPROVAL)
        for bad in (ENVIRONMENT, dict(e, can_admins_bypass=True),
                    dict(e, protection_rules=[])):
            with self.assertRaises(ValueError):
                check_environment(bad, POLICIES, TAG, RC3_APPROVAL)
        with self.assertRaises(ValueError):
            check_environment(e, POLICIES, TAG)
        with self.assertRaises(ValueError):
            check_environment(e, POLICIES, "computer-host-lan-v1.0.0", RC3_APPROVAL)
        review = {"state": "approved", "user": {"id": int(MAINTAINER_ID)}, "environments": [{"id": 99}]}
        check_approval([review], e, MAINTAINER_ID, RC3_APPROVAL)
        for bad in ([], [dict(review, user={"id": 2})], [dict(review, state="rejected")]):
            with self.assertRaises(ValueError):
                check_approval(bad, e, MAINTAINER_ID, RC3_APPROVAL)
        with self.assertRaises(ValueError):
            check_approval([review], e, MAINTAINER_ID)

    def test_ref(self):
        check_ref({"object": {"type": "commit", "sha": SHA}}, SHA)
        for obj in ({"type": "tag", "sha": SHA}, {"type": "commit", "sha": "b" * 40}):
            with self.assertRaises(ValueError):
                check_ref({"object": obj}, SHA)

    def test_latest_exact_main_run(self):
        def response(*runs):
            return {"total_count": len(runs), "workflow_runs": list(runs)}
        self.assertEqual(select_run(response(RUN), SHA), RUN)
        for patch in ({"head_branch": "topic"}, {"event": "pull_request"},
                      {"head_sha": "b" * 40}, {"head_repository": {"id": 1}}):
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                select_run(response(dict(RUN, **patch)), SHA)
        with self.assertRaises(ValueError):
            select_run(response(RUN, dict(RUN, run_number=11, conclusion="failure")), SHA)
        with self.assertRaises(ValueError):
            select_run(dict(response(RUN), total_count=2), SHA)

    def test_jobs(self):
        expected = {"matrix": 2, "build": 1}
        jobs = [{"name": name, "status": "completed", "conclusion": "success"}
                for name in ("matrix (a)", "matrix (b)", "build")]
        check_jobs({"total_count": 3, "jobs": jobs}, expected)
        for bad in (jobs[:2], [jobs[0], jobs[0], jobs[2]],
                    [*jobs[:2], dict(jobs[2], conclusion="skipped")],
                    [*jobs[:2], dict(jobs[2], name="other")]):
            with self.assertRaises(ValueError):
                check_jobs({"total_count": len(bad), "jobs": bad}, expected)

    def test_environment(self):
        check_environment(ENVIRONMENT, POLICIES, TAG)
        for field, value in (("reviewers", []), ("prevent_self_review", False)):
            bad = copy.deepcopy(ENVIRONMENT)
            bad["protection_rules"][0][field] = value
            with self.assertRaises(ValueError):
                check_environment(bad, POLICIES, TAG)
        for policy in ({"type": "branch", "name": TAG}, {"type": "tag", "name": "*"}):
            with self.assertRaises(ValueError):
                check_environment(ENVIRONMENT, dict(POLICIES, branch_policies=[policy]), TAG)

    def test_admin_bypass_must_be_explicitly_disabled(self):
        for value in (True, None, 0, "false"):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "administrator bypass"):
                check_environment(dict(ENVIRONMENT, can_admins_bypass=value), POLICIES, TAG)
        missing = dict(ENVIRONMENT)
        del missing["can_admins_bypass"]
        with self.assertRaisesRegex(ValueError, "administrator bypass"):
            check_environment(missing, POLICIES, TAG)

    def test_invalid_phase_rejected_before_io(self):
        for phase, draft in (("unknown", "false"), ("draft", "false"), ("attest", "invalid")):
            with self.subTest(phase=phase, draft=draft), \
                    patch.dict("os.environ", {"CREATE_DRAFT": draft}, clear=True), \
                    patch("attested_release_gate.api") as api, \
                    patch("attested_release_gate.Path") as path, \
                    patch("attested_release_gate.subprocess.check_output") as command:
                with self.assertRaises(ValueError):
                    gate(phase)
                api.assert_not_called()
                path.assert_not_called()
                command.assert_not_called()

    def test_approval(self):
        review = {"state": "approved", "user": {"id": 2}, "environments": [{"id": 99}]}
        check_approval([review], ENVIRONMENT, "1")
        for reviews in ([], [dict(review, user={"id": 1})], [dict(review, state="rejected")],
                        [dict(review, environments=[{"id": 98}])]):
            with self.assertRaises(ValueError):
                check_approval(reviews, ENVIRONMENT, "1")


if __name__ == "__main__":
    unittest.main()
