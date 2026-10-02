기능 `{feature}`의 `{layer}` 계층을 구현한다.

1. 이전 단계 산출물의 설계서(`coord/design/{feature}.md`)가 있으면 `git show <브랜치>:coord/design/{feature}.md`로 읽는다. 없으면 아래 요청을 기준으로 한다.
2. 수정 가능 범위 안에서 구현하고 테스트를 작성·실행한다.
3. 작업 브랜치에 커밋한 뒤 `directive done <이 지시서 id> --ref <브랜치>@<커밋>`으로 끝낸다.
4. "이전 시도 결과"가 있으면 그 실패 원인부터 해결한다.
