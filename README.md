# U-Fly 60 availability monitor

This private GitHub Actions project checks U-Fly Wanaka U-Fly 60 availability
for one person on 2026-11-09 through 2026-11-15 every five minutes.

New slots and the first monitoring failure are sent to the configured private
ntfy topic. The topic is stored as the `NTFY_TOPIC` GitHub Actions secret and is
not present in the source code.

The monitor does not log in, book, submit personal information, or make
payments. It disables its own scheduled workflow after the monitoring window.
