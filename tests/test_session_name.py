import pytest

from tmuxctl import parse_role_session, role_session_name, valid_name


@pytest.mark.parametrize("args, name", [
    (("mw", "impl", "impl", "skeleton"), "mw-impl-impl-skeleton"),
    (("mw", "design", "feature_design", 1), "mw-design-feature_design-1"),
    (("mw", "quality", "reviewer", None), "mw-quality-reviewer"),
])
def test_round_trip(args, name):
    assert role_session_name(*args) == name
    meta = parse_role_session(name)
    assert (meta["division"], meta["dept"], meta["role"]) == args[:3]
    assert meta["suffix"] == (str(args[3]) if args[3] is not None else None)
    assert valid_name(name)


@pytest.mark.parametrize("name", ["mw.impl.skeleton", "mw-impl", "Mw-impl-impl", "my session", "dev_monitor", "mw-impl-impl-a-b"])
def test_not_role_session(name):
    assert parse_role_session(name) is None


@pytest.mark.parametrize("args", [("mw", "impl", "Impl"), ("mw", "im-pl", "impl"), ("", "impl", "impl"), ("mw", "impl", "impl", "a.b")])
def test_invalid_parts(args):
    with pytest.raises(ValueError):
        role_session_name(*args)
