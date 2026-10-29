#!/usr/bin/env bash
# fstack 설치 스크립트. macOS 기본 bash 3.2와 BSD 도구에서도 돌도록 쓴다(빈 배열 펼치기, sed -i 없음).
# - 위치: ~/dev/fstack 에 있어야 한다. CORE와 스킬이 이 절대 경로를 참조한다.
# - 스킬: 있는 하네스의 skills 디렉터리에 폴더 단위 심볼릭 링크를 건다.
# - CORE: 각 하네스의 사용자 지침 파일에 관리 블록(<!-- fstack:begin … <!-- fstack:end -->)으로 복사한다.
#     local/core.md(개인 보충)가 있으면 frontmatter를 떼고 CORE 뒤에 붙인다. local/은 개인 폴더(또는 그 링크)이고 공개하지 않는다.
#     Claude: 계정 설정 폴더(~/.claude-<이름>, CLAUDE_CONFIG_DIR로 쓰는 폴더)의 CLAUDE.md.
#             ~/.claude/CLAUDE.md는 다른 계정 폴더가 있으면 $HOME 아래 세션에서 프로젝트 지침으로 한 번 더 실리므로
#             --include-default 를 줄 때나 다른 계정 폴더가 없을 때만 다룬다. 빠지면 점검 출력에 표시한다.
#     Codex: ~/.codex/AGENTS.md (Pi의 ~/.pi/agent/AGENTS.md가 같은 파일을 가리키면 한 번만).
# - 기본은 점검만 한다. --apply 로 반영한다. 처음 블록을 넣는 파일은 .bak-<날짜>로 백업하고, 기존 파일의 권한을 보존한다.
# - 충돌(fstack 이름의 다른 항목, 또는 대체 대상인 옛 스킬이 남아 있음)이 하나라도 있으면 아무것도 바꾸지 않고 실패한다.
#   --retire 는 대체 대상(local/retire.txt에 한 줄에 하나)을 각 skills 디렉터리의 .retired-fstack-<날짜>/ 로 옮긴다.
#   --keep-legacy 는 이름이 다른 옛 스킬을 그대로 두고 설치한다(두 세트가 함께 켜진다).
# - CORE를 고친 뒤에는 다시 --apply 로 블록을 갱신한다. 확인은 python3 -I tools/check_fstack.py --installed.
# - 전역 지침에 "불확실하면 먼저 묻는다" 같은 규칙이 있으면 CORE C8과 부딪친다. 그 줄을 "묻는 기준은 fstack CORE C8"로 바꾸기를 권한다.
# - Pi는 설정에서 ~/.agents/skills를 제외해 스킬 목록이 보이지 않는다. CORE 스킬 지도의 경로로 SKILL.md를 읽는다.
# 사용법: ./install.sh [--apply] [--retire | --keep-legacy] [--include-default]
set -u

resolve() { readlink -f "$1" 2>/dev/null || python3 -c 'import os,sys;print(os.path.realpath(sys.argv[1]))' "$1"; }

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
WANT_DIR="$(cd "$HOME/dev/fstack" 2>/dev/null && pwd -P || echo "$HOME/dev/fstack")"
SKILLS=(council research build verify ship sol-loop full-send full-stop ops setup walk wrap harness lesson)
# 대체 대상(fstack이 대신하는 옛 스킬 이름)은 개인 폴더의 local/retire.txt에서 읽는다. 없으면 비어 있다.
RETIRE=()
if [ -f "$REPO_DIR/local/retire.txt" ]; then
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in ''|\#*) ;; *) RETIRE+=("$line") ;; esac
  done < "$REPO_DIR/local/retire.txt"
fi
MARK_BEGIN="<!-- fstack:begin"
BEGIN="<!-- fstack:begin (install.sh가 관리한다. 직접 고치지 말고 ~/dev/fstack/CORE.md를 고친 뒤 install.sh --apply) -->"
END="<!-- fstack:end -->"
STAMP="$(date +%Y%m%d)"

APPLY=0 RETIRE_ON=0 KEEP_LEGACY=0 INCLUDE_DEFAULT=0
for arg in "$@"; do
  case "$arg" in
    --apply) APPLY=1 ;;
    --retire) RETIRE_ON=1 ;;
    --keep-legacy) KEEP_LEGACY=1 ;;
    --include-default) INCLUDE_DEFAULT=1 ;;
    -h|--help) sed -n '2,/^# 사용법/p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "알 수 없는 인자: $arg" >&2; exit 2 ;;
  esac
done
if [ "$RETIRE_ON" -eq 1 ] && [ "$KEEP_LEGACY" -eq 1 ]; then echo "--retire 와 --keep-legacy 는 함께 쓸 수 없다" >&2; exit 2; fi

say() { printf '%s\n' "$*"; }

