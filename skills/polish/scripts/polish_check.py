#!/usr/bin/env python3
"""polish_check.py — polish 첨삭 앞뒤의 기계 점검. LLM을 부르지 않는다.

사용:
  python3 -I polish_check.py pre FILE [--fix OUT]
    첨삭 전. 연결어미 뒤 쉼표와 "A가 아니라 B" 대조를 센다.
    --fix OUT: 연결어미 뒤 쉼표를 걷은 판을 OUT에 쓴다. FILE은 고치지 않는다.
  python3 -I polish_check.py post BEFORE AFTER [--apply]
    반영 후. 바뀐 문장 비율, 서법(당위·추측) 소실, 새로 생긴 연결어미 쉼표를 본다.
    --apply: 새로 생긴 연결어미 쉼표를 걷어 AFTER에 쓴다.

종료 코드: 0 진행, 1 확인 필요(서법 소실, 바뀐 문장이 절반 초과), 2 실행 오류.
코드 블록과 인라인 코드, 따옴표 안은 세지도 고치지도 않는다.
"""
from __future__ import annotations

import argparse
import difflib
import re
import sys

TOUCH_STOP = 0.5
FENCE = re.compile(r"^\s*(```|~~~)")
# 연결어미 바로 뒤의 쉼표. 뒤에 공백이 와야 한다(숫자·목록 쉼표 제외).
CONN_COMMA = re.compile(r"(고|며|지만|면서|는데|은데|아서|어서|여서|해서|져서|으며|으면서),(?=\s)")
QUOTED = re.compile(r"\"[^\"\n]*\"|“[^”\n]*”|‘[^’\n]*’|「[^」\n]*」|『[^』\n]*』|`[^`\n]*`")
SENT_END = re.compile(r"(?<=[.!?…])\s+|\n+")
ANTITHESIS = re.compile(r"(?:이|가|것이|게|은|는)?\s?아니라|인가,\s?[^.?!\n]{1,40}인가")
DEONTIC = re.compile(r"(?:해|하여|되어|돼|어|아)야\s?(?:한다|합니다|했다|할|하며|하고|만)|할\s?필요가\s?있|하지\s?말아야|반드시")
HEDGE = re.compile(r"[ㄹ을]?\s?수\s?(?:도\s?)?있(?:다|습니다|을|는)|(?:것|듯)으로\s?보인|로\s?보인|가능성이\s?있|추정|짐작|아마|일\s?것이다|ㄹ\s?것이다|듯하다|듯합니다")


def blocks(text: str):
    """코드 블록 밖(True)과 안(False)을 순서대로 낸다."""
    buf, prose = [], True
    for line in text.splitlines(keepends=True):
        if FENCE.match(line):
            if prose:
                if buf:
                    yield True, "".join(buf)
                buf, prose = [line], False
            else:
                buf.append(line)
                yield False, "".join(buf)
                buf, prose = [], True
            continue
        buf.append(line)
    if buf:
        yield prose, "".join(buf)


def prose(text: str) -> str:
    return "".join(c for p, c in blocks(text) if p)


def sentences(text: str) -> list[str]:
    out = []
    for s in SENT_END.split(prose(text)):
        s = re.sub(r"^[#>*\-\d.\s|]+", "", s).strip()
        if s:
            out.append(s)
    return out


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def strip_commas(chunk: str) -> tuple[str, int]:
    """따옴표·인라인 코드 밖의 연결어미 쉼표를 걷는다."""
    spans = [m.span() for m in QUOTED.finditer(chunk)]
    out, last, n = [], 0, 0
    for m in CONN_COMMA.finditer(chunk):
        if any(a <= m.start() < b for a, b in spans):
            continue
        out.append(chunk[last:m.end() - 1])
        last = m.end()
        n += 1
    out.append(chunk[last:])
    return "".join(out), n


def map_prose(text: str, fn) -> tuple[str, int]:
    parts, total = [], 0
    for is_prose, chunk in blocks(text):
        if is_prose:
            chunk, n = fn(chunk)
            total += n
        parts.append(chunk)
    return "".join(parts), total


def short(s: str, n: int = 50) -> str:
    s = norm(s)
    return s if len(s) <= n else s[:n] + "…"


