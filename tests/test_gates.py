import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
                          check=True, capture_output=True, text=True).stdout


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "r"
    git(tmp_path, "init", "-q", "-b", "main", str(r))
    git(r, "commit", "-q", "--allow-empty", "-m", "init")
    git(r, "checkout", "-q", "-b", "feat/a/impl")
    return r


def put(repo, rel, text="x"):
    f = repo / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(text)
    git(repo, "add", rel)
    git(repo, "commit", "-q", "-m", rel)


def gate(name, repo, feature="a", **env):
    r = subprocess.run([str(ROOT / "gates" / name), str(repo), feature, str(repo.parent / "out")],
                       capture_output=True, text=True, env={**os.environ, **env})
    return r.returncode, r.stdout + r.stderr


def test_ownership(repo):
    env = {"GATE_ROLE": "impl", "GATE_CAN_EDIT": "src/** test/**", "GATE_DENY": "gen/** **/*.arxml coord/spec.md"}
    put(repo, "src/a/b.cpp")
    put(repo, "test/t.cpp")
    assert gate("common/ownership_check.sh", repo, **env)[0] == 0
    put(repo, "src/model.arxml")
    rc, out = gate("common/ownership_check.sh", repo, **env)
    assert rc == 1 and "수정 금지 경로: src/model.arxml" in out
    git(repo, "reset", "-q", "--hard", "HEAD~1")
    put(repo, "README.md")
    rc, out = gate("common/ownership_check.sh", repo, **env)
    assert rc == 1 and "범위 밖: README.md" in out


def test_ownership_ignores_merged_commits(repo):
    git(repo, "checkout", "-q", "-b", "feat/a/design", "main")
    put(repo, "coord/design/a.md")
    git(repo, "checkout", "-q", "feat/a/impl")
    git(repo, "merge", "-q", "--no-edit", "--no-ff", "feat/a/design")
    put(repo, "src/x.cpp")
    assert gate("common/ownership_check.sh", repo, GATE_CAN_EDIT="src/**")[0] == 0


def test_review_and_std_and_sil(repo):
    assert gate("common/review_approved.sh", repo)[0] == 1
    (repo / "coord/review").mkdir(parents=True)
    (repo / "coord/review/a.md").write_text("CHANGES_REQUESTED\nfix it\n")
    rc, out = gate("common/review_approved.sh", repo)
    assert rc == 1 and "fix it" in out
    (repo / "coord/review/a.md").write_text("APPROVED  \n")
    assert gate("common/review_approved.sh", repo)[0] == 0
    (repo / "coord/standards-check").mkdir(parents=True)
    (repo / "coord/standards-check/impl-a.md").write_text("PASS\n")
    assert gate("adaptive/impl_std_check.sh", repo)[0] == 0
    (repo / "reports/sil1").mkdir(parents=True)
    (repo / "reports/sil1/a.md").write_text("결과: FAIL\n")
    assert gate("adaptive/sil_feature.sh", repo)[0] == 1
    (repo / "reports/sil1/a.md").write_text("결과: PASS\n")
    assert gate("adaptive/sil_feature.sh", repo)[0] == 0
    assert gate("adaptive/sil_feature.sh", repo, SIL_RUNNER="false")[0] == 1


def test_unit_test_and_design(repo):
    assert gate("adaptive/unit_test.sh", repo)[0] == 1
    put(repo, "src/a.cpp")
    rc, out = gate("adaptive/unit_test.sh", repo)
    assert rc == 0 and "TEST_CMD 미설정" in out
    assert gate("adaptive/unit_test.sh", repo, TEST_CMD="false")[0] == 1
    assert gate("adaptive/design_check.sh", repo)[0] == 1
    put(repo, "coord/design/a.md")
    assert gate("adaptive/design_check.sh", repo)[0] == 0


def test_main_build_ok(repo, tmp_path):
    put(repo, "src/a.cpp")
    rc, out = gate("common/main_build_ok.sh", repo)
    assert rc == 1 and "머지되지 않은 브랜치: feat/a/impl" in out
    git(repo, "checkout", "-q", "-b", "feat/a/integrator", "main")
    git(repo, "merge", "-q", "--no-edit", "feat/a/impl")
    git(repo, "branch", "-f", "main", "HEAD")
    rc, out = gate("common/main_build_ok.sh", repo, TEST_CMD="test -f src/a.cpp")
    assert rc == 0, out
    assert gate("common/main_build_ok.sh", repo, TEST_CMD="false")[0] == 1
    assert "main" not in git(repo, "worktree", "list").split("\n", 1)[1] if "\n" in git(repo, "worktree", "list").strip() else True
