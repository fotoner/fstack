#!/usr/bin/env python3
"""check_fstack.py — fstack 저장소 자체 검사(형식·참조·하드코딩·크기 예산·목록 일치·설치본 일치).

규칙이 문장으로만 있으면 어긋나도 아무것도 멈추지 않는다. 스킬·CORE를 고친 뒤 이 검사를 돌린다.
사용: python3 -I tools/check_fstack.py [--root <fstack 경로>] [--installed]
  --installed  각 하네스에 설치된 CORE 관리 블록이 지금 CORE.md(+ local/core.md)와 같은지도 본다.
공개 검사: `local/`은 공개하지 않는 개인 폴더다. `local/private-terms.txt`의 용어(대소문자 무시)나 홈 디렉터리 절대 경로가
`local/` 밖 파일에 나오면 오류다. 목록이 없으면(새로 받은 사본) 공개 검사를 건너뛰고 경고만 낸다.
이 검사는 용어와 홈 경로만 찾는다. 개인 수치·사례·일화는 잡지 못하니 공개 저장소에 푸시하기 전에 사람이 diff를 읽는다.
종료 코드: 0 통과, 1 오류 있음. 경고는 종료 코드에 영향을 주지 않는다.
"""
import argparse, re, sys
from pathlib import Path

# 크기 예산(바이트). 늘리려면 이 값을 고치고 이유를 커밋 메시지에 적는다.
BUDGET = {"CORE.md": 9000, "description_each": 700, "description_total": 6000, "skill_each": 12000}
MODEL_ID = re.compile(r"\b(gpt-\d[\w.-]*|claude-(?:opus|sonnet|haiku|fable)-\d[\w.-]*|gemini-\d[\w.-]*)\b")
RULE_ID = re.compile(r"\b([CH]\d{1,2})\b")
FSTACK_REF = re.compile(r"`~/dev/fstack/([^`\s]+?)`")
LOCAL_REF = re.compile(r"`((?:templates|references)/[^`\s]+?)`")
BARE_REF = re.compile(r"`((?:skills|shared|docs|tools)/[^`\s]+?)`")
MARK_BEGIN = "<!-- fstack:begin"
BEGIN = "<!-- fstack:begin (install.sh가 관리한다. 직접 고치지 말고 ~/dev/fstack/CORE.md를 고친 뒤 install.sh --apply) -->"
END = "<!-- fstack:end -->"
OLD_TAG = re.compile(r"\[[^\]\n]*열람[^\]\n]*\]")
HOME_PATH = re.compile(r"/(?:home|Users)/[A-Za-z0-9_.-]+")
SKIP_DIRS = {"local", ".git", "__pycache__"}
LOCAL_FILES = {"routing.md", "core.md", "lessons.md", "private-terms.txt", "retire.txt", "설계-근거.md", "extract_turns.py"}


def strip_frontmatter(text):
    """개인 폴더 문서는 노트 저장소 형식(YAML frontmatter)일 수 있다. 블록에는 본문만 싣는다."""
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end >= 0:
            return text[end + 5:].lstrip("\n")
    return text


def compose_block(core, local):
    """install.sh와 같은 방식으로 관리 블록을 만든다(끝 줄바꿈 제외)."""
    body = core + ("\n" + local if local else "")
    return f"{BEGIN}\n{body}{END}"


def public_files(root):
    for p in sorted(root.rglob("*")):
        if p.is_file() and not (set(p.relative_to(root).parts) & SKIP_DIRS):
            yield p


def frontmatter(text):
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---", 4)
    if end < 0:
        return None
    fm, key, buf = {}, None, []
    for line in text[4:end].splitlines():
        m = re.match(r"^([a-z_-]+):\s*(.*)$", line)
        if m:
            if key:
                fm[key] = " ".join(buf).strip()
            key, buf = m.group(1), [m.group(2).strip(">- ")]
        elif key:
            buf.append(line.strip())
    if key:
        fm[key] = " ".join(buf).strip()
    return fm


