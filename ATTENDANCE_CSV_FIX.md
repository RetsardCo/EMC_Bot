# Attendance CSV fix

The previous `activity.py` was still exporting raw UTC fields:

`discord_id,display_name,first_join,last_leave,total_seconds,status`

This patch changes the export to:

- Discord ID
- Student/Display Name
- Date (Manila)
- First Join (Manila)
- Last Leave (Manila)
- Total Time
- Status

Stored attendance timestamps remain UTC internally; only the human-facing CSV
format is changed.