if [ "$REPO_DIR" != "$WANT_DIR" ]; then
  say "오류: fstack은 ~/dev/fstack 에 있어야 한다(지금: $REPO_DIR). CORE와 스킬이 이 경로를 참조한다."
  exit 2
fi

in_list() { local x="$1"; shift; local n; for n in "$@"; do [ "$n" = "$x" ] && return 0; done; return 1; }
is_fstack() { [ -L "$1" ] && [ "$(resolve "$1")" = "$REPO_DIR/skills/$(basename "$1")" ]; }
exists() { [ -e "$1" ] || [ -L "$1" ]; }

# --- 대상 찾기 -------------------------------------------------------------
# 계정 폴더: ~/.claude-<이름> 중 실제로 쓰는 설정 폴더(.claude.json 또는 projects/가 있음). 이름에 backup이 든 폴더는 뺀다.
is_account_dir() {
  case "$(basename "$1")" in *backup*) return 1 ;; esac
  [ -d "$1" ] && { [ -e "$1/.claude.json" ] || [ -d "$1/projects" ]; }
}
SKILL_DIRS=()
for base in "$HOME/.claude" "$HOME/.agents" "$HOME/.codex"; do
  [ -d "$base" ] && SKILL_DIRS+=("$base/skills")
done
for base in "$HOME"/.claude-*; do
  is_account_dir "$base" && SKILL_DIRS+=("$base/skills")
done

CLAUDE_FILES=()
others=0
for base in "$HOME"/.claude-*; do
  if is_account_dir "$base"; then CLAUDE_FILES+=("$base/CLAUDE.md"); others=1; fi
done
default_note=""
if [ -d "$HOME/.claude" ]; then
  if [ "$INCLUDE_DEFAULT" -eq 1 ] || [ "$others" -eq 0 ]; then
    CLAUDE_FILES+=("$HOME/.claude/CLAUDE.md")
  else
    default_note="기본 프로필 ~/.claude: 스킬 링크는 걸지만 CORE는 넣지 않는다. CLAUDE_CONFIG_DIR 없이 claude를 쓰면 --include-default 로 포함한다."
  fi
fi

BLOCK_FILES=()
seen=""
for f in ${CLAUDE_FILES[@]+"${CLAUDE_FILES[@]}"} "$HOME/.codex/AGENTS.md" "$HOME/.pi/agent/AGENTS.md"; do
  [ -d "$(dirname "$f")" ] || continue
  real="$(resolve "$f")"
  case " $seen " in *" $real "*) continue ;; esac
  seen="$seen $real"
  BLOCK_FILES+=("$real")
done

# --- 1단계: 계획 (아무것도 바꾸지 않는다) ------------------------------------
links=() retires=() conflicts=() blocks=()

for dir in ${SKILL_DIRS[@]+"${SKILL_DIRS[@]}"}; do
  for n in ${RETIRE[@]+"${RETIRE[@]}"}; do
    e="$dir/$n"
    exists "$e" || continue
    is_fstack "$e" && continue
    if [ "$RETIRE_ON" -eq 1 ]; then
      retires+=("$e")
    elif ! in_list "$n" "${SKILLS[@]}" && [ "$KEEP_LEGACY" -eq 0 ]; then
      conflicts+=("$e (옛 스킬. --retire 또는 --keep-legacy)")
    fi
  done
  for s in "${SKILLS[@]}"; do
    e="$dir/$s"
    is_fstack "$e" && continue
    if exists "$e"; then
      if [ "$RETIRE_ON" -eq 1 ] && in_list "$s" ${RETIRE[@]+"${RETIRE[@]}"}; then links+=("$e"); else conflicts+=("$e (같은 이름의 다른 항목)"); fi
    else
      links+=("$e")
    fi
  done
done

