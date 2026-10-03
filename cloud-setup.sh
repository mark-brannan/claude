#!/usr/bin/env bash
# Paste this into the Claude Code cloud environment's setup script.
#
# Why it exists: cloud sessions get claude.ai connectors delivered server-side,
# and their tool schemas are the largest fixed cost in the context floor --
# ~64k before a single useful token, with connectors the biggest single slice.
# A session on dotfiles is already covered by this repo's project settings, but
# a session on any OTHER repo reads no settings of ours and pays full price.
# This writes the deny list at USER scope, which every session reads regardless
# of which repo it was started on.
#
# Why deniedMcpServers and not disableClaudeAiConnectors: the latter is set in
# this repo's project settings, on a version well past its 2.1.182 requirement,
# and connectors loaded anyway -- it governs the CLI's own auto-fetch path, not
# the server-side delivery cloud sessions use. deniedMcpServers merges across
# ALL settings sources and beats every allowlist, and it was verified working
# live: adding one entry disconnected a running server mid-session.
#
# Deny is by NAME, so a connector added later is not covered until this list is
# refreshed. Regenerate from the ListConnectors tool when you add one.
#
# Idempotent, and it merges rather than clobbers: an existing settings.json
# keeps its other keys, and its deniedMcpServers entries are unioned with these.
set -uo pipefail

SETTINGS="${HOME}/.claude/settings.json"
mkdir -p "$(dirname "$SETTINGS")"

# Every connector installed on the account as of 2026-08-20. Server names are
# the connector's display name with spaces replaced by underscores -- the rule
# holds for all nine entries that were already denied by hand.
DENY='[
  "Audible","Autodesk_Product_Help","CourtListener","Courtroom5","DocuSeal",
  "Docusign","Dropbox","Evernote_MCP","Gmail","Google_Calendar","Google_Drive",
  "Harvey","IFTTT","Intuit_QuickBooks","Intuit_TurboTax","Legal_Data_Hunter",
  "LegalZoom","Lucid","Postman","PubMed","Scholar_Gateway","SignNow","Spotify",
  "Superhuman_Docs","Taskrabbit_Booking_Assistance","Todoist","Trello","Zapier"
]'

if ! command -v jq >/dev/null 2>&1; then
  echo "cloud-setup: jq not found, writing settings without merge" >&2
  [ -s "$SETTINGS" ] && cp "$SETTINGS" "$SETTINGS.bak"
  printf '{"deniedMcpServers":%s}\n' \
    "$(printf '%s' "$DENY" | tr -d '\n ' | sed 's/"\([^"]*\)"/{"serverName":"\1"}/g')" \
    > "$SETTINGS"
  exit 0
fi

[ -s "$SETTINGS" ] || echo '{}' > "$SETTINGS"

jq --argjson deny "$DENY" '
  .deniedMcpServers = (
    ((.deniedMcpServers // []) + ($deny | map({serverName: .})))
    | unique_by(.serverName)
  )
' "$SETTINGS" > "$SETTINGS.tmp" && mv -f "$SETTINGS.tmp" "$SETTINGS" || {
  rm -f "$SETTINGS.tmp"
  echo "cloud-setup: jq merge failed, left settings untouched" >&2
  exit 0
}

echo "cloud-setup: denied $(jq '.deniedMcpServers | length' "$SETTINGS") MCP servers at user scope"
