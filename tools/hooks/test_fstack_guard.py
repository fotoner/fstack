#!/usr/bin/env python3
"""fstack_guard.py 시험. 막아야 할 것과 통과해야 할 것(대조군)을 함께 본다.
사용: python3 -I tools/hooks/test_fstack_guard.py
"""
import json
import subprocess
import sys
from pathlib import Path

GUARD = Path(__file__).resolve().parent / "fstack_guard.py"

CASES = [
    # (설명, 훅 입력, 막혀야 하나)
    ("pkill -f", {"tool_name": "Bash", "tool_input": {"command": "pkill -f check.sh"}}, True),
    ("pkill 이름", {"tool_name": "Bash", "tool_input": {"command": "pkill MyApp"}}, True),
    ("killall", {"tool_name": "Bash", "tool_input": {"command": "killall Music"}}, True),
    ("연결 뒤 pkill", {"tool_name": "Bash", "tool_input": {"command": "cd /tmp && pkill -9 node"}}, True),
    ("kill $(pgrep)", {"tool_name": "Bash", "tool_input": {"command": "kill $(pgrep -f vite)"}}, True),
    ("pgrep | xargs kill", {"tool_name": "Bash", "tool_input": {"command": "pgrep -f metro | xargs -r kill"}}, True),
    ("허락 표시", {"tool_name": "Bash", "tool_input": {"command": "pkill -f old-server # fstack:allow-kill"}}, False),
    ("PID kill", {"tool_name": "Bash", "tool_input": {"command": "kill 48211"}}, False),
    ("pgrep 조회만", {"tool_name": "Bash", "tool_input": {"command": "pgrep -fl t3"}}, False),
    ("문자열 속 단어", {"tool_name": "Bash", "tool_input": {"command": "grep -n 'skillall' notes.md"}}, False),
    ("일반 명령", {"tool_name": "Bash", "tool_input": {"command": "git status --short"}}, False),
    ("Agent 모델 없음", {"tool_name": "Agent", "tool_input": {"prompt": "조사", "subagent_type": "general-purpose"}}, True),
    ("Agent 모델 있음", {"tool_name": "Agent", "tool_input": {"prompt": "조사", "model": "sonnet"}}, False),
    ("Task 모델 빈 값", {"tool_name": "Task", "tool_input": {"prompt": "조사", "model": " "}}, True),
    ("delegate_task 모델 없음", {"tool_name": "mcp__t3-code__delegate_task", "tool_input": {"task": "리뷰", "target": {}}}, True),
    ("delegate_task 모델 있음", {"tool_name": "mcp__t3-code__delegate_task", "tool_input": {"task": "리뷰", "target": {"model": "x"}}}, False),
    ("다른 도구", {"tool_name": "Read", "tool_input": {"file_path": "/tmp/a"}}, False),
    # 컨실 r2(O2-6, S2-3): 검색·메시지는 통과
    ("grep 인자", {"tool_name": "Bash", "tool_input": {"command": "grep -rn pkill CORE.md"}}, False),
    ("rg 따옴표", {"tool_name": "Bash", "tool_input": {"command": "rg -n 'killall|pkill' ."}}, False),
    ("커밋 메시지", {"tool_name": "Bash", "tool_input": {"command": "git commit -m 'H1: pkill 금지'"}}, False),
    ("echo 문자열", {"tool_name": "Bash", "tool_input": {"command": "echo \"use killall\" && ls"}}, False),
    ("절대 경로 pkill", {"tool_name": "Bash", "tool_input": {"command": "/usr/bin/pkill -f vite"}}, True),
    ("sudo killall", {"tool_name": "Bash", "tool_input": {"command": "sudo killall -9 Music"}}, True),
    ("env 접두 pkill", {"tool_name": "Bash", "tool_input": {"command": "env FOO=1 pkill node"}}, True),
    ("백틱 kill", {"tool_name": "Bash", "tool_input": {"command": "kill `pgrep -f vite`"}}, True),
    ("따옴표 속 kill $(pgrep)", {"tool_name": "Bash", "tool_input": {"command": "kill \"$(pgrep -f vite)\""}}, True),
    ("여러 줄 뒤 pkill", {"tool_name": "Bash", "tool_input": {"command": "cd /tmp\npkill -f server"}}, True),
    ("PID 변수 kill", {"tool_name": "Bash", "tool_input": {"command": "kill \"$SERVER_PID\""}}, False),
    # 컨실 r3(O3-9, S3-5~S3-7): 접두 옵션·치환·제어 구문·셸 문자열은 막고, 주석·heredoc 본문·조회는 통과
    ("bash -c 큰따옴표", {"tool_name": "Bash", "tool_input": {"command": "bash -c \"pkill -f foo\""}}, True),
    ("sh -c 작은따옴표", {"tool_name": "Bash", "tool_input": {"command": "sh -c 'killall node'"}}, True),
    ("timeout 인자", {"tool_name": "Bash", "tool_input": {"command": "timeout 5s pkill -f vite"}}, True),
    ("sudo -u 인자", {"tool_name": "Bash", "tool_input": {"command": "sudo -u root pkill -f vite"}}, True),
    ("env -u 인자", {"tool_name": "Bash", "tool_input": {"command": "env -u NODE_ENV pkill -f vite"}}, True),
    ("큰따옴표 속 치환", {"tool_name": "Bash", "tool_input": {"command": "printf \"%s\" \"$(pkill -f vite)\""}}, True),
    ("if then", {"tool_name": "Bash", "tool_input": {"command": "if true; then pkill -f vite; fi"}}, True),
    ("중괄호 묶음", {"tool_name": "Bash", "tool_input": {"command": "{ pkill -f vite; }"}}, True),
    ("ssh 원격 문자열", {"tool_name": "Bash", "tool_input": {"command": "ssh buildhost 'pgrep -f vite | xargs kill'"}}, True),
    ("따옴표 친 명령 이름", {"tool_name": "Bash", "tool_input": {"command": "\"pkill\" -f vite"}}, True),
    ("nohup sh -c", {"tool_name": "Bash", "tool_input": {"command": "nohup sh -c \"sleep 1; killall node\" &"}}, True),
    ("따옴표 없는 heredoc 치환", {"tool_name": "Bash", "tool_input": {"command": "cat <<EOF\n$(pkill -f vite)\nEOF"}}, True),
    ("command -v 조회", {"tool_name": "Bash", "tool_input": {"command": "command -v pkill"}}, False),
    ("주석 속 pkill", {"tool_name": "Bash", "tool_input": {"command": "echo ok # example; pkill -f vite"}}, False),
    ("인용 heredoc 본문", {"tool_name": "Bash", "tool_input": {"command": "cat > notes.md <<'EOF'\npkill -f vite\nkill $(pgrep x)\nEOF\nls"}}, False),
    ("커밋 heredoc", {"tool_name": "Bash", "tool_input": {"command": "git commit -m \"$(cat <<'EOF'\nH1: don't use pkill (ever)\nEOF\n)\""}}, False),
    ("git grep", {"tool_name": "Bash", "tool_input": {"command": "git grep -n pkill"}}, False),
    ("bash -c 조회", {"tool_name": "Bash", "tool_input": {"command": "bash -c \"echo pkill\""}}, False),
    # 컨실 r4(S4-5, O4-6): 데이터 인자·접두 뒤 조회는 통과, 포트로 죽이기는 막음
    ("find 이름 인자", {"tool_name": "Bash", "tool_input": {"command": "find /usr/bin -name pkill"}}, False),
    ("커밋 메시지 한 단어", {"tool_name": "Bash", "tool_input": {"command": "git commit -m 'pkill'"}}, False),
    ("env 접두 grep", {"tool_name": "Bash", "tool_input": {"command": "env LC_ALL=C grep -n pkill CORE.md"}}, False),
    ("sudo 접두 grep", {"tool_name": "Bash", "tool_input": {"command": "sudo grep -rn killall /etc"}}, False),
    ("lsof 조회만", {"tool_name": "Bash", "tool_input": {"command": "lsof -i :3000"}}, False),
    ("find -exec pkill", {"tool_name": "Bash", "tool_input": {"command": "find . -name x -exec pkill -f {} \\;"}}, True),
    ("kill $(lsof -t)", {"tool_name": "Bash", "tool_input": {"command": "kill -9 $(lsof -ti :3000)"}}, True),
    ("lsof | xargs kill", {"tool_name": "Bash", "tool_input": {"command": "lsof -ti :3000 | xargs kill"}}, True),
    ("fuser -k", {"tool_name": "Bash", "tool_input": {"command": "fuser -k 3000/tcp"}}, True),
    ("커밋 메시지 속 치환", {"tool_name": "Bash", "tool_input": {"command": "git commit -m \"$(pkill -f vite)\""}}, True),
    # 컨실 r5(O5-3, D5-3, S5-1): 명령을 실행하는 git 하위 명령·fd 실행 옵션은 검사, fuser·lsof 옵션은 그 명령 뒤에서만
    ("git bisect run", {"tool_name": "Bash", "tool_input": {"command": "git bisect run pkill -f vite"}}, True),
    ("git bisect run sh -c", {"tool_name": "Bash", "tool_input": {"command": "git bisect run sh -c 'pkill -f vite; npm test'"}}, True),
    ("git submodule foreach", {"tool_name": "Bash", "tool_input": {"command": "git submodule foreach pkill node"}}, True),
    ("fd -x", {"tool_name": "Bash", "tool_input": {"command": "fd -x pkill -f vite"}}, True),
    ("fd -X", {"tool_name": "Bash", "tool_input": {"command": "fd -X killall node"}}, True),
    ("fuser --kill", {"tool_name": "Bash", "tool_input": {"command": "sudo fuser --kill 3000/tcp"}}, True),
    ("sudo -k 뒤 fuser 조회", {"tool_name": "Bash", "tool_input": {"command": "sudo -k fuser -v 3001/tcp"}}, False),
    ("git log --grep", {"tool_name": "Bash", "tool_input": {"command": "git log --grep pkill"}}, False),
    ("git -C 뒤 grep", {"tool_name": "Bash", "tool_input": {"command": "git -C /tmp/x grep -n pkill"}}, False),
    ("fd 검색만", {"tool_name": "Bash", "tool_input": {"command": "fd pkill src"}}, False),
    ("git rebase --exec", {"tool_name": "Bash", "tool_input": {"command": "git rebase -i HEAD~3 --exec \"pkill node\""}}, True),
    ("git -c 별칭", {"tool_name": "Bash", "tool_input": {"command": "git -c alias.k='!pkill node' k"}}, True),
    ("git rebase --exec 시험", {"tool_name": "Bash", "tool_input": {"command": "git rebase main --exec \"npm test\""}}, False),
    ("fork는 모델 없음 허용", {"tool_name": "Agent", "tool_input": {"prompt": "x", "subagent_type": "fork"}}, False),
    ("깨진 입력", None, False),
]


def run(event):
    data = "not json" if event is None else json.dumps(event)
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
