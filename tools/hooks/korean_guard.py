#!/usr/bin/env python3
"""korean_guard.py — Claude Code Stop 훅. C3(한국어)을 기계로 확인한다.

문서 규칙·메모리·압축 요약에 "반드시 한국어"를 적어 둔 뒤에도, 컨텍스트 압축 직후·긴 도구 작업 뒤·영어 알림에 답할 때
최종 보고가 영어로 나갔다. 한 세션에서 교정 직후에도 6번 재발했다. 이 훅은 마지막 응답이 영어 위주면 턴을 끝내지 못하게
막고 한국어로 다시 쓰게 한다.

판정: 코드 블록·인라인 코드·URL·경로·따옴표 안 인용을 뺀 본문에서 단어를 센다. 단어가 MIN_WORDS 이상이고, 한글 단어 비율이
MIN_HANGUL 미만이고, 영어 기능어(the, is, to …) 비율이 MIN_FUNCTION 이상이면 영어 응답으로 본다. 기능어 조건은 영어 용어가 많은
한국어 보고(lint, merge, branch 같은 명사 위주)를 막지 않으려고 둔다.
기준값은 실제 세션의 최종 응답 523개(2026-10-29~11-05, 한 호스트)로 맞췄다. 영어 응답 23개는 한글 비율 최고 0.33·기능어 비율
최저 0.30이었고, 정상 한국어 응답은 한글 비율 최저 0.63이었다. 이 기준으로 영어 23개를 모두 잡고 정상 응답 500개는 막지 않았다.
한계: 마지막 응답만 본다. 도구 호출 사이의 진행 메모가 영어여도 마지막 응답이 한국어면 통과한다.
사용자의 마지막 요청에 "영어로", "in English" 같은 말이 있으면 검사하지 않는다.

입력: 표준 입력의 Stop 훅 JSON(`last_assistant_message`, `stop_hook_active`, `transcript_path`).
막을 때는 이유를 stderr에 쓰고 종료 코드 2를 낸다. `stop_hook_active`가 참이면(이미 한 번 막아 다시 쓰는 중) 통과시켜 반복을 막는다.
설치(전역 설정 변경)는 사용자 승인 뒤에 한다. 설정 조각은 README의 "개인 설정".
"""
import json
import re
import sys

MIN_WORDS = 12
MIN_HANGUL = 0.5
MIN_FUNCTION = 0.15
# 영어 문장에만 나오는 기능어. 한국어 문장에 섞인 영어 용어(lint, merge, branch)는 명사라 여기에 걸리지 않는다.
FUNCTION_WORDS = {
    "the", "a", "an", "and", "or", "but", "is", "are", "was", "were", "be", "been", "i", "i'm", "i've", "you",
    "it", "it's", "its", "this", "that", "these", "those", "to", "of", "in", "on", "for", "with", "as", "at",
    "by", "from", "so", "not", "no", "have", "has", "had", "do", "does", "did", "will", "would", "can", "could",
    "should", "we", "they", "there", "which", "what", "now", "if", "then", "also", "into", "than", "because",
}

FENCE = re.compile(r"(```|~~~)[\s\S]*?(\1|$)")
INLINE = re.compile(r"`[^`\n]*`")
URL = re.compile(r"https?://\S+|\]\([^)]*\)")
PATHISH = re.compile(r"\S*[/\\]\S*|\S+\.[A-Za-z0-9]{1,5}\b")
TAG = re.compile(r"<[^>\n]{1,200}>")
QUOTE = re.compile(r"\"[^\"\n]{1,80}\"|“[^”\n]{1,80}”|'[^'\n]{1,80}'(?![A-Za-z])")
WORD = re.compile(r"[가-힣ㄱ-ㆎ]+|[A-Za-z][A-Za-z'’]+")
ENGLISH_ASK = re.compile(r"영어로|영문으로|영어 ?버전|in english|english (version|please)|translate .{0,20}english|write .{0,20}english", re.I)


def words_of(text):
    """코드·URL·경로·따옴표 안 인용을 뺀 본문의 단어."""
    t = FENCE.sub(" ", text or "")
    t = INLINE.sub(" ", t)
    t = URL.sub(" ", t)
    t = TAG.sub(" ", t)
    t = QUOTE.sub(" ", t)
    t = PATHISH.sub(" ", t)
    return WORD.findall(t)


def hangul_ratio(text):
    """(한글 단어 비율, 센 단어 수)."""
    words = words_of(text)
    if not words:
        return 1.0, 0
    hangul = sum(1 for w in words if "가" <= w[0] <= "힣" or "ㄱ" <= w[0] <= "ㆎ")
    return hangul / len(words), len(words)


def is_english(text):
    """(영어 응답인가, 한글 단어 비율, 센 단어 수). 한글이 적고 영어 기능어가 많아야 영어로 본다."""
    words = words_of(text)
    ratio, n = hangul_ratio(text)
    if n < MIN_WORDS or ratio >= MIN_HANGUL:
        return False, ratio, n
    function = sum(1 for w in words if w.lower().replace("’", "'") in FUNCTION_WORDS)
    return function / n >= MIN_FUNCTION, ratio, n


def last_user_text(transcript_path):
    """대화 기록에서 사람이 쓴 마지막 요청 본문. 못 읽으면 빈 문자열."""
    last = ""
    try:
        with open(transcript_path, encoding="utf-8", errors="ignore") as f:
            for line in f:
                if '"type":"user"' not in line and '"type": "user"' not in line:
                    continue
                try:
                    o = json.loads(line)
                except ValueError:
                    continue
                c = (o.get("message") or {}).get("content")
                if isinstance(c, str):
                    last = c
                elif isinstance(c, list):
                    texts = [x.get("text", "") for x in c if isinstance(x, dict) and x.get("type") == "text"]
                    if texts:
                        last = "\n".join(texts)
    except (OSError, TypeError):
        return ""
    return last


def last_assistant_text(transcript_path):
    """`last_assistant_message`가 없는 버전용. 마지막 assistant 메시지의 본문."""
    last = ""
    try:
        with open(transcript_path, encoding="utf-8", errors="ignore") as f:
            for line in f:
                if '"assistant"' not in line:
                    continue
                try:
                    o = json.loads(line)
                except ValueError:
                    continue
                if o.get("type") != "assistant":
                    continue
                c = (o.get("message") or {}).get("content") or []
                texts = [x.get("text", "") for x in c if isinstance(x, dict) and x.get("type") == "text"]
                if texts:
                    last = "\n".join(texts)
    except (OSError, TypeError):
        return ""
    return last


def main():
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return 0
    if data.get("stop_hook_active"):
        return 0
    path = data.get("transcript_path") or ""
    text = data.get("last_assistant_message")
    if text is None and path:
        text = last_assistant_text(path)
    english, ratio, n = is_english(text or "")
    if not english:
        return 0
    if path and ENGLISH_ASK.search(last_user_text(path)[:2000]):
        return 0
    sys.stderr.write(
        f"fstack C3(한국어): 마지막 응답이 영어 위주다(한글 단어 {ratio:.0%}, {n}단어). "
        "같은 내용을 한국어로 다시 써서 사용자에게 보여라. 코드·명령·식별자·인용은 원문 그대로 둔다. "
        "사과나 이 안내에 대한 언급 없이 본문만 다시 쓴다.\n"
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
