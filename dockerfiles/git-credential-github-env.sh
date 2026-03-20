#!/bin/sh
# Invoked by Git during push/pull — not by you or the agent. Reads $GITHUB_TOKEN from the container env
# (sandbox profile → docker -e). No build-time secret, no entrypoint.
set -e
case "$1" in
get) ;;
store | erase) exit 0 ;;
*) exit 1 ;;
esac

host=""
proto=""
while IFS= read -r line; do
    [ -z "$line" ] && break
    case "$line" in
    host=*) host="${line#host=}" ;;
    protocol=*) proto="${line#protocol=}" ;;
    esac
done

[ "$proto" = "https" ] || exit 1
[ "$host" = "github.com" ] || exit 1
[ -n "$GITHUB_TOKEN" ] || exit 1

printf '%s\n' "username=x-access-token" "password=$GITHUB_TOKEN"
