# fstack

Fotone의 Claude Code, Codex, Pi용 에이전트 스킬. [T3 Code](https://github.com/pingdotgg/t3code) 위에서 쓰는 것을 기준으로 하고, T3 Code가 없으면 하네스 기본 도구로 대신한다.

## 스킬

| 스킬 | 하는 일 |
|---|---|
| `full-send` | 증명 → 리뷰 → QA → PR → 감시 → 머지까지 무인으로 진행 |
| `full-stop` | `full-send`와 같고 머지 직전에서 멈춤 |
| `sol-loop` | GPT Sol과 합의할 때까지 diff 리뷰 반복 |
| `council` | 회사가 다른 모델 3개로 합의할 때까지 검토 |
| `ship` | 말한 단계까지만 커밋·푸시·PR·머지 |
| `build` | 재현 후 최소 수정, 이슈별 worktree, 웨이브 구현 |
| `verify` | 조회·재현으로 완료 판정, 실제 환경 QA, 배포 단계 판정 |
| `research` | 결론과 근거, 갈래별 병렬 조사 |
| `walk` | 사람이 정할 것만 한 건씩, 아침 킥오프 |
| `wrap` | 마무리 점검, 인계, 이어받기 |
| `ops` | 읽기 전용 운영 점검, 예약 작업 |
| `setup` | 설치·장애 대응 |
| `harness` | 저장소 지침 정리, 반복 문제를 검사로 |
| `lesson` | 교정을 훅·검사·스킬·규칙에 반영 |

`full-send`는 `sol-loop`, `verify`, `ship`을 쓰고, `full-stop`은 `full-send`를 쓴다. 모든 세션에 [CORE.md](CORE.md)가 함께 실린다.

## T3 Code

| 도구 | 쓰는 곳 | 없을 때 |
|---|---|---|
| `delegate_task` | `council`, `sol-loop`, 하위 에이전트 위임 | 하네스의 하위 에이전트. 다른 회사 모델을 못 부르면 리뷰 미실행으로 보고 |
| `orchestrator_capabilities` | `council`, `sol-loop` | 하네스의 모델 목록 |
| `watch_pull_request`, `unwatch_pull_request` | `full-send`, `full-stop`, `ship` | `gh pr checks --watch`(검사만 기다린다) |
| `link_pull_request` | `ship` | 생략 |
| `schedule_task` | `ops` | 하네스의 예약 기능 |
| `request_secret` | CORE C19 | 파일로 받는다 |

## 설치

```bash
git clone https://github.com/fotoner/fstack ~/dev/fstack
cp ~/dev/fstack/ROUTING.example.md <개인 폴더>/routing.md   # 채운다
ln -s <개인 폴더> ~/dev/fstack/local
cd ~/dev/fstack
./install.sh           # 점검만
./install.sh --apply
```

`~/dev/fstack`에 둔다. 옵션은 `./install.sh --help`.

## 필요한 것

- 인증된 [GitHub CLI](https://cli.github.com)(`gh`), `python3`
- `council`, `sol-loop`: 다른 회사 모델을 하위 에이전트로 부를 수 있는 하네스(T3 Code면 `delegate_task`)

## 개인 설정

모델·계정·호스트·저장소별 규칙은 `local/routing.md`, 개인 어휘는 `local/core.md`. `local/`은 커밋되지 않는다.

스킬을 고친 뒤: `python3 -I tools/check_fstack.py`

훅(선택, Claude Code `settings.json`):

```json
{"hooks": {"PreToolUse": [{"matcher": "Bash|Agent|Task|mcp__t3-code__delegate_task",
  "hooks": [{"type": "command", "command": "python3 -I ~/dev/fstack/tools/hooks/fstack_guard.py"}]}]}}
```

## 라이선스

[MIT](LICENSE)
