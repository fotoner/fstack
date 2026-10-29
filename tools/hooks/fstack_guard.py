#!/usr/bin/env python3
"""fstack_guard.py — Claude Code PreToolUse 훅. 문장으로는 막지 못했던 두 가지를 기계로 막는다.

1. H1: 이름·패턴·포트로 프로세스를 죽이는 명령(`pkill`, `killall`, `fuser -k`, `kill`과 `pgrep`·`pidof`·`lsof -t`를 함께 쓰는 명령).
   한 저장소에서 다른 작업자의 검사와 사용자의 앱이 이렇게 종료됐다. 내가 띄운 PID는 `kill <PID>`로 끈다.
   사용자가 그 작업에서 명시적으로 허락했으면 명령 끝에 `# fstack:allow-kill`을 붙인다.
2. C17: 모델 인자 없이 하위 에이전트를 띄우는 호출(Claude `Agent`/`Task`, T3 `delegate_task`).
   "지시 없으면 소넷" 규칙을 문서로 둔 뒤에도 다른 프로젝트에서 14번 상속(Opus)으로 띄웠다.
   `subagent_type: "fork"`는 부모 모델을 그대로 쓰는 것이 정의라서 검사하지 않는다.

H1 검사 방식(r3): 명령 위치를 추적하지 않는다. 실행되는 텍스트(따옴표 밖, `$(…)`·백틱 안, 따옴표 없는 heredoc의
치환, `bash -c`·`ssh`·`eval`에 넘긴 문자열)를 단어로 나누고, 그 안에 `pkill`·`killall`이 어느 위치에든 있으면 막는다.
실행되지 않는 텍스트(주석, 따옴표 친 heredoc 본문, 일반 따옴표 문자열)와, 접두 명령(`sudo`·`env`·`timeout` 등과 옵션 값)을 벗긴
머리 명령이 데이터만 다루는 명령(`grep`, `find`(`-exec` 없이), `git`, `cat`, `echo`, `command -v` 등)인 명령 단위는 보지 않는다.
접두를 잘못 벗기면 머리 명령을 못 알아봐 막는 쪽으로 기운다(오판의 대가는 누락이 아니라 오탐이다).
한계: 변수·별칭·함수로 이름을 감춘 경우, 스크립트 파일 안의 kill, 다른 언어(`python -c` 등)가 부르는 kill은 잡지 못한다.
이 훅은 실수를 줄이는 장치이고 보안 경계가 아니다. 규칙은 CORE H1이다.

입력: 표준 입력의 훅 JSON(`tool_name`, `tool_input`). 막을 때는 이유를 stderr에 쓰고 종료 코드 2를 낸다.
설치(전역 설정 변경)는 사용자 승인 뒤에 한다. 설정 조각은 README의 "내 것으로 만들기".
"""
import json
import os
import re
import sys

ALLOW_KILL = "# fstack:allow-kill"
KILLERS = {"pkill", "killall"}
PID_LOOKUPS = {"pgrep", "pidof"}
RESERVED = {"if", "then", "else", "elif", "fi", "do", "done", "while", "until", "!", "{", "}", "time"}
DATA_HEADS = {"grep", "egrep", "fgrep", "rg", "ag", "ack", "man", "which", "whereis", "type", "whatis",
              "apropos", "tldr", "info", "echo", "printf", "find", "fd", "ls", "cat", "bat", "head",
              "tail", "less", "more", "wc", "diff", "jq", "tree", "file", "stat", "du", "sort", "uniq", "cut",
              "strings", "sed"}
FIND_EXEC = {"-exec", "-execdir", "-ok", "-okdir"}
FD_EXEC = {"-x", "-X", "--exec", "--exec-batch"}
EXEC_FLAGS = FD_EXEC | FIND_EXEC
# 데이터만 다루는 git 하위 명령. bisect·submodule·rebase 등 명령을 실행하는 하위 명령과 -c(별칭·설정)는 검사한다
GIT_DATA_SUBS = {"status", "log", "show", "diff", "grep", "blame", "commit", "add", "branch", "checkout", "switch",
                 "restore", "fetch", "pull", "push", "stash", "tag", "remote", "rev-parse", "rev-list", "ls-files",
                 "ls-tree", "merge-base", "describe", "shortlog", "reflog", "worktree", "clone", "init", "mv", "rm",
                 "reset", "cherry-pick", "merge", "cat-file", "notes", "format-patch", "apply", "am", "archive"}
