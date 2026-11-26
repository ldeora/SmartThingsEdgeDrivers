"""Fail-closed eligibility gate for the explicitly dispatched Linux release."""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO = "ldeora/SmartThingsEdgeDrivers"
REPO_ID = 895807249
PREFIX = "computer-host-lan-v"
WORKFLOWS = {
    "computer-host-linux.yml": {"python-tests": 5, "distro-source-smoke": 6,
                                "Reproducible source archives and checksums": 1},
    "computer-host-windows.yml": {"windows-build": 1, "windows-arm64-build": 1},
    "computer-host-inno.yml": {"inno-windows-x64": 1},
    "computer-host-release.yml": {"linux-source": 1, "windows-x64": 1,
                                  "Validate release asset set (no publication)": 1},
    "computer-host-linux-installer.yml": {"wizard-tests": 1},
}
ATTEST = "computer-host-linux-attest"
DRAFT = "computer-host-linux-draft"
RC3_TAG = PREFIX + "1.0.0-rc.3"
RC3_APPROVAL = "rc3-maintainer-only"
MAINTAINER_ID = "176927315"


def require(ok, message):
    if not ok:
        raise ValueError(message)


def release_identity(env, manifest):
    sha = env["GITHUB_SHA"]
    tag = env["EXPECTED_TAG"]
    require(env["GITHUB_REPOSITORY"] == REPO and env["GITHUB_REPOSITORY_ID"] == str(REPO_ID), "wrong repository")
    require(env["GITHUB_EVENT_NAME"] == "workflow_dispatch" and env["GITHUB_RUN_ATTEMPT"] == "1", "explicit first-attempt dispatch required")
    require(re.fullmatch(r"[0-9a-f]{40}", sha) and sha == env["EXPECTED_SHA"], "source commit mismatch")
    version = manifest["integration"]
    require(re.fullmatch(r"1\.0\.0(?:-rc\.(?:[3-9]|[1-9][0-9]+))?", version), "ineligible release version")
    require(tag == PREFIX + version and env["GITHUB_REF"] == "refs/tags/" + tag, "release tag mismatch")
    require(manifest["release_candidate_tag"] == tag and manifest["release_stage"] == "attestation-ready-v" + version, "manifest is not approved for attestation")
    return sha, tag


def check_ref(ref, sha):
    require(ref["object"]["type"] == "commit" and ref["object"]["sha"] == sha, "ref must point directly to approved commit")


def check_jobs(jobs, expected):
    require(jobs["total_count"] == len(jobs["jobs"]) == sum(expected.values()), "incomplete required job set")
    counts = dict.fromkeys(expected, 0)
    seen = set()
    for job in jobs["jobs"]:
        name = job["name"]
        require(name not in seen and job["status"] == "completed" and job["conclusion"] == "success", "job missing success or duplicated")
        seen.add(name)
        keys = [key for key in expected if name == key or (expected[key] > 1 and name.startswith(key + " ("))]
        require(len(keys) == 1, "unexpected job name")
        counts[keys[0]] += 1
    require(counts == expected, "required job counts differ")


def select_run(response, sha):
    runs = response["workflow_runs"]
    require(response["total_count"] == len(runs) and len(runs) > 0, "missing or truncated workflow history")
    eligible = [run for run in runs if run["head_sha"] == sha and run["head_branch"] == "main" and
                run["event"] in ("push", "workflow_dispatch") and run["head_repository"]["id"] == REPO_ID]
    require(eligible, "no exact-commit main workflow run")
    latest = max(eligible, key=lambda run: (run["run_number"], run["run_attempt"]))
    require(latest["status"] == "completed" and latest["conclusion"] == "success", "latest exact-commit workflow not successful")
    return latest


def approval_mode(env, manifest):
    """Explicit, manifest-bound exception for one candidate; never stable."""
    mode = manifest.get("linux_attestation_approval", "independent")
    require(mode in ("independent", RC3_APPROVAL), "unknown approval policy")
    if mode == RC3_APPROVAL:
        require(manifest["integration"] == "1.0.0-rc.3" and
                env["EXPECTED_TAG"] == RC3_TAG, "exception restricted to rc.3")
        require(env["GITHUB_ACTOR_ID"] == MAINTAINER_ID,
                "rc.3 exception requires maintainer dispatch")
        require(env["CREATE_DRAFT"] == "false",
                "rc.3 exception cannot stage a draft")
    return mode


