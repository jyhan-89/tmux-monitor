기능 `{feature}`의 구현을 `coord/standards.md` 기준으로 검사한다.

1. 이전 단계 산출물의 구현 브랜치를 읽는다.
2. `coord/standards-check/impl-{feature}.md`를 쓴다. 첫 줄은 `PASS` 또는 `FAIL`, 그 아래에 위반 목록(규칙 ID, 위치, 설명).
3. 커밋하고 `directive done <이 지시서 id> --ref <브랜치>@<커밋>`으로 끝낸다.
