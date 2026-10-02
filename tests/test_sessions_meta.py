import pytest

import sessions_meta
import store


@pytest.fixture(autouse=True)
def config_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "CONFIG_DIR", tmp_path)


def test_adopt_role_sessions():
    assert sessions_meta.adopt(["mw-impl-impl-skeleton", "dev_monitor", "mw-quality-reviewer"])
    meta = sessions_meta.get("mw-impl-impl-skeleton")
    assert meta == {"division": "mw", "dept": "impl", "role": "impl", "grouped": True}
    assert sessions_meta.get("dev_monitor") is None
    assert store.group_of()["mw-impl-impl-skeleton"] == "mw/impl"
    assert store.group_of()["mw-quality-reviewer"] == "mw/quality"
    assert "mw" in store.groups()
    assert not sessions_meta.adopt(["mw-impl-impl-skeleton"])


def test_adopt_keeps_user_group():
    store.create_group("내 그룹")
    store.move_session("mw-impl-impl-proxy", "내 그룹")
    sessions_meta.adopt(["mw-impl-impl-proxy"])
    assert store.group_of()["mw-impl-impl-proxy"] == "내 그룹"


def test_adopt_once_respects_later_moves():
    sessions_meta.adopt(["mw-verify-sil"])
    store.move_session("mw-verify-sil", None)
    sessions_meta.adopt(["mw-verify-sil"])
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
    assert sessions_meta.adopt(["mw-impl-impl-skeleton"])
    assert store.group_of()["mw-impl-impl-skeleton"] == "mw/impl"
    assert sessions_meta.get("mw-impl-impl-skeleton")["worktree"] == "/wt"