# 접두 명령과, 값을 하나 받는 옵션(값까지 건너뛴다)
WRAPPERS = {"sudo": {"-u", "-g", "-C", "-D", "-h", "-p", "-r", "-t", "-U"}, "doas": {"-u", "-C"},
            "env": {"-u", "-C", "-S"}, "nohup": set(), "time": {"-f", "-o"}, "timeout": {"-s", "-k"},
            "nice": {"-n"}, "ionice": {"-c", "-n"}, "stdbuf": {"-i", "-o", "-e"}, "exec": {"-a"},
            "command": set(), "caffeinate": set()}
DURATION = re.compile(r"^\d+(\.\d+)?[smhd]?$")
RUNNERS = {"bash", "sh", "zsh", "dash", "ksh", "fish", "eval", "ssh", "su", "watch"}
ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
AGENT_TOOLS = {"Agent", "Task"}


def deny(reason):
    sys.stderr.write(f"[fstack_guard] {reason}\n")
    sys.exit(2)


class Lexer:
    """셸 명령을 '명령 단위 단어 목록'으로 나눈다. 치환(`$(…)`, 백틱)은 별도 명령 단위로 더한다.
    따옴표는 벗기고, 주석과 따옴표 친 heredoc 본문은 버린다. 짝이 맞지 않으면 ValueError."""

    def __init__(self):
        self.out = []

    def lex(self, s, i=0, stop=False):
        n = len(s)
        seg, word = [], []
        started = False
        heredocs = []
        depth = 0

        def end_word():
            nonlocal word, started
            if started:
                seg.append("".join(word))
            word, started = [], False

        def end_seg():
            nonlocal seg
            end_word()
            if seg:
                self.out.append(seg)
            seg = []

        while i < n:
            c = s[i]
            if c in " \t":
                end_word()
                i += 1
            elif c == "\n":
                end_seg()
                i = self.skip_heredocs(s, i + 1, heredocs)
                heredocs = []
            elif c == "#" and not started:
                k = s.find("\n", i)
                i = n if k < 0 else k
            elif c in ";&|":
                end_seg()
                i += 1
            elif c == "(":
                depth += 1
                end_seg()
                i += 1
            elif c == ")":
                end_seg()
                if stop and depth == 0:
                    return i
                depth -= 1
                i += 1
            elif s.startswith("<<", i) and not s.startswith("<<<", i):
                end_word()
                i = self.read_heredoc_mark(s, i + 2, heredocs)
            elif c in "<>":
                end_word()
                i += 1
            elif c == "'":
                k = s.find("'", i + 1)
                if k < 0:
                    raise ValueError("작은따옴표 짝")
                word.append(s[i + 1:k])
                started = True
                i = k + 1
            elif c == '"':
                i = self.double_quoted(s, i + 1, word)
                started = True
            elif c == "\\":
                if s[i + 1:i + 2] != "\n":
                    word.append(s[i + 1:i + 2])
                    started = True
                i += 2
            elif c == "`":
                i = self.backtick(s, i + 1)
                started = True
            elif s.startswith("$((", i):
                i = self.skip_parens(s, i + 1)
                started = True
            elif s.startswith("$(", i):
                i = self.lex(s, i + 2, stop=True) + 1
                started = True
            elif s.startswith("$'", i):
                k = i + 2
                while k < n and s[k] != "'":
                    k += 2 if s[k] == "\\" else 1
                if k >= n:
                    raise ValueError("$' 짝")
                word.append(s[i + 2:k])
                started = True
                i = k + 1
            elif s.startswith("${", i):
                k = s.find("}", i)
                if k < 0:
                    raise ValueError("${ 짝")
                word.append(s[i:k + 1])
                started = True
                i = k + 1
            else:
                word.append(c)
                started = True
                i += 1
        if stop:
            raise ValueError("$( 짝")
        end_seg()
        return i

    def double_quoted(self, s, i, word):
        n = len(s)
        while i < n and s[i] != '"':
            if s[i] == "\\":
                word.append(s[i + 1:i + 2])
                i += 2
            elif s.startswith("$((", i):
                i = self.skip_parens(s, i + 1)
            elif s.startswith("$(", i):
                i = self.lex(s, i + 2, stop=True) + 1
            elif s[i] == "`":
                i = self.backtick(s, i + 1)
            else:
                word.append(s[i])
                i += 1
        if i >= n:
            raise ValueError("큰따옴표 짝")
        return i + 1

    def backtick(self, s, i):
        k = i
        while k < len(s) and s[k] != "`":
            k += 2 if s[k] == "\\" else 1
        if k >= len(s):
            raise ValueError("백틱 짝")
        Lexer.into(self.out, s[i:k])
        return k + 1

    @staticmethod
    def skip_parens(s, i):
        depth = 0
        while i < len(s):
            depth += {"(": 1, ")": -1}.get(s[i], 0)
            i += 1
            if depth == 0:
                return i
        raise ValueError("$(( 짝")

    @staticmethod
    def read_heredoc_mark(s, i, heredocs):
        n = len(s)
        strip = s[i:i + 1] == "-"
        i += strip
        while i < n and s[i] in " \t":
            i += 1
        delim, quoted = [], False
        while i < n and s[i] not in " \t\n;&|()<>":
            if s[i] in "'\"":
                k = s.find(s[i], i + 1)
                if k < 0:
                    raise ValueError("heredoc 구분자 짝")
                delim.append(s[i + 1:k])
                quoted, i = True, k + 1
            elif s[i] == "\\":
                delim.append(s[i + 1:i + 2])
                quoted, i = True, i + 2
            else:
                delim.append(s[i])
                i += 1
        heredocs.append(("".join(delim), quoted, strip))
        return i

    def skip_heredocs(self, s, pos, heredocs):
        """본문을 건너뛴다. 따옴표 없는 구분자면 본문 속 치환은 실행되므로 검사한다."""
        n = len(s)
        for delim, quoted, strip in heredocs:
            while pos < n:
                k = s.find("\n", pos)
                end = n if k < 0 else k
                line = s[pos:end]
                pos = n if k < 0 else k + 1
                if (line.lstrip("\t") if strip else line) == delim:
                    break
                if not quoted:
                    self.expansions(line)
        return pos

    def expansions(self, s):
        i = 0
        while i < len(s):
            if s[i] == "\\":
                i += 2
            elif s.startswith("$((", i):
                i = self.skip_parens(s, i + 1)
            elif s.startswith("$(", i):
                i = self.lex(s, i + 2, stop=True) + 1
            elif s[i] == "`":
                i = self.backtick(s, i + 1)
            else:
                i += 1

    @staticmethod
    def into(out, s):
        lx = Lexer()
        lx.lex(s)
        out.extend(lx.out)