def cmd_pre(a) -> int:
    text = open(a.file, encoding="utf-8").read()
    hits = [s for s in sentences(text) if strip_commas(s)[1]]
    n_comma = sum(strip_commas(s)[1] for s in hits)
    anti = len(ANTITHESIS.findall(prose(text)))
    print("[기계 점검: 첨삭 전]")
    print(f"연결어미 뒤 쉼표: {n_comma}곳({len(hits)}문장)")
    for s in hits[:12]:
        print(f'  - "{short(s)}"')
    if len(hits) > 12:
        print(f"  - 외 {len(hits) - 12}문장")
    print(f'"A가 아니라 B" 대조: {anti}회' + (" — 두 번 이상이면 하나만 남긴다" if anti >= 2 else ""))
    if a.fix:
        fixed, removed = map_prose(text, strip_commas)
        with open(a.fix, "w", encoding="utf-8") as f:
            f.write(fixed)
        print(f"쉼표 정리: {removed}곳을 걷은 판을 {a.fix}에 썼다")
    return 0


def best_match(s: str, pool: list[str]) -> tuple[str, float]:
    best, score = "", 0.0
    for t in pool:
        r = difflib.SequenceMatcher(None, s, t).ratio()
        if r > score:
            best, score = t, r
    return best, score


def cmd_post(a) -> int:
    before = open(a.before, encoding="utf-8").read()
    after = open(a.after, encoding="utf-8").read()
    bs, as_ = sentences(before), sentences(after)
    a_set = {norm(s) for s in as_}
    touched = [s for s in bs if norm(s) not in a_set]
    rate = len(touched) / len(bs) if bs else 0.0

    losses = []
    for s in touched:
        for kind, rx in (("당위", DEONTIC), ("추측", HEDGE)):
            if rx.search(s):
                m, score = best_match(s, as_)
                if score >= 0.5 and not rx.search(m):
                    losses.append((kind, s, m))
                break
    d0, h0 = len(DEONTIC.findall(prose(before))), len(HEDGE.findall(prose(before)))
    d1, h1 = len(DEONTIC.findall(prose(after))), len(HEDGE.findall(prose(after)))

    b_set = {norm(s) for s in bs}

    def strip_new(chunk: str) -> tuple[str, int]:
        pieces = re.split(r"((?<=[.!?…])\s+|\n+)", chunk)
        out, n = [], 0
        for p in pieces:
            key = norm(re.sub(r"^[#>*\-\d.\s|]+", "", p))
            if key and key not in b_set:
                p, k = strip_commas(p)
                n += k
            out.append(p)
        return "".join(out), n

    fixed, new_commas = map_prose(after, strip_new)

    print("[기계 점검: 반영 후]")
    print(f"바뀐 문장: {len(touched)}/{len(bs)}({rate:.0%})" + (" — 절반을 넘었다. 반영을 멈추고 사용자에게 보인다" if rate > TOUCH_STOP else ""))
    print(f"서법 소실: {len(losses)}문장(당위 {d0}→{d1}, 추측 {h0}→{h1})")
    for kind, s, m in losses[:8]:
        print(f'  - [{kind}] "{short(s)}" → "{short(m)}"')
    print(f"새로 생긴 연결어미 쉼표: {new_commas}곳")
    if a.apply and new_commas:
        with open(a.after, "w", encoding="utf-8") as f:
            f.write(fixed)
        print(f"적용: 쉼표 {new_commas}곳을 걷어 {a.after}에 썼다")
    need = []
    if losses:
        need.append("서법이 사라진 문장을 원문의 서법으로 다시 고친다")
    if rate > TOUCH_STOP:
        need.append("바뀐 문장이 절반을 넘었다")
    print("판정: " + ("확인 필요 — " + "; ".join(need) if need else "진행"))
    return 1 if need else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="polish 첨삭 앞뒤의 기계 점검")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("pre")
    p.add_argument("file")
    p.add_argument("--fix", metavar="OUT")
    q = sub.add_parser("post")
    q.add_argument("before")
    q.add_argument("after")
    q.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)
    try:
        return cmd_pre(a) if a.cmd == "pre" else cmd_post(a)
    except Exception as exc:  # noqa: BLE001
        print(f"[기계 점검] 실행 오류: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
