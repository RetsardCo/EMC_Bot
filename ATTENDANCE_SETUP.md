# EM Bot Attendance Update

## Main change

`/attendance_end` now generates an ephemeral beginner-friendly GUI report
from the exact same attendance rows used for the CSV export.

The GUI shows:
- Session
- Voice channel
- Manila date
- Manila start/end time
- Recorded participants
- Present
- Late
- Left Early
- Each participant's display name
- First join
- Last leave
- Total participation time
- Status

The report has Previous/Next buttons for larger lists.

## No automatic absence

The system does not create an `Absent` status from missing voice activity.
It only reports observed voice participation.

## Multiple voice sessions

Multiple attendance sessions can run at the same time in one server when they
observe different voice channels.

Example:

```text
GD 4th Year VC  -> Session A
DAT 2nd Year VC -> Session B
Faculty VC      -> Session C
```

The same voice channel cannot have two active attendance sessions at the same
time.

When more than one session is active, `/attendance_status` and
`/attendance_end` show a private session selector. You can also supply the
voice channel directly.

## Manila time

Stored event timestamps remain UTC ISO-8601.

Attendance GUI and CSV filenames use `Asia/Manila` / UTC+8.

The module includes a UTC+8 fallback if the system timezone database is
missing, but installing `tzdata` is recommended.

## Existing data

The loader accepts the previous guild-keyed attendance_sessions.json format
and converts it to unique session IDs so existing records are not discarded.

## Deployment

Replace:

```text
cogs/activity.py
```

Add `tzdata` to `requirements.txt`:

```text
tzdata>=2025.2
```

or run:

```bash
pip install -r requirements-attendance.txt
```

Keep your existing:

```env
ACTIVITY_LOG_CHANNEL_IDS=...
ACTIVITY_DATA_DIR=data
ATTENDANCE_LATE_AFTER_MINUTES=15
```

No database is required for this update.


## Beginner-friendly CSV format

The attendance CSV is exported in Manila time and uses readable values:

```text
Discord ID
Student/Display Name
Date (Manila)
First Join (Manila)
Last Leave (Manila)
Total Time
Status
```

Example:

```text
723270517804499087,KURADOS猫ねこ,August 31, 2026,02:31:56 AM,02:38:41 AM,6m 45s,Present
```

The raw UTC timestamps are still retained internally; the CSV is the
human-readable staff/research report.
