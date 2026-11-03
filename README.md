# U-Fly 60 availability monitor

This GitHub Actions project checks U-Fly Wanaka U-Fly 60 availability for one
person on 2026-11-09 through 2026-11-15. A Cloudflare Worker starts the workflow
every five minutes because GitHub's native cron scheduler proved too irregular.

New slots and the first monitoring failure are sent to the configured private
ntfy topic. The topic is stored as the `NTFY_TOPIC` GitHub Actions secret and is
not present in the source code.

The monitor does not log in, book, submit personal information, or make
payments. The Cloudflare scheduler stops dispatching after the monitoring
window.
