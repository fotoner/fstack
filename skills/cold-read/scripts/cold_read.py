#!/usr/bin/env python3
"""cold_read.py — cold-read의 기계 부분. LLM을 부르지 않는다.

사용:
  python3 -I cold_read.py brief read DOC
    자유 읽기 지시서에 문서 전문을 넣어 출력한다. 출력을 그대로 독자에게 보낸다.
  python3 -I cold_read.py brief answer DOC --questions FILE
    답안 시험 지시서에 질문과 문서 전문을 넣어 출력한다. FILE에는 질문만 둔다(답안은 따로 둔다).
  python3 -I cold_read.py scan DOC
    대화의 흔적, 외부 참조, 약어, 모호 신호를 줄 번호와 함께 뽑는다. 판정에만 쓰고 독자에게 보내지 않는다.
  python3 -I cold_read.py grow BEFORE AFTER
    글자 수(공백 제외) 변화를 보고한다. 20%를 넘으면 종료 코드 1.

지시서를 스크립트가 만드는 이유: 오케스트레이터가 독자 프롬프트를 손으로 쓰면 맥락을 덧붙이게 된다.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TEMPLATES = HERE.parent / "templates"
GROW_STOP = 0.20

FENCE = re.compile(r"^\s*(```|~~~)")
INLINE_CODE = re.compile(r"`[^`\n]*`")

CHECKS = [
    ("대화의 흔적", [
        ("대화에서 붙인 안 이름", re.compile(r"(?<![0-9A-Za-z가-힣])(?:[0-9]+|[A-Z])안(?![전내녕경과건정심목쪽팎방])")),
        ("번호로 부른 항목", re.compile(r"(?<![0-9A-Za-z])[A-Z]{1,2}[0-9]{1,2}(?![0-9A-Za-z])")),
        ("N번", re.compile(r"(?<![0-9])[0-9]{1,2}번(?!째|지|길)")),
        ("절·장 번호", re.compile(r"[0-9]+(?:\.[0-9]+)+\s*[절장]?|[0-9]+\s*[절장](?![가-힣])")),
        ("앞선 대화를 가리키는 말", re.compile(r"앞서|위에서|지난번|아까|앞에서 (?:정한|말한)|말씀하신|말한 대로|논의한 대로|이전에 정한")),
    ]),
    ("외부 참조", [
        ("링크", re.compile(r"https?://[^\s)>\]]+")),
        ("이슈·PR 번호", re.compile(r"(?<![\w/&])#[0-9]+")),
    ]),
    ("약어", [
        ("영문 약어", re.compile(r"(?<![A-Za-z])[A-Z]{2,}[A-Z0-9]*(?![a-z])")),
    ]),
    ("모호 신호", [
        ("가리키는 대상이 흐린 말", re.compile(r"해당|관련된?|이것|그것|이는|이를")),
        ("기준 없는 꾸밈말", re.compile(r"적절히|적당히|필요 ?시|필요하면|가능하면|가급적|충분히|빠르게|일부|여러")),
        ("상대 날짜", re.compile(r"추후|향후|조만간|곧|다음 ?주|이번 ?주|지난 ?주|내일|어제|오늘|이번 달|다음 달|[월화수목금토일]요일")),
    ]),
]


def prose_lines(text: str):
    """코드 블록 밖의 줄을 (줄 번호, 인라인 코드를 뺀 줄)로 낸다."""
    in_fence = False
    for no, line in enumerate(text.splitlines(), 1):
        if FENCE.match(line):
            in_fence = not in_fence
            continue
        if not in_fence:
            yield no, INLINE_CODE.sub(" ", line)


def template_block(name: str) -> str:
    text = (TEMPLATES / name).read_text(encoding="utf-8")
    m = re.search(r"```text\n(.*?)\n```", text, re.S)
    if not m:
        raise SystemExit(f"{name}: ```text 블록이 없다")
    return m.group(1)


def cmd_brief(a) -> int:
    doc = Path(a.doc).read_text(encoding="utf-8").strip()
    if a.kind == "read":
        out = template_block("reader-brief.md").replace("{DOC}", doc)
    else:
        if not a.questions:
            raise SystemExit("answer에는 --questions가 필요하다")
        qs = [q.strip() for q in Path(a.questions).read_text(encoding="utf-8").splitlines() if q.strip()]
        qs = [re.sub(r"^(?:Q?\d+[.)]\s*|[-*]\s*)", "", q) for q in qs]
        numbered = "\n".join(f"질문 {i}. {q}" for i, q in enumerate(qs, 1))
        out = template_block("answer-test.md").replace("{QUESTIONS}", numbered).replace("{DOC}", doc)
    sys.stdout.write(out + "\n")
    return 0


def cmd_scan(a) -> int:
    text = Path(a.doc).read_text(encoding="utf-8")
    lines = list(prose_lines(text))
    print("[cold-read 훑기] 판정에만 쓰고 독자에게 보내지 않는다")
    total = 0
    for group, rules in CHECKS:
        found = []
        for label, rx in rules:
            hits: dict[str, list[int]] = {}
            for no, line in lines:
                for m in rx.finditer(line):
                    hits.setdefault(m.group(0).strip(), []).append(no)
            for word, nos in hits.items():
                found.append((label, word, nos))
        print(f"\n## {group}: {len(found)}종")
        for label, word, nos in found[:40]:
            where = ", ".join(map(str, nos[:6])) + (" …" if len(nos) > 6 else "")
            print(f"- [{label}] {word} — {len(nos)}회, 줄 {where}")
        if len(found) > 40:
            print(f"- 외 {len(found) - 40}종")
        total += len(found)
    print(f"\n합계 {total}종. 신호일 뿐이다. 실제 독자가 아는 말과 문서 안에서 풀린 말은 판정에서 뺀다.")
    return 0


def size(path: str) -> int:
    return len(re.sub(r"\s+", "", Path(path).read_text(encoding="utf-8")))


def cmd_grow(a) -> int:
    b, c = size(a.before), size(a.after)
    rate = (c - b) / b if b else 0.0
    print(f"글자 수(공백 제외): {b} → {c} ({rate:+.0%})")
    if rate > GROW_STOP:
        print("20%를 넘게 늘었다. 반영을 멈추고 사용자에게 보인다")
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="cold-read의 기계 부분")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("brief")
    b.add_argument("kind", choices=["read", "answer"])
    b.add_argument("doc")
    b.add_argument("--questions")
    s = sub.add_parser("scan")
    s.add_argument("doc")
    g = sub.add_parser("grow")
    g.add_argument("before")
    g.add_argument("after")
    a = ap.parse_args(argv)
    return {"brief": cmd_brief, "scan": cmd_scan, "grow": cmd_grow}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
