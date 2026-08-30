# EM Bot

EM Bot is a Discord community assistant for the Bicol State College of Applied Sciences and Technology (BSEMC/BISCAST) community.

The bot combines role-based Discord automation, onboarding, moderation, official-document knowledge retrieval, and multi-provider AI routing.

## Features

### Discord onboarding

- Automatic welcome message for new members.
- `/setup` opens the appropriate Student or verified Faculty introduction form.
- Student setup can assign:
  - `BISCAST`
  - `Student`
  - specialization/year role
  - `Introduced`
- Nickname format is based on the user's name, specialization, and year.
- Users can complete the nickname setup only once.
- Future nickname changes must be handled manually by Moderator or EMC Faculty.
- Verified faculty can use the `!Faculty` verification role before completing the Faculty setup.
- After successful Faculty setup, `!Faculty` is replaced by `Faculty`.
- EMC Faculty remains a manually assigned elevated staff role.

### Role-based help and commands

`/help` shows commands according to the member's access level.

The bot supports different command availability for students, Faculty, Moderator, and EMC Faculty.

### Feedback

`/feedback` allows members to submit suggestions or feedback.

Feedback is intended to be forwarded into a staff-only feedback channel.

### Activity logging and voice participation

- Server joins and leaves are saved as local activity records.
- Voice joins, leaves, and channel moves are logged with observed timestamps and durations.
- Staff can optionally mirror those logs to one or more private channels by setting `ACTIVITY_LOG_CHANNEL_IDS`.
- Staff can use `/attendance_start`, `/attendance_status`, `/attendance_end`, and `/attendance_export` for a selected voice channel.
- `/activity_export` downloads server and voice records as CSV.

Attendance reports record observed Discord participation only. They do not infer that a person is absent merely because no voice activity was observed.

### Daily community chat and holiday notices

EM Bot can post one changing daily prompt about Game Development, drawing, or animation. Edit [daily_topics.json](knowledge/daily_topics.json) to add topics and prompts; the bot reads it when it posts, so changing that file does not require a bot restart.

Set `DAILY_CHAT_CHANNEL_IDS` to one or more comma-separated channel IDs and `DAILY_CHAT_TIME` to the Philippine local posting time. Staff can run `/daily_chat_now` to test a prompt immediately.

For nationwide holidays, EM Bot checks the Official Gazette's Nationwide Holidays page before posting to the channels in `HOLIDAY_ANNOUNCEMENT_CHANNEL_IDS`. It posts nothing if that source cannot be reached or does not identify a holiday for the date. For a school/local holiday, an authorized staff member must post this exact format in one of the configured `LOCAL_HOLIDAY_SOURCE_CHANNEL_IDS`:

```text
LOCAL_HOLIDAY: 2026-09-01 | No classes due to an approved local holiday.
```

### Moderation

The bot includes configurable protections for:

- Spam
- Repeated messages
- Excessive mentions
- New-account raids
- Automatic timeouts
- Bad-word filtering
- Link restrictions
- Role/channel exemptions

### AI system

EM Bot uses an external-provider architecture rather than running a local language model.

Configured providers can include:

- Gemini
- OpenRouter
- Mistral

The AI router can select different models for different request types, including:

- General questions
- Coding
- Reasoning
- Fast responses
- Vision/image questions
- Agent/tool-style tasks

The bot keeps the AI output limit configurable with:

```env
AI_MAX_OUTPUT_TOKENS=1200
```

Images can be processed through the vision route when supported.

## Official-information safety model

Official BSEMC information is treated differently from ordinary educational questions.

The bot is instructed to:

1. Use verified official documents as authoritative sources.
2. Never invent missing curriculum subjects, units, prerequisites, requirements, dates, or policies.
3. Say that verified information is unavailable when the official knowledge base does not contain the requested information.
4. Avoid presenting general model knowledge as current official BSEMC information.
5. Prefer structured verified JSON/CSV over AI-extracted PDF knowledge.

This is especially important for curriculum, attendance, admissions, grading, policies, and student-handbook questions.

## Knowledge system

The knowledge system supports:

```text
JSON
CSV
PDF
Markdown cache
```

### Recommended knowledge hierarchy

```text
Verified JSON/CSV
        ↓
Direct structured retrieval
        ↓
AI formatting
```

For PDFs:

```text
PDF
 ↓
AI extraction
 ↓
DRAFT
 ↓
Staff review
 ↓
Approve
 ↓
VERIFIED / CURRENT
```

A PDF extraction is therefore not automatically treated as authoritative.

### Why JSON is preferred for structured information

For curricula, course descriptions, policies, and other structured official information, JSON is preferred because it preserves hierarchy and fields such as:

```text
Program
Year
Semester
Course code
Course title
Units
Prerequisite
Description
Policy section
```

