결재가 승인되었다. 기능 `{feature}`의 브랜치를 `main`에 머지한다.

1. `git fetch origin` 후 `git merge origin/main`으로 작업 브랜치를 최신 main에 맞춘다.
2. 이전 단계 산출물의 구현 브랜치(`feat/{feature}/…`)를 적힌 순서대로 `git merge --no-ff <브랜치>`한다. 충돌은 해결 범위 안에서만 고친다.
3. 빌드·테스트를 확인한 뒤 `git push origin HEAD:main`으로 main에 반영한다.
4. `directive done <이 지시서 id> --ref main@<커밋>`으로 끝낸다.