block_of() { awk -v m="$MARK_BEGIN" -v e="$END" 'index($0,m)==1{p=1} p{print} $0==e{p=0}' "$1"; }
# 표지 상태: 0 = 없음, 1 = 시작·끝이 짝을 이룬 블록 하나, 2 = 그 밖(끝 없음, 시작이 겹침, 끝이 먼저, 블록 여러 개, 끝 표지 문구가 다름)
marker_state() {
  awk -v m="$MARK_BEGIN" -v ep="<!-- fstack:end" -v e="$END" '
    index($0,m)==1 { if (open) bad=1; open=1; n++ }
    index($0,ep)==1 { if (!open || $0 != e) bad=1; open=0 }
    END { if (open || bad || n > 1) print 2; else print n }' "$1"
}
# frontmatter(첫 줄 --- 부터 다음 --- 까지)와 그 뒤 빈 줄을 뗀다. check_fstack.py의 strip_frontmatter와 같다.
strip_fm() { awk 'NR==1 && $0=="---" {fm=1; next} fm==1 { if ($0=="---") { fm=2; lead=1 }; next } lead && $0=="" {next} {lead=0; print}' "$1"; }
LOCAL_CORE="$REPO_DIR/local/core.md"
[ -f "$REPO_DIR/local/routing.md" ] || say "경고: local/routing.md가 없다. 스킬은 모델 역할·호스트·저장소 규칙을 이 파일에서 읽으므로, 채우기 전에는 그 값을 모른다(공개 CORE만 싣는다). ROUTING.example.md를 local/routing.md로 복사해 채운다. --installed 검사는 이 파일이 없으면 실패한다."
want_block="$(printf '%s\n' "$BEGIN"; cat "$REPO_DIR/CORE.md"; if [ -f "$LOCAL_CORE" ]; then printf '\n'; strip_fm "$LOCAL_CORE"; fi; printf '%s\n' "$END")"
for f in ${BLOCK_FILES[@]+"${BLOCK_FILES[@]}"}; do
  if [ -f "$f" ]; then
    case "$(marker_state "$f")" in
      2) conflicts+=("$f (fstack 표지의 순서·짝이 맞지 않거나 블록이 여러 개다. 직접 확인)"); continue ;;
      1) [ "$(block_of "$f")" = "$want_block" ] && continue ;;
    esac
  fi
  blocks+=("$f")
done

for e in ${retires[@]+"${retires[@]}"}; do say "예정: 은퇴 $e -> $(dirname "$e")/.retired-fstack-$STAMP/"; done
for e in ${links[@]+"${links[@]}"}; do say "예정: 링크 $e"; done
for f in ${blocks[@]+"${blocks[@]}"}; do
  if [ -f "$f" ] && grep -q "^$MARK_BEGIN" "$f"; then say "예정: CORE 블록 갱신 $f"; else say "예정: CORE 블록 추가 $f"; fi
done
[ -n "$default_note" ] && say "참고: $default_note"
for e in ${conflicts[@]+"${conflicts[@]}"}; do say "충돌: $e"; done

if [ "${#conflicts[@]}" -gt 0 ]; then
  say "실패: 충돌 ${#conflicts[@]}개. 아무것도 바꾸지 않았다."
  exit 1
fi
if [ "$APPLY" -eq 0 ]; then
  say "요약(점검 모드, 바꾼 것 없음): 은퇴 ${#retires[@]} · 링크 ${#links[@]} · CORE 블록 ${#blocks[@]}"
  exit 0
fi

# --- 2단계: 반영 -------------------------------------------------------------
failed=0
for e in ${retires[@]+"${retires[@]}"}; do
  dest="$(dirname "$e")/.retired-fstack-$STAMP"
  if mkdir -p "$dest" && mv "$e" "$dest/"; then say "은퇴: $e"; else say "오류: $e 를 옮기지 못했다"; failed=$((failed + 1)); fi
done
for e in ${links[@]+"${links[@]}"}; do
  if mkdir -p "$(dirname "$e")" && ln -s "$REPO_DIR/skills/$(basename "$e")" "$e"; then say "링크: $e"; else say "오류: $e"; failed=$((failed + 1)); fi
done
for f in ${blocks[@]+"${blocks[@]}"}; do
  tmp="$(mktemp)"
  if [ -f "$f" ]; then
    grep -q "^$MARK_BEGIN" "$f" || cp -p "$f" "$f.bak-$STAMP"
    # 기존 블록을 빼고, 끝의 빈 줄을 지운 뒤 빈 줄 하나와 새 블록을 붙인다(갱신해도 빈 줄이 늘지 않는다)
    awk -v m="$MARK_BEGIN" -v e="$END" 'index($0,m)==1{skip=1} !skip{print} $0==e{skip=0}' "$f" \
      | awk '{l[NR]=$0} END{n=NR; while (n>0 && l[n] ~ /^[[:space:]]*$/) n--; for (i=1;i<=n;i++) print l[i]; if (n>0) print ""}' > "$tmp"
  fi
  printf '%s\n' "$want_block" >> "$tmp"
  if [ -f "$f" ]; then cat "$tmp" > "$f"; else mkdir -p "$(dirname "$f")" && cp "$tmp" "$f"; fi \
    && say "CORE 블록: $f" || { say "오류: $f"; failed=$((failed + 1)); }
  rm -f "$tmp"
done
say "요약: 은퇴 ${#retires[@]} · 링크 ${#links[@]} · CORE 블록 ${#blocks[@]} · 오류 $failed"
say "확인: 쓰는 계정마다 새 세션(저장소 안과 /tmp)에서 'fstack CORE의 C8은?'을 물어 CORE가 실렸는지 본다. python3 -I $REPO_DIR/tools/check_fstack.py --installed"
[ "$failed" -eq 0 ]
