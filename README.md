# Hloppy - The Slack Praise Bot 🌟

Hloppy is a Slack bot that enables team members to praise each other, fostering a positive and supportive work environment. The bot tracks praises given and received, maintains weekly limits, and provides leaderboard statistics.

## Features

- Give praise to team members using simple Slack commands
- Support for multiple mentions in a single praise
- Weekly limit of 3 praises per user
- Automatic bi-weekly leaderboard updates
- Persistent storage of praise history
- Real-time statistics and standings

## Commands

- `/hloppy @user Your praise message` - Give praise to a team member
- `/hloppy @user1 @user2 Your praise message` - Praise multiple team members
- `/stats` - View current praise statistics and standings

## Setup

1. Create a Slack App in your workspace
2. Enable Socket Mode for your app
3. Add the following bot token scopes:
   - `chat:write`
   - `commands`
   - `users:read`
   - `users:read.email`
4. Create a `.env` file with the following variables:
   ```
   SLACK_BOT_TOKEN=xoxb-your-bot-token
   SLACK_APP_TOKEN=xapp-your-app-token
   SLACK_SIGNING_SECRET=your-signing-secret
   ```
5. Install required dependencies:
   ```bash
   pip install -r requirements.txt
   ```
6. Run the bot:
   ```bash
   python3 hloppy_bot.py
   ```

## File Structure

- `hloppy_bot.py` - Main bot implementation with two main classes:
  - `PraiseData`: Handles data persistence and praise tracking
  - `HloppyBot`: Manages Slack interactions and bot functionality
- `hloppy_data.json` - JSON file storing praise history
- `hloppy_bot.log` - Log file for debugging and monitoring
- `.env` - Environment variables configuration
- `requirements.txt` - Python dependencies

## Data Storage

Praises are stored in `hloppy_data.json` with the following structure:
```json
{
  "user_id": {
    "received": [
      {
        "from_user": "sender_id",
        "message": "praise message",
        "timestamp": "ISO datetime"
      }
    ],
    "given": [
      {
        "to_user": "receiver_id",
        "message": "praise message",
        "timestamp": "ISO datetime"
      }
    ]
  }
}
```

## Recent Changes

1. Improved standings calculation to properly include all users who have received or given praises
2. Fixed weekly praise limit tracking to accurately count praises within the current week
3. Enhanced data structure to ensure proper initialization of user data
4. Improved error handling and user feedback messages
5. Implemented real-time data loading for accurate statistics
6. Removed legacy fields from data structure for cleaner storage
7. Added proper validation for user existence and activity
8. Fixed edge cases in praise counting and display

## Requirements

- Python 3.7+
- slack-bolt
- python-dotenv
- schedule

## Contributing

Feel free to submit issues and enhancement requests! 