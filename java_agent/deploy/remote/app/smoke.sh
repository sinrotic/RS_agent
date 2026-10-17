#!/usr/bin/env bash
set -euo pipefail

gateway_url="${RS_SMOKE_GATEWAY_URL:-http://127.0.0.1:18088}"
profile_user_id="${RS_SMOKE_PROFILE_USER_ID:?Set RS_SMOKE_PROFILE_USER_ID to an imported amazon_reviews_base user_id}"
username="${RS_SMOKE_USERNAME:-smoke_$(date +%s)}"
password="${RS_SMOKE_PASSWORD:-SmokeOnly_2026!}"

for command_name in curl jq; do
  command -v "$command_name" >/dev/null || {
    echo "$command_name is required" >&2
    exit 1
  }
done

post_json() {
  local path="$1"
  local body="$2"
  shift 2
  curl --fail --silent --show-error \
    -H "Content-Type: application/json" \
    "$@" \
    --data "$body" \
    "$gateway_url$path"
}

wait_feedback_applied() {
  local event_id="$1"
  local status="PENDING"
  for attempt in {1..30}; do
    status="$(curl --fail --silent --show-error "${authorization[@]}" \
      "$gateway_url/api/recommend/feedback/status/$event_id" | jq -r '.application_status')"
    [[ "$status" == "APPLIED" ]] && return 0
    sleep 1
  done
  echo "feedback event $event_id did not become APPLIED (last status=$status)" >&2
  return 1
}

register_body="$(jq -nc \
  --arg username "$username" \
  --arg password "$password" \
  --arg profileUserId "$profile_user_id" \
  '{username:$username,password:$password,nickname:"Deployment Smoke",bindStrategy:"selected",profileUserId:$profileUserId}')"
auth="$(post_json /api/auth/register "$register_body")"
access_token="$(jq -er '.accessToken' <<<"$auth")"
account_id="$(jq -er '.accountId' <<<"$auth")"

authorization=(-H "Authorization: Bearer $access_token")
session="$(post_json /api/sessions '{"entryScene":"deployment-smoke"}' "${authorization[@]}")"
session_id="$(jq -er '.sessionId' <<<"$session")"

recommend_body="$(jq -nc --arg session_id "$session_id" '{session_id:$session_id,scene:"home",page_size:5,debug:false}')"
recommend="$(post_json /api/recommend/home "$recommend_body" "${authorization[@]}")"
jq -e '.request_id != null and (.items | length) > 0' >/dev/null <<<"$recommend"
recommend_request_id="$(jq -er '.request_id' <<<"$recommend")"
recommend_item_id="$(jq -er '.items[0].item_id' <<<"$recommend")"

exposure_body="$(jq -nc \
  --arg request_id "$recommend_request_id" \
  --arg session_id "$session_id" \
  --arg item_id "$recommend_item_id" \
  '{request_id:$request_id,session_id:$session_id,items:[{item_id:$item_id,position:1,visible_ratio:1.0,visible_duration_ms:1200}],exposed_at:(now*1000|floor)}')"
exposure="$(post_json /api/recommend/feedback/exposure "$exposure_body" "${authorization[@]}")"
jq -e '.accepted == true and .application_status == "NOT_APPLICABLE"' >/dev/null <<<"$exposure"

like_body="$(jq -nc \
  --arg request_id "$recommend_request_id" \
  --arg session_id "$session_id" \
  --arg item_id "$recommend_item_id" \
  '{request_id:$request_id,session_id:$session_id,item_id:$item_id,event_type:"like",event_value:1,occurred_at:(now*1000|floor)}')"
like="$(post_json /api/recommend/feedback/event "$like_body" "${authorization[@]}")"
jq -e '.accepted == true and (.application_status == "APPLIED" or .application_status == "PENDING")' >/dev/null <<<"$like"
like_event_id="$(jq -er '.feedback_id' <<<"$like")"
like_version="$(jq -er '.preference_version' <<<"$like")"
if [[ "$(jq -r '.application_status' <<<"$like")" == "PENDING" ]]; then
  wait_feedback_applied "$like_event_id"
fi

duplicate_like="$(post_json /api/recommend/feedback/event "$like_body" "${authorization[@]}")"
jq -e --arg event_id "$like_event_id" '.duplicate == true and .feedback_id == $event_id' >/dev/null <<<"$duplicate_like"

refresh_body="$(jq -nc --arg session_id "$session_id" '{session_id:$session_id,scene:"home",page_size:5,refresh_token:"feedback-smoke",debug:false}')"
refreshed="$(post_json /api/recommend/home/refresh "$refresh_body" "${authorization[@]}")"
jq -e --arg event_id "$like_event_id" --argjson version "$like_version" \
  '.preference_version >= $version and (.applied_feedback_event_ids | index($event_id)) != null' \
  >/dev/null <<<"$refreshed"

preferences="$(curl --fail --silent --show-error "${authorization[@]}" "$gateway_url/api/recommend/preferences")"
jq -e --arg item_id "$recommend_item_id" '.items | any(.item_id == $item_id and .state == "like")' >/dev/null <<<"$preferences"

reversal_body="$(jq -nc --arg event_id "$like_event_id" '{feedback_event_id:$event_id}')"
reversal="$(post_json /api/recommend/feedback/reversal "$reversal_body" "${authorization[@]}")"
jq -e '.accepted == true and (.application_status == "APPLIED" or .application_status == "PENDING")' >/dev/null <<<"$reversal"
if [[ "$(jq -r '.application_status' <<<"$reversal")" == "PENDING" ]]; then
  wait_feedback_applied "$(jq -er '.feedback_id' <<<"$reversal")"
fi

agent_body="$(jq -nc --arg session_id "$session_id" '{session_id:$session_id,user_message:"Recommend one useful item",limit:1,context:{}}')"
agent="$(post_json /api/agent/chat "$agent_body" "${authorization[@]}")"
jq -e '.request_id != null and .card_set_id != null' >/dev/null <<<"$agent"

if [[ "${RS_DEPLOYMENT_PROFILE:-recommend}" == "full-commerce" ]]; then
  # 使用提前准备的隔离测试数据；不重置库存或覆盖商品报价。
  RS_SMOKE_TOKEN="$access_token" RS_SMOKE_GATEWAY_URL="$gateway_url" \
    node "$(dirname "$0")/commerce_smoke.mjs"
  if [[ -n "${RS_SMOKE_SECKILL_ACTIVITY_ID:-}" ]]; then
    RS_SMOKE_TOKEN="$access_token" RS_SMOKE_GATEWAY_URL="$gateway_url" \
      node "$(dirname "$0")/seckill_smoke.mjs"
  fi
fi

echo "Deployment smoke passed for account=$account_id session=$session_id profile=${RS_DEPLOYMENT_PROFILE:-recommend}"