CSV is useful for flat tables.

PDF is retained as an original/reference document, but AI-extracted PDF data requires review before becoming authoritative.

## Knowledge document lifecycle

Documents can have these states:

```text
🟡 DRAFT
🔒 VERIFIED
✅ CURRENT
🗃️ ARCHIVED
```

### Meaning

**DRAFT**

AI-extracted PDF/Markdown knowledge that still requires staff review.

**VERIFIED**

Structured or reviewed knowledge that is trusted but may not be the active/current document.

**CURRENT**

The active official document used for current questions.

**ARCHIVED**

Historical knowledge retained for reference but excluded from current-answer retrieval.

## Knowledge categories

The Knowledge Manager is not limited to curriculum.

Supported categories include:

```text
curriculum
program_specifications
course_descriptions
admissions
student_handbook
rules
faq
events
policies
faculty
scholarship
internship
specialization
academic_calendar
syllabus
other
```

Single-current categories can keep one active document per scope, while categories such as events or FAQ can support multiple current documents.

## Knowledge Manager

Staff can use:

```text
/knowledge
```

This opens the private Knowledge Manager GUI.

The GUI can be used to:

- View stored documents.
- Inspect document status.
- Select a document.
- Set a document as Current.
- Archive a document.
- Review pending PDF extractions.
- Repair legacy JSON/CSV status metadata.
- Activate verified structured documents.

### Bulk activation

The Knowledge Manager includes:

```text
✅ Set All Verified as Current
```

This is useful after:

- A server restart
- A fresh deployment
- Importing a knowledge backup
- Rebuilding the knowledge directory

It activates eligible verified JSON/CSV documents.

PDF/Markdown drafts are not automatically activated.

### Legacy status repair

The Knowledge Manager also includes:

```text
🔧 Repair JSON/CSV Status
```

This repairs older knowledge manifests where structured JSON/CSV files may have been incorrectly recorded as DRAFT.

## Knowledge commands

Common staff commands include:

```text
/knowledge
/knowledge_add
/knowledge_list
/knowledge_export
/knowledge_export_md
/knowledge_import
/knowledge_rebuild
/knowledge_rebuild_structured
/knowledge_test
```

### `/knowledge_test`

`/knowledge_test` is the main knowledge diagnostic command.

It tests the same general retrieval path used by `/ask` and reports:

```text
Expected source
Category
Status used
Route
Expected fields
Expected answer data
```

Example:

```text
/knowledge_test question: What is GD 302?
```

A successful result should identify the appropriate structured source, such as:

```text
BSEMC_course_descriptions.json
```

and report that the route used direct verified JSON.

## Direct structured retrieval

For structured official information, the bot uses direct lookup before generic knowledge fallback.

Example:

```text
User:
What is GD 302?

Knowledge router:
1. Detect explicit course code GD 302
2. Search verified JSON course records
3. Match courses[].code
4. Select the exact course record
5. Pass the exact record to the AI
6. AI formats the response
```

This prevents unrelated PDFs or general model knowledge from replacing an exact structured fact.

The same approach can be used for:

- Course codes
- Prerequisites
- Units
- Student-handbook policies
- Attendance rules
- Admissions requirements
- Scholarship information
- Program specifications
- Course descriptions

## Curriculum management

Curriculum documents should be treated as versioned official knowledge.

Example:

```text
2023_bsemc-gd_curr_approved.json
        ↓
🗃️ ARCHIVED

2026_bsemc-gd_curr_approved.json
        ↓
✅ CURRENT
```

Older curricula can remain stored for historical reference.

The active curriculum should be explicitly marked Current rather than allowing the AI to guess which version is newer.

## Startup/recovery workflow

After a production restart:

```text
1. Start the bot
2. Run /knowledge
3. Check knowledge statuses
4. Use Repair JSON/CSV Status if necessary
5. Use Set All Verified as Current when appropriate
6. Run /knowledge_test
7. Test /ask
```

This is especially useful on low-resource hosting or after importing knowledge backups.

## Production hosting

EM Bot is designed to use external AI APIs rather than running local AI models.

This makes it suitable for small servers such as a VM with approximately:

```text
512 MB RAM
1 GB disk
limited CPU
```

For low-resource production servers:

- Prefer JSON/CSV for important structured knowledge.
- Avoid large PDF collections.
- Keep AI history short.
- Limit output tokens.
- Avoid unnecessary in-memory caching.
- Use external AI providers for inference.

## Environment variables

A typical production `.env` contains:

