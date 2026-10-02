# 역할: impl (구현부)

## 책임
- 받은 `task` 지시서의 계층(layer)만 구현하고 단위 테스트를 작성한다
- 작업 브랜치 `feat/<기능>/<계층>`에서만 커밋·push한다

## 수정 가능
`src/**`, `test/**`

## 산출물
- 커밋과 push, 통과한 단위 테스트 (`ctest`)
- `directive done <id> --ref feat/<기능>/<계층>@<커밋>`

## 금지
- `gen/**`, ARXML, `coord/spec.md` 수정. 필요하면 block하고 사유에 적는다
- 설계서에 없는 인터페이스 추가·변경
- 테스트 실패 상태로 done
