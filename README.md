# EM Bot

A database-free Discord bot for the BSEMC community.

## Current features

- Welcome message when a member joins (optional welcome channel)
- Introduction button with Discord Modal forms
- Nickname formatting based on existing server roles
  - Student: `Name BSEMC DAT 1st Year`
  - Student: `Name BSEMC GD 1st Year`
  - Faculty: `Name BSEMC Faculty`
- Moderation: timeout, kick, ban, purge
- Admin tools: manual nickname change, server info, announcements
- No database
- No music module

## Important design choice

EM Bot does **not** assign Student/Faculty/DAT/GD roles. Your community questions system is responsible for role assignment. EM Bot only checks whether the member already has the `Student` or `Faculty` role.

## Discord permissions

The bot should have:

- View Channels
- Send Messages
- Embed Links
- Read Message History
- Manage Nicknames
- Moderate Members
- Kick Members (if you want `/kick`)
- Ban Members (if you want `/ban`)
- Manage Messages (if you want `/purge`)
- Manage Server (only for admin actions, depending on command permissions)

Also place the bot's role **above the roles of members it needs to rename or moderate**.

## Intents

In the Discord Developer Portal, enable:

- Server Members Intent
- Message Content Intent

The bot uses the members intent to handle welcome events and inspect member roles.

## Setup

1. Install Python 3.11 or newer.
2. Open a terminal in this folder.
3. Create a virtual environment:

   `python -m venv .venv`

4. Activate it on Windows PowerShell:

   `.\.venv\Scripts\Activate.ps1`

5. Install dependencies:

   `pip install -r requirements.txt`

6. Copy `.env.example` to `.env`.
7. Put your Discord bot token in `.env`.
8. Set your channel IDs if you want welcome/log channels.
9. Run:

   `python bot.py`

## First server setup

Once the bot is online:

1. Make sure the server has roles named exactly `Student` and `Faculty` (or change the names in `.env`).
2. Put the EM Bot role above those roles.
3. In the channel where you want the introduction panel, run:

   `/setup_intro`

4. Test the button with a test Student or Faculty account/role.

## Commands

### Nickname / introduction

- `/setup_intro`

### Moderation

- `/timeout`
- `/kick`
- `/ban`
- `/purge`

### Admin

- `/nick`
- `/serverinfo`
- `/announce`

## Project structure

```text
EM_Bot/
├── bot.py
├── requirements.txt
├── .env.example
├── .gitignore
├── README.md
└── cogs/
    ├── __init__.py
    ├── welcome.py
    ├── introduction.py
    ├── moderation.py
    └── admin.py
```

## Future expansion

This structure is intended to be expanded with additional cogs later, such as verification, event tools, logging, community-question integration, automated announcements, or music.
