# Controlled stop

1. Stop accepting new decision requests.
2. Stop producing new manifests.
3. Finish or pause Masscan and L7 inflight work per execution profile.
4. Flush result spool and decision metadata.
5. WAL checkpoint and snapshot.

# Emergency stop

On a manifest-external target, abuse report, audit integrity failure, corrupt DB, critical disk/spool or unexpected traffic, the kill switch stops all network execution. Evidence is preserved. Automatic restart is forbidden.
