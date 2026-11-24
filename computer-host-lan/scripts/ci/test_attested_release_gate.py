import copy
import unittest

from attested_release_gate import (
    REPO, REPO_ID, check_approval, check_environment, check_jobs, check_ref,
    release_identity, select_run,
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
ENVIRONMENT = {"id": 99, "protection_rules": [{"type": "required_reviewers",
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

    def test_approval(self):
        review = {"state": "approved", "user": {"id": 2}, "environments": [{"id": 99}]}
        check_approval([review], ENVIRONMENT, "1")
        for reviews in ([], [dict(review, user={"id": 1})], [dict(review, state="rejected")],
                        [dict(review, environments=[{"id": 98}])]):
            with self.assertRaises(ValueError):
                check_approval(reviews, ENVIRONMENT, "1")


if __name__ == "__main__":
    unittest.main()
