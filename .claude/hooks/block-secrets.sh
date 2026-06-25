#!/usr/bin/env bash
# PreToolUse hook on Bash: blocks `git commit`/`git push` when the diff being
# committed/pushed contains an .env file or a secret-shaped value. Mechanical
# backstop for design.md's "no secrets/.env in git" rule, now that this repo
# is public (gupta-builds/TradingView).
set -u

input="$(cat)"
command="$(printf '%s' "$input" | jq -r '.tool_input.command // empty' 2>/dev/null)"

[ -z "$command" ] && exit 0

deny() {
  local reason="$1"
  printf 'BLOCKED: %s\n' "$reason" >&2
  jq -n --arg reason "$reason" \
    '{continue:false, stopReason:$reason, hookSpecificOutput:{hookEventName:"PreToolUse", permissionDecision:"deny", permissionDecisionReason:$reason}}'
  exit 0
}

is_commit=false
is_push=false
printf '%s' "$command" | grep -Eq '\bgit\b.*\bcommit\b' && is_commit=true
printf '%s' "$command" | grep -Eq '\bgit\b.*\bpush\b' && is_push=true

if [ "$is_commit" = false ] && [ "$is_push" = false ]; then
  exit 0
fi

if [ "$is_commit" = true ]; then
  diff_files="$(git diff --cached --name-only 2>/dev/null)"
  diff_content="$(git diff --cached 2>/dev/null)"
else
  range="$(git rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null)"
  if [ -n "$range" ]; then
    diff_files="$(git diff "${range}..HEAD" --name-only 2>/dev/null)"
    diff_content="$(git diff "${range}..HEAD" 2>/dev/null)"
  else
    diff_files="$(git diff origin/main...HEAD --name-only 2>/dev/null || git diff origin/master...HEAD --name-only 2>/dev/null)"
    diff_content="$(git diff origin/main...HEAD 2>/dev/null || git diff origin/master...HEAD 2>/dev/null)"
  fi
fi

if printf '%s\n' "$diff_files" | grep -Eq '(^|/)\.env$|(^|/)\.env\.[^.]+$' \
   && ! printf '%s\n' "$diff_files" | grep -Eq '(^|/)\.env\.example$'; then
  deny "a .env file is staged/about to be pushed. design.md requires .env to stay out of git."
fi

if printf '%s' "$diff_content" | grep -Eiq '(api[_-]?key|secret|token|password)[[:space:]]*[:=][[:space:]]*['"'"'"]?[A-Za-z0-9_-]{8,}|sk-[A-Za-z0-9]{16,}'; then
  deny "the diff contains what looks like a secret/API key/token. Remove it before committing/pushing (design.md secrets policy)."
fi

exit 0