def is_name(word, names):
    if word in names:
        return True
    return word.startswith(("/", "./", "../", "~/")) and os.path.basename(word) in names


def head(seg):
    """예약어·변수 할당·접두 명령(옵션과 그 값, timeout의 시간)을 건너뛴 머리 명령과 나머지 단어."""
    i, wrapper = 0, None
    while i < len(seg):
        w = seg[i]
        base = os.path.basename(w)
        if w in RESERVED or ASSIGN.match(w):
            i += 1
        elif base in WRAPPERS and not (base == "command" and seg[i + 1:i + 2] in (["-v"], ["-V"])):
            wrapper, i = base, i + 1
        elif wrapper and w.startswith("-"):
            i += 2 if w in WRAPPERS[wrapper] else 1
        elif wrapper == "timeout" and DURATION.match(w):
            i, wrapper = i + 1, None
        else:
            return base, seg[i + 1:]
    return "", []


def git_sub(rest):
    """git 전역 옵션을 건너뛴 하위 명령. -c·--exec-path가 있으면 빈 값(검사 대상)."""
    i = 0
    while i < len(rest):
        w = rest[i]
        if w == "-c" or w.startswith(("--exec-path", "--config-env")) or (w.startswith("-c") and len(w) > 2):
            return ""
        if w in ("-C", "--git-dir", "--work-tree", "--namespace"):
            i += 2
        elif w.startswith("-"):
            i += 1
        else:
            return w
    return ""


