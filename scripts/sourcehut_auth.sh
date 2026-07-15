sourcehut_auth() {
  local had_xtrace=0 hut_config
  case "$-" in *x*) had_xtrace=1; set +x ;; esac

  if [[ -z "${SRHT_TOKEN:-}" ]]; then
    SRHT_TOKEN="${OAUTH2_TOKEN:-}"
    hut_config="${HOME:-}/.config/hut/config"
    if [[ -z "$SRHT_TOKEN" && -f "$hut_config" ]] && [[ "$(<"$hut_config")" =~ access-token[[:space:]]+\"([^\"]+)\" ]]; then
      SRHT_TOKEN="${BASH_REMATCH[1]}"
    fi
    if [[ -n "$SRHT_TOKEN" ]]; then export SRHT_TOKEN; fi
  fi

  if [[ "$had_xtrace" -eq 1 ]]; then set -x; fi
}