def check_environment(environment, policies, tag, mode="independent"):
    require(mode in ("independent", RC3_APPROVAL), "unknown approval policy")
    require(mode != RC3_APPROVAL or tag == RC3_TAG, "exception restricted to rc.3")
    require(environment.get("can_admins_bypass") is False, "environment must disable administrator bypass")
    rules = [r for r in environment["protection_rules"] if r["type"] == "required_reviewers"]
    if mode == RC3_APPROVAL:
        require(len(rules) == 1 and rules[0]["prevent_self_review"] is False and
                len(rules[0]["reviewers"]) == 1 and rules[0]["reviewers"][0]["type"] == "User" and
                str(rules[0]["reviewers"][0]["reviewer"]["id"]) == MAINTAINER_ID,
                "rc.3 environment must require only the named maintainer")
    else:
        require(len(rules) == 1 and rules[0]["reviewers"] and rules[0]["prevent_self_review"] is True,
                "environment must require independent approval")
    require(environment["deployment_branch_policy"] == {"protected_branches": False, "custom_branch_policies": True}, "environment must restrict deployment refs")
    require(policies["total_count"] == len(policies["branch_policies"]) == 1 and
            policies["branch_policies"][0]["type"] == "tag" and policies["branch_policies"][0]["name"] == tag,
            "environment must allow only the exact approved tag")


def check_approval(reviews, environment, actor_id, mode="independent"):
    require(mode in ("independent", RC3_APPROVAL), "unknown approval policy")
    matches = [r for r in reviews if any(e["id"] == environment["id"] for e in r["environments"])]
    require(matches and all(r["state"] == "approved" for r in matches),
            "environment approval not recorded")
    if mode == RC3_APPROVAL:
        require(actor_id == MAINTAINER_ID and
                all(str(r["user"]["id"]) == MAINTAINER_ID for r in matches),
                "named maintainer approval not recorded")
    else:
        require(any(str(r["user"]["id"]) != actor_id for r in matches),
                "independent environment approval not recorded")


def api(path, paginate=False):
    args = ["gh", "api", "--method", "GET"]
    if paginate:
        args += ["--paginate", "--slurp"]
    return json.loads(subprocess.check_output(args + ["repos/" + REPO + "/" + path], text=True, timeout=120))


def gate(phase):
    env = os.environ
    require(phase in ("eligibility", "attest", "draft"), "invalid phase")
    require(env["CREATE_DRAFT"] in ("true", "false"), "invalid draft selection")
    environments = [ATTEST]
    if env["CREATE_DRAFT"] == "true":
        environments.append(DRAFT)
    require(phase != "draft" or DRAFT in environments, "invalid phase")
    manifest = json.loads(Path("computer-host-lan/release.json").read_text())
    sha, tag = release_identity(env, manifest)
    mode = approval_mode(env, manifest)
    check_ref(api("git/ref/heads/main"), sha)
    check_ref(api("git/ref/tags/" + tag), sha)
    require(subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip() == sha, "checkout mismatch")
    for workflow, expected in WORKFLOWS.items():
        run = select_run(api(f"actions/workflows/{workflow}/runs?branch=main&head_sha={sha}&per_page=100"), sha)
        check_jobs(api(f"actions/runs/{run['id']}/attempts/{run['run_attempt']}/jobs?per_page=100"), expected)
        print(f"Verified {workflow}: run {run['id']} attempt {run['run_attempt']}")
    releases = api("releases?per_page=100", paginate=True)
    # Read-only tokens cannot list drafts. The contents-write draft job
    # repeats this check before creating a release and can see drafts too.
    require(not any(release["tag_name"] == tag for page in releases for release in page), "release already exists; never replace assets")
    for name in environments:
        environment = api("environments/" + name)
        check_environment(environment, api("environments/" + name + "/deployment-branch-policies?per_page=100"), tag, mode)
        if phase == "draft" or (phase == "attest" and name == ATTEST):
            check_approval(api("actions/runs/" + env["GITHUB_RUN_ID"] + "/approvals"), environment, env["GITHUB_ACTOR_ID"], mode)
    print(f"Eligible: {tag} at {sha} ({phase}, {mode})")


if __name__ == "__main__":
    try:
        gate(sys.argv[1])
    except (ValueError, KeyError, IndexError, TypeError, OSError, subprocess.SubprocessError) as exc:
        sys.exit(f"Release gate refused: {exc}")
