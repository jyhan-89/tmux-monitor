기능 `{feature}`의 구현을 검토한다.

1. 이전 단계 산출물의 각 브랜치를 `git diff main..<브랜치>`와 `git log`로 읽는다.
2. `coord/review/{feature}.md`를 쓴다. 첫 줄은 `APPROVED` 또는 `CHANGES_REQUESTED` 한 단어. 그 아래에 지적 사항(파일:줄, 문제, 근거).
3. 리뷰 파일을 커밋하고 `directive done <이 지시서 id> --ref <브랜치>@<커밋>`으로 끝낸다.