```env
# Discord
DISCORD_TOKEN=
TEST_GUILD_IDS=

# Roles
FACULTY_ROLE_NAME=Faculty
MODERATOR_ROLE_NAME=Moderator
STUDENT_ROLE_NAME=Student
INTRODUCED_ROLE_NAME=Introduced
UNINTRODUCED_ROLE_NAME=Unintroduced

# Channels
WELCOME_CHANNEL_ID=0
INTRO_COMPLETE_CHANNEL_ID=0
INTRO_CHANNEL_ID=0
MOD_LOG_CHANNEL_ID=0
AI_CHANNEL_ID=0
ACTIVITY_LOG_CHANNEL_IDS=

# Activity and attendance
ACTIVITY_DATA_DIR=data
ATTENDANCE_LATE_AFTER_MINUTES=15

# Community engagement
COMMUNITY_TIMEZONE=Asia/Manila
DAILY_CHAT_CHANNEL_IDS=
DAILY_CHAT_TIME=09:00
DAILY_CHAT_TOPICS_FILE=knowledge/daily_topics.json

# Holiday notices
HOLIDAY_ANNOUNCEMENT_CHANNEL_IDS=
HOLIDAY_CHECK_TIME=06:00
NATIONWIDE_HOLIDAY_URL=https://www.officialgazette.gov.ph/nationwide-holidays/
LOCAL_HOLIDAY_SOURCE_CHANNEL_IDS=
LOCAL_HOLIDAY_SOURCE_LOOKBACK_MESSAGES=200

# AI providers
GEMINI_API_KEY=
GEMINI_MODEL=gemini-3.6-flash

OPENROUTER_API_KEY=
OPENROUTER_CODING_MODEL=openai/gpt-oss-120b:free
OPENROUTER_CODING_FALLBACK=qwen/qwen3-coder:free
OPENROUTER_REASONING_MODEL=nvidia/nemotron-3-ultra-550b-a55b:free
OPENROUTER_FAST_MODEL=openai/gpt-oss-20b:free
OPENROUTER_LIGHTNING_MODEL=nvidia/nemotron-3.5-lightning:free
OPENROUTER_VISION_MODEL=google/gemma-4-31b-it:free
OPENROUTER_VISION_FALLBACK=nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free
OPENROUTER_AGENT_MODEL=openai/gpt-oss-120b:free

MISTRAL_API_KEY=
MISTRAL_MODEL=mistral-small-latest

# AI settings
AI_COOLDOWN_SECONDS=10
AI_MAX_HISTORY_TURNS=4
AI_MAX_OUTPUT_TOKENS=1200
AI_MAX_IMAGE_BYTES=3145728

# Official BSEMC source channels
AI_SOURCE_CHANNEL_IDS=
AI_SOURCE_LOOKBACK_MESSAGES=50
```

Do not commit `.env` or API keys to GitHub.

## Installation

### 1. Clone the repository

```bash
git clone <YOUR_REPOSITORY_URL>
cd EM_Bot
```

### 2. Create a virtual environment

Windows:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure `.env`

Create:

```text
.env
```

and add the required Discord and AI provider credentials.

### 5. Start the bot

```bash
python bot.py
```

## Development and production

Recommended workflow:

```text
Development machine
        ↓
Test Discord server
        ↓
Verify commands / knowledge / AI
        ↓
Production server
        ↓
Official Discord server
```

Do not test potentially destructive moderation or knowledge changes directly on production when a development server is available.

## Security

Never commit any of the following:

```text
DISCORD_TOKEN
GEMINI_API_KEY
OPENROUTER_API_KEY
MISTRAL_API_KEY
.env
```

Also review Discord permissions carefully, especially for:

- Manage Nicknames
- Manage Roles
- Moderate Members
- Manage Messages
- View Audit Log
- Send Messages

The `EMC Faculty` role should be manually controlled because it provides elevated administrative capabilities.

## Suggested repository structure

```text
EM_Bot/
├── bot.py
├── .env
├── requirements.txt
├── cogs/
│   ├── ai.py
│   ├── activity.py
│   ├── admin.py
│   ├── automod.py
│   ├── community.py
│   ├── feedback.py
│   ├── help.py
│   ├── introduction.py
│   ├── knowledge.py
│   ├── moderation.py
│   ├── polls.py
│   └── welcome.py
├── knowledge/
│   ├── source/
│   ├── cache/
│   ├── drafts/
│   └── manifest.json
└── README.md
```

## Current design principles

The current architecture follows these priorities:

```text
Exact verified structured data
        ↓
Direct source retrieval
        ↓
AI formatting
        ↓
Generic knowledge fallback
```

The AI should explain official information, not invent or reconstruct it.

For official documents, a verified source should always take priority over model memory.


## Maintainer notes

When updating the bot:

1. Test changes on the development Discord server.
2. Verify `/knowledge_test` before testing `/ask`.
3. Check document status after deployment.
4. Use `/knowledge` to manage Current/Verified/Archived state.
5. Keep structured JSON/CSV authoritative and reviewed.
6. Treat PDF extraction as draft knowledge until manually approved.
