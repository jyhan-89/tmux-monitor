import pytest

import sessions_meta
import store


ALL = lambda parsed: True


@pytest.fixture(autouse=True)
def config_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "CONFIG_DIR", tmp_path)


def test_adopt_role_sessions():
    assert sessions_meta.adopt(["mw-impl-impl-skeleton", "dev_monitor", "mw-quality-reviewer"], ALL)
    meta = sessions_meta.get("mw-impl-impl-skeleton")
    assert meta == {"division": "mw", "dept": "impl", "role": "impl", "grouped": True}
    assert sessions_meta.get("dev_monitor") is None
    assert store.group_of()["mw-impl-impl-skeleton"] == "mw/impl"
    assert store.group_of()["mw-quality-reviewer"] == "mw/quality"
    assert "mw" in store.groups()
    assert not sessions_meta.adopt(["mw-impl-impl-skeleton"], ALL)


def test_adopt_keeps_user_group():
    store.create_group("내 그룹")
    store.move_session("mw-impl-impl-proxy", "내 그룹")
    sessions_meta.adopt(["mw-impl-impl-proxy"], ALL)
    assert store.group_of()["mw-impl-impl-proxy"] == "내 그룹"


def test_adopt_once_respects_later_moves():
    sessions_meta.adopt(["mw-verify-sil"], ALL)
    store.move_session("mw-verify-sil", None)
    sessions_meta.adopt(["mw-verify-sil"], ALL)
    assert "mw-verify-sil" not in store.group_of()


def test_update_rename_forget():
    sessions_meta.update("mw-impl-impl-skeleton", branch="feat/a/skeleton", node="implement")
    with pytest.raises(KeyError):
        sessions_meta.update("x", color="red")
    sessions_meta.rename("mw-impl-impl-skeleton", "mw-impl-impl-1")
    assert sessions_meta.get("mw-impl-impl-1")["branch"] == "feat/a/skeleton"
    assert sessions_meta.get("mw-impl-impl-skeleton") is None
    sessions_meta.forget("mw-impl-impl-1")
    assert sessions_meta.all_meta() == {}


def test_missing_file_is_empty():
    assert sessions_meta.all_meta() == {}


def test_adopt_groups_launcher_sessions_with_meta():
    sessions_meta.update("mw-impl-impl-skeleton", division="mw", dept="impl", role="impl", worktree="/wt")
    assert sessions_meta.adopt(["mw-impl-impl-skeleton"], ALL)
    assert store.group_of()["mw-impl-impl-skeleton"] == "mw/impl"
    assert sessions_meta.get("mw-impl-impl-skeleton")["worktree"] == "/wt"


def test_unknown_names_are_not_adopted():
    assert not sessions_meta.adopt(["classic-autosar-main"])
    assert sessions_meta.get("classic-autosar-main") is None
    assert "classic-autosar-main" not in store.group_of()


def test_role_known_uses_org(tmp_path):
    import shutil
    from pathlib import Path
    import company_api
    import tokens
    sample = Path(__file__).resolve().parent.parent / "company" / "examples" / "mw-minimal"
    tokens.company_dir().mkdir(parents=True)
    assert not company_api.role_known({"division": "mw", "dept": "impl", "role": "impl"})
    shutil.copy(sample / "org.yaml", tokens.company_dir() / "org.yaml")
    assert company_api.role_known({"division": "mw", "dept": "impl", "role": "impl"})
    assert company_api.role_known({"division": "mw", "dept": "shared", "role": "analysis"})
    assert not company_api.role_known({"division": "mw", "dept": "impl", "role": "reviewer"})
    assert not company_api.role_known({"division": "classic", "dept": "autosar", "role": "main"})
