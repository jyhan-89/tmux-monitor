import logging
import os
import subprocess
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import models
import tokens

log = logging.getLogger("tmux-web")
router = APIRouter(prefix="/api/company")
KINDS = tuple(models.PARSERS)


def kind_path(kind: str) -> Path:
    return tokens.company_dir() / f"{kind}.yaml"


def check_kind(kind: str) -> None:
    if kind not in KINDS:
        raise HTTPException(404, f"정의 종류는 {', '.join(KINDS)} 중 하나입니다")


def read_texts() -> dict[str, str]:
    return {k: kind_path(k).read_text() for k in KINDS if kind_path(k).exists()}


def validate(texts: dict[str, str]) -> None:
    if all(k in texts for k in KINDS):
        models.parse_texts(texts)
        return
    issues = []
    for k, text in texts.items():
        try:
            models.PARSERS[k](text)
        except models.DefinitionError as e:
            issues += e.issues
    if issues:
        raise models.DefinitionError(issues)


def git_commit(kind: str) -> None:
    folder = tokens.company_dir()
    try:
        if not (folder / ".git").exists():
            subprocess.run(["git", "init", "-q"], cwd=folder, check=True, capture_output=True)
            (folder / ".gitignore").write_text("secrets/\n")
            subprocess.run(["git", "add", ".gitignore"], cwd=folder, check=True, capture_output=True)
        subprocess.run(["git", "add", f"{kind}.yaml"], cwd=folder, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-q", "-m", f"{kind}.yaml 수정"], cwd=folder, check=True, capture_output=True)
    except (OSError, subprocess.CalledProcessError) as e:
        log.warning("company git commit 실패: %s", getattr(e, "stderr", e))


@router.get("")
def summary(_: dict = Depends(tokens.require("company.read"))):
    texts = read_texts()
    try:
        validate(texts)
        issues = []
    except models.DefinitionError as e:
        issues = [i.as_dict() for i in e.issues]
    return {"exists": {k: k in texts for k in KINDS}, "complete": len(texts) == len(KINDS), "issues": issues}


@router.get("/{kind}")
def get_kind(kind: str, _: dict = Depends(tokens.require("company.read"))):
    check_kind(kind)
    p = kind_path(kind)
    return {"kind": kind, "exists": p.exists(), "text": p.read_text() if p.exists() else ""}


class Definition(BaseModel):
    text: str


@router.put("/{kind}")
def put_kind(kind: str, body: Definition, _: dict = Depends(tokens.require("company.write"))):
    check_kind(kind)
    texts = {**read_texts(), kind: body.text}
    try:
        validate(texts)
    except models.DefinitionError as e:
        raise HTTPException(400, {"message": "정의 검증에 실패했습니다", "issues": [i.as_dict() for i in e.issues]})
    folder = tokens.company_dir()
    folder.mkdir(parents=True, exist_ok=True)
    tmp = kind_path(kind).with_suffix(".yaml.tmp")
    tmp.write_text(body.text)
    os.replace(tmp, kind_path(kind))
    git_commit(kind)
    return {"ok": True}