def is_data_head(word, rest):
    if word == "find":
        return not (FIND_EXEC & set(rest))
    if word == "fd":
        return not (FD_EXEC & set(rest)) and not any(w.startswith(("--exec=", "--exec-batch=")) for w in rest)
    if word == "git":
        return git_sub(rest) in GIT_DATA_SUBS
    return word in DATA_HEADS or (word == "command" and rest[:1] in (["-v"], ["-V"]))


def flags_after(seg, names):
    """seg에서 names 명령 뒤에 오는 옵션만 모은다(앞의 sudo -k 같은 옵션을 섞지 않는다)."""
    for i, w in enumerate(seg):
        if is_name(w, names):
            return [f for f in seg[i + 1:] if f.startswith("-")]
    return []


def facts(cmd, level=0):
    """(이름으로 죽이는 단어, kill 단어, PID 조회 단어)가 실행되는 텍스트에 있는지."""
    lx = Lexer()
    lx.lex(cmd)
    killer = kill = lookup = False
    for seg in lx.out:
        word, rest = head(seg)
        if is_data_head(word, rest):
            continue
        fuser = flags_after(seg, {"fuser"})
        lsof = flags_after(seg, {"lsof"})
        killer |= any(is_name(w, KILLERS) for w in seg)
        killer |= "--kill" in fuser or any(re.match(r"^-[A-Za-z]*k", f) for f in fuser)
        kill |= any(is_name(w, {"kill"}) for w in seg)
        lookup |= any(is_name(w, PID_LOOKUPS) for w in seg)
        lookup |= any(re.match(r"^-[A-Za-z]*t", f) for f in lsof)
        code = []
        if any(os.path.basename(w) in RUNNERS for w in seg):
            code += [w for w in seg if re.search(r"[\s;&|]", w)]
        for i, w in enumerate(seg):
            if w in EXEC_FLAGS and i + 1 < len(seg):
                code.append(seg[i + 1])          # git rebase --exec "…", fd -x … 의 문자열
            elif w.startswith("--exec="):
                code.append(w.split("=", 1)[1])
            elif "=!" in w:
                code.append(w.split("=!", 1)[1])  # git -c alias.x='!…'
        if level < 3:
            for w in code:
                a, b, c = facts(w, level + 1)
                killer, kill, lookup = killer or a, kill or b, lookup or c
    return killer, kill, lookup


def kills_by_name(cmd):
    try:
        killer, kill, lookup = facts(cmd)
    except (ValueError, RecursionError):
        # 셸도 실행하지 못하는 명령이다. 단어만 거칠게 보고 의심스러우면 막는다.
        return bool(re.search(r"(^|[^\w-])(pkill|killall)([^\w-]|$)", cmd))
    return killer or (kill and lookup)


def main():
    try:
        event = json.load(sys.stdin)
    except ValueError:
        return 0  # 형식이 다르면 막지 않는다(훅 오류로 작업을 멈추지 않는다)
    tool = event.get("tool_name") or ""
    args = event.get("tool_input") or {}

    if tool == "Bash":
        cmd = args.get("command") or ""
        if ALLOW_KILL not in cmd and kills_by_name(cmd):
            deny("이름·패턴으로 프로세스를 죽이는 명령은 막혀 있다(fstack H1). 내가 띄운 PID를 확인해 `kill <PID>`로 끈다. "
                 "사용자가 이 작업에서 명시적으로 허락했다면 명령 끝에 `# fstack:allow-kill`을 붙인다.")
    elif tool in AGENT_TOOLS:
        if args.get("subagent_type") != "fork" and not (args.get("model") or "").strip():
            deny("하위 에이전트의 `model` 인자가 없다(fstack C17). ~/dev/fstack/local/routing.md 역할표대로 적는다(지시가 없으면 reader·worker = sonnet).")
    elif tool.endswith("delegate_task"):
        target = args.get("target") or {}
        if not (target.get("model") or "").strip():
            deny("`delegate_task`의 `target.model`이 없다(fstack C17). ~/dev/fstack/local/routing.md 역할표대로 모델과 effort(`target.options`)를 적는다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