def expected_targets(include_default):
    """install.sh와 같은 규칙으로 CORE 블록이 있어야 할 파일 목록을 만든다."""
    home = Path.home()
    cands, others = [], False
    for d in sorted(home.glob(".claude-*")):
        if d.is_dir():
            cands.append(d / "CLAUDE.md")
            others = True
    if (home / ".claude").is_dir() and (include_default or not others):
        cands.append(home / ".claude" / "CLAUDE.md")
    for f in (home / ".codex/AGENTS.md", home / ".pi/agent/AGENTS.md"):
        if f.parent.is_dir():
            cands.append(f)
    seen, out = set(), []
    for p in cands:
        r = p.resolve() if p.exists() else p
        if r not in seen:
            seen.add(r)
            out.append(r)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(Path(__file__).resolve().parent.parent))
    ap.add_argument("--installed", action="store_true")
    ap.add_argument("--include-default", action="store_true", help="--installed에서 ~/.claude/CLAUDE.md도 대상으로 본다")
    a = ap.parse_args()
    root = Path(a.root)
    errors, warns = [], []
    core = (root / "CORE.md").read_text()
    local_dir = root / "local"
    core_local = strip_frontmatter((local_dir / "core.md").read_text()) if (local_dir / "core.md").exists() else ""
    if local_dir.is_dir() and not (local_dir / "routing.md").exists():
        errors.append("local/은 있는데 local/routing.md가 없다. ROUTING.example.md를 복사해 채운다")
    if not local_dir.is_dir():
        warns.append("local/이 없다. 개인 폴더를 만들어 연결하고 ROUTING.example.md를 local/routing.md로 복사해 채운다(README 설치 절)")
    core_ids = set(re.findall(r"\*\*([CH]\d{1,2})\b", core))
    skills = sorted(p.parent.name for p in (root / "skills").glob("*/SKILL.md"))

    # 1. 스킬 형식과 크기
    desc_total = 0
    for name in skills:
        path = root / "skills" / name / "SKILL.md"
        text = path.read_text()
        fm = frontmatter(text)
        if not fm:
            errors.append(f"{path}: frontmatter가 없다")
            continue
        if fm.get("name") != name:
            errors.append(f"{path}: name '{fm.get('name')}'이 폴더 이름 '{name}'과 다르다")
        desc = fm.get("description", "")
        if not desc:
            errors.append(f"{path}: description이 비었다")
        if len(desc.encode()) > BUDGET["description_each"]:
            warns.append(f"{path}: description {len(desc.encode())}B > {BUDGET['description_each']}B")
        desc_total += len(desc.encode())
        if len(text.encode()) > BUDGET["skill_each"]:
            warns.append(f"{path}: 본문 {len(text.encode())}B > {BUDGET['skill_each']}B")

    # 2~4. 규칙 ID, 경로, 모델 ID (references/는 옮겨 온 원문이라 제외)
    loaded = [p for p in (root / "CORE.md", local_dir / "core.md", local_dir / "routing.md") if p.exists()]
    loaded += list((root / "shared").glob("*.md"))
    loaded += [p for p in (root / "skills").rglob("*.md") if "references" not in p.parts]
    for ref_doc in sorted((root / "skills").glob("*/references/*.md")):
        if OLD_TAG.search(ref_doc.read_text()):
            errors.append(f"{ref_doc.relative_to(root)}: 옛 태그 열람이 남았다(출처 태그는 [요약])")
    extra = [root / "README.md", root / "ROUTING.example.md", root / "docs" / "design.md", local_dir / "lessons.md", local_dir / "설계-근거.md"]
    for path in loaded + [p for p in extra if p.exists()]:
        text = path.read_text()
        rel = path.relative_to(root)
        if path.name != "CORE.md":
            for rid in sorted(set(RULE_ID.findall(text)) - core_ids):
                if path.name in ("design.md", "설계-근거.md"):
                    continue  # 설계 문서는 옮긴 번호의 이력을 말할 수 있다
                errors.append(f"{rel}: CORE에 없는 규칙 ID {rid}")
        for ref in FSTACK_REF.findall(text):
            ref = ref.rstrip(".,)")
            if "<" not in ref and "*" not in ref and not (root / ref).exists():
                if ref.startswith("local/"):
                    # routing.md는 위에서 한 번 검사한다. 선택 파일·처음 쓸 때 만드는 파일은 없어도 된다.
                    # 개인 폴더가 있는데 알려진 이름이 아니면 오타로 본다.
                    if not local_dir.is_dir() or ref[len("local/"):] in LOCAL_FILES:
                        continue
                errors.append(f"{rel}: 없는 경로 `~/dev/fstack/{ref}`")
        if path in loaded and OLD_TAG.search(text):
            errors.append(f"{rel}: 옛 태그 [열람]이 남았다(완료 등급은 [코드], 출처 태그는 [요약])")
        if path in loaded:
            for ref in LOCAL_REF.findall(text):
                ref = ref.rstrip(".,)")
                if "<" in ref or "*" in ref:
                    continue
                base = path.parent.parent if path.parent.name == "templates" else path.parent
                if not (base / ref).exists():
                    errors.append(f"{rel}: 스킬 폴더 기준으로 없는 경로 `{ref}`")
            for ref in BARE_REF.findall(text):
                ref = ref.rstrip(".,)")
                if "<" in ref or "*" in ref or not (root / ref).exists():
                    continue  # 대상 저장소 기준 경로(예: 작업 저장소의 docs/)는 그대로 둔다
                errors.append(f"{rel}: 다른 하네스·저장소에서 열리지 않는 상대 경로 `{ref}` (`~/dev/fstack/{ref}`로 쓴다)")
            if path.name not in ("routing.md", "ROUTING.example.md") and "templates" not in path.parts:
                for mid in sorted(set(MODEL_ID.findall(text))):
                    errors.append(f"{rel}: 모델 ID 하드코딩 {mid} (routing.md 역할 이름을 쓴다)")

    # 5. 목록 일치: CORE 스킬 지도, README 표, install.sh
    m = re.search(r"## 스킬 지도\n(.*)", core, re.S)
    core_map = set(re.findall(r"^- ([a-z-]+):", m.group(1), re.M)) if m else set()
    readme_map = set(re.findall(r"^\| `([a-z-]+)` \|", (root / "README.md").read_text(), re.M))
    m = re.search(r"^SKILLS=\(([^)]*)\)", (root / "install.sh").read_text(), re.M)
    install_map = set(m.group(1).split()) if m else set()
    for label, found in (("CORE 스킬 지도", core_map), ("README 스킬 표", readme_map), ("install.sh SKILLS", install_map)):
        if found != set(skills):
            errors.append(f"{label}가 스킬 폴더와 다르다: 빠짐 {sorted(set(skills) - found)}, 남음 {sorted(found - set(skills))}")

    # 6. 크기 예산(설치 때 함께 실리는 local/core.md 포함)
    core_size = len(core.encode()) + len(core_local.encode())
    if core_size > BUDGET["CORE.md"]:
        errors.append(f"CORE.md + local/core.md {core_size}B > 예산 {BUDGET['CORE.md']}B")

    # 6b. 공개 검사
    terms_file = local_dir / "private-terms.txt"
    if terms_file.exists():
        terms = [l.strip() for l in terms_file.read_text().splitlines() if l.strip() and not l.startswith("#")]
        pat = re.compile("|".join(re.escape(x) for x in terms), re.I) if terms else None
        for p in public_files(root):
            try:
                text = p.read_text()
            except UnicodeDecodeError:
                continue
            for n, line in enumerate(text.splitlines(), 1):
                hits = (set(m.group(0) for m in pat.finditer(line)) if pat else set()) | set(HOME_PATH.findall(line))
                if hits:
                    errors.append(f"공개 파일에 개인 정보: {p.relative_to(root)}:{n} {sorted(hits)}")
    else:
        warns.append("local/private-terms.txt가 없어 공개 검사를 건너뛰었다")
    if desc_total > BUDGET["description_total"]:
        warns.append(f"스킬 description 합계 {desc_total}B > {BUDGET['description_total']}B")

    # 7. 설치본 일치
    if a.installed:
        if not (local_dir / "routing.md").exists():
            errors.append("local/routing.md가 없다. 설치된 CORE와 스킬은 개인 값(역할·호스트·저장소 규칙)을 이 파일에서 읽는다")
        want = compose_block(core, core_local)
        for f in expected_targets(a.include_default):
            if not f.exists():
                errors.append(f"CORE 블록이 있어야 할 파일이 없다: {f} (./install.sh --apply)")
                continue
            text = f.read_text()
            starts = [i for i, line in enumerate(text.splitlines()) if line.startswith(MARK_BEGIN)]
            if not starts:
                errors.append(f"CORE 블록이 없다: {f} (이 하네스는 CORE를 읽지 않는다. ./install.sh --apply)")
                continue
            if len(starts) > 1:
                errors.append(f"CORE 블록이 {len(starts)}개다: {f} (두 번 실린다)")
            ends = [i for i, line in enumerate(text.splitlines()) if line.startswith("<!-- fstack:end")]
            paired = len(ends) == len(starts) and all(s < e for s, e in zip(starts, ends)) \
                and all(e < s for e, s in zip(ends, starts[1:]))
            if not paired:
                errors.append(f"fstack 표지의 순서·짝이 맞지 않는다: {f} (install.sh는 이 파일을 고치지 않는다. 직접 확인)")
            b = text.index(MARK_BEGIN)
            e = text.find(END, b)
            if e < 0:
                errors.append(f"CORE 블록의 끝 표지가 없다: {f}")
                continue
            if text[b:e + len(END)] != want:
                errors.append(f"설치된 CORE 블록이 정본과 다르다: {f} (./install.sh --apply로 갱신)")
            else:
                print(f"설치본 일치: {f}")

    print(f"스킬 {len(skills)}개 · CORE(+local) {core_size}B/{BUDGET['CORE.md']}B · description 합계 {desc_total}B/{BUDGET['description_total']}B")
    for w in warns:
        print("경고:", w)
    for e in errors:
        print("오류:", e)
    print("통과" if not errors else f"오류 {len(errors)}개")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
