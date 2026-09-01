# EM Bot Community Daily System Update

This update changes the community scheduler to three behaviors.

## Daily knowledge
The daily post is now an information/trivia post, not a discussion question. The bot selects a topic, retrieves text from configured sources, asks the AI to create one fact plus a short explanation, checks for repetition, and verifies the claims against the supplied source before posting.

`knowledge/daily_topics.json` is now a small source configuration file rather than a large prompt database. You can add or remove trusted source URLs without writing daily facts manually.

Supported topic examples include Game Development, Game Engines, Animation, 3D Art, Computer Graphics, Programming for Games, Anime, Animated Works, and Games.

## Daily duplicate protection
The scheduled daily post uses the persistent state key `daily-knowledge:YYYY-MM-DD` in `data/community_scheduler_state.json`. After a successful post, that key prevents another scheduled post for the same Manila date, including after restarts.

`/daily_chat_now` is a test command and does not consume the scheduled daily slot, although its successful test item is retained in daily history so repetition checking can still work.

## Holiday reminders
The scheduler checks both today and three days ahead after `HOLIDAY_CHECK_TIME`. A three-day reminder uses a separate persistent key and is posted to the same `HOLIDAY_ANNOUNCEMENT_CHANNEL_IDS`.

Example:

- August 31: `Holiday Reminder` for a September 3 holiday
- September 3: `Holiday Notice`

Nationwide holidays still use the configured Official Gazette source. Local holidays still require the exact `LOCAL_HOLIDAY: YYYY-MM-DD | ...` message in the configured source channel.

## Deployment
Replace `cogs/community.py` and `knowledge/daily_topics.json` with the files in this package, then restart EM Bot. No new Python dependency is introduced by this change.
