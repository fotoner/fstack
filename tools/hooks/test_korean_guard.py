#!/usr/bin/env python3
"""korean_guard.py 시험. 막아야 할 것과 통과해야 할 것(대조군)을 함께 본다.
사용: python3 -I tools/hooks/test_korean_guard.py
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

GUARD = Path(__file__).resolve().parent / "korean_guard.py"

EN_REPORT = ("I ran all 8 QA scenarios in the local environment, and all of them pass. No defects found. "
             "One suspected issue turned out to be expected behavior, so I left it as is.")
KO_REPORT = ("로컬 환경에서 QA 시나리오 8개를 모두 돌렸고 모두 통과했습니다 [합성]. 결함은 없었습니다. "
             "의심했던 한 건은 정상 동작이라 그대로 두었습니다.")
KO_WITH_CODE = ("`ship` 6단계를 고쳤습니다. 검사는 통과했습니다.\n\n```bash\npython3 -I tools/check_fstack.py\n"
                "All checks passed. Skills: 14, CORE size within budget, descriptions within budget.\n```\n"
                "변경 파일은 `skills/ship/SKILL.md`, `skills/council/SKILL.md`, `CORE.md`입니다.")
KO_MANY_TERMS = ("PR #12의 CI가 main 기준 lint, typecheck, unit test, e2e smoke 단계에서 모두 통과했습니다. "
                 "release branch에 cherry-pick할지는 정하지 않았습니다. dev에는 merge하지 않았습니다.")
EN_WITH_KO_QUOTES = ('I removed the "가져오기 기록" item from the document. Section 9 now has three items: '
                     '"설정 화면", "알림 목록", and "내보내기".')


def transcript(lines):
    f = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, encoding="utf-8")
    for role, text in lines:
        f.write(json.dumps({"type": role, "message": {"role": role, "content": [{"type": "text", "text": text}]}},
                           ensure_ascii=False) + "\n")
    f.close()
    return f.name


CASES = [
    # (설명, 훅 입력, 막혀야 하나)
    ("영어 보고", {"hook_event_name": "Stop", "stop_hook_active": False, "last_assistant_message": EN_REPORT}, True),
    ("따옴표 속 한국어만 있는 영어 보고",
     {"hook_event_name": "Stop", "stop_hook_active": False, "last_assistant_message": EN_WITH_KO_QUOTES}, True),
    ("한국어 보고", {"hook_event_name": "Stop", "stop_hook_active": False, "last_assistant_message": KO_REPORT}, False),
    ("코드 블록이 영어인 한국어 보고",
     {"hook_event_name": "Stop", "stop_hook_active": False, "last_assistant_message": KO_WITH_CODE}, False),
    ("영어 용어가 많은 한국어 보고",
     {"hook_event_name": "Stop", "stop_hook_active": False, "last_assistant_message": KO_MANY_TERMS}, False),
    ("짧은 영어", {"hook_event_name": "Stop", "stop_hook_active": False, "last_assistant_message": "Done."}, False),
    ("코드만", {"hook_event_name": "Stop", "stop_hook_active": False,
              "last_assistant_message": "```python\nprint('hello world from the english code block here')\n```"}, False),
    ("다시 쓰는 중이면 통과", {"hook_event_name": "Stop", "stop_hook_active": True, "last_assistant_message": EN_REPORT}, False),
    ("사용자가 영어를 요청", {"hook_event_name": "Stop", "stop_hook_active": False, "last_assistant_message": EN_REPORT,
                       "transcript_path": transcript([("user", "이 공지 영어로 써줘"), ("assistant", EN_REPORT)])}, False),
    ("요청 없이 영어", {"hook_event_name": "Stop", "stop_hook_active": False, "last_assistant_message": EN_REPORT,
                    "transcript_path": transcript([("user", "QA 진행해줘"), ("assistant", EN_REPORT)])}, True),
    ("본문 필드 없음, 기록에서 읽음", {"hook_event_name": "Stop", "stop_hook_active": False,
                             "transcript_path": transcript([("user", "QA 진행해줘"), ("assistant", EN_REPORT)])}, True),
    ("본문 필드 없음, 한국어 기록", {"hook_event_name": "Stop", "stop_hook_active": False,
                            "transcript_path": transcript([("user", "QA 진행해줘"), ("assistant", KO_REPORT)])}, False),
    ("깨진 입력", None, False),
]


def run(event):
    data = "not json" if event is None else json.dumps(event, ensure_ascii=False)
    p = subprocess.run([sys.executable, "-I", str(GUARD)], input=data, capture_output=True, text=True)
    return p.returncode, p.stderr


def main():
    fails = 0
    for name, event, should_block in CASES:
        code, err = run(event)
        blocked = code == 2
        ok = blocked == should_block and (blocked or code == 0)
        fails += not ok
        print(f"{'통과' if ok else '실패'}: {name} (종료 코드 {code})")
    print(f"{len(CASES) - fails}/{len(CASES)} 통과")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
