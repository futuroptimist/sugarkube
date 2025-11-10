# Sugarkube Debug Logs

This directory collects sanitized `just up` logs when `SAVE_DEBUG_LOGS=1` is exported during a bootstrap run. Files are named with the UTC timestamp, the checked-out commit hash, the hostname, and the environment to make it easy to pair logs from multiple nodes. Secrets and external IP addresses are redacted automatically before they are written here.
