import os
import json
import logging
import schedule
import time
import threading
from datetime import datetime, timedelta
from collections import defaultdict
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from dotenv import load_dotenv

# Constants
DATA_FILE = 'hloppy_data.json'
WEEKLY_PRAISE_LIMIT = 3
LEADERBOARD_SCHEDULE_DAYS = 14
LEADERBOARD_POST_TIME = "10:00"

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(name)s - %(message)s',
    handlers=[
        logging.FileHandler('hloppy_bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class PraiseData:
    """Handles storage and retrieval of praise data"""
    
    def __init__(self, app=None):
        """Initialize PraiseData with optional Slack app instance"""
        self.data = self._create_empty_data()
        self.app = app
        self.load_data()

    def _create_empty_data(self):
        """Create an empty data structure with proper defaults"""
        def create_user_data():
            return {
                'received': [],
                'given': []
            }
        return defaultdict(create_user_data)

    def load_data(self):
        """Load and parse praise data from JSON file"""
        try:
            if os.path.exists(DATA_FILE):
                with open(DATA_FILE, 'r') as f:
                    data = json.load(f)
                    logger.info(f"Loaded data from {DATA_FILE}: {json.dumps(data, indent=2)}")
                    
                    # Always start with a fresh defaultdict
                    self.data = self._create_empty_data()
                    
                    if not data:  # Empty file or just {}
                        logger.info("Data file is empty, using fresh empty data structure")
                        return
                    
                    # Parse data and convert timestamps
                    for user_id, user_data in data.items():
                        self.data[user_id]['received'] = [
                            {
                                'from_user': p['from_user'],
                                'message': p['message'],
                                'timestamp': datetime.fromisoformat(p['timestamp'])
                            }
                            for p in user_data.get('received', [])
                        ]
                        self.data[user_id]['given'] = [
                            {
                                'to_user': p['to_user'],
                                'message': p['message'],
                                'timestamp': datetime.fromisoformat(p['timestamp'])
                            }
                            for p in user_data.get('given', [])
                        ]
            else:
                logger.info(f"Data file {DATA_FILE} does not exist, using fresh empty data structure")
                self.data = self._create_empty_data()
        except Exception as e:
            logger.exception(f"Error loading data: {e}")
            self.data = self._create_empty_data()

    def save_data(self):
        """Save praise data to JSON file with ISO format timestamps"""
        try:
            data = {
                user_id: {
                    'received': [
                        {
                            'from_user': p['from_user'],
                            'message': p['message'],
                            'timestamp': p['timestamp'].isoformat()
                        }
                        for p in user_data['received']
                    ],
                    'given': [
                        {
                            'to_user': p['to_user'],
                            'message': p['message'],
                            'timestamp': p['timestamp'].isoformat()
                        }
                        for p in user_data['given']
                    ]
                }
                for user_id, user_data in self.data.items()
                if user_data['received'] or user_data['given']  # Only save users with data
            }
            logger.info(f"Saving data to {DATA_FILE}: {json.dumps(data, indent=2)}")
            with open(DATA_FILE, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.exception(f"Error saving data: {e}")

    def get_user_weekly_praises(self, user_id):
        """Get the number of praises given by a user in the current week"""
        # Always load fresh data
        self.load_data()
        
        if user_id not in self.data:
            logger.info(f"User {user_id} not found in data, returning 0 praises")
            return 0
        
        # Calculate week start (Monday 00:00:00)
        current_time = datetime.now()
        week_start = current_time - timedelta(days=current_time.weekday())
        week_start = week_start.replace(hour=0, minute=0, second=0, microsecond=0)
        
        # Count praises given this week
        weekly_count = sum(1 for praise in self.data[user_id]['given'] 
                         if praise['timestamp'] >= week_start)
        
        logger.info(f"User {user_id} has given {weekly_count} praises this week (since {week_start})")
        return weekly_count

    def add_praise(self, from_user, to_user, message):
        """Record a new praise with current timestamp"""
        self.load_data()
        current_time = datetime.now()
        
        self.data[to_user]['received'].append({
            'from_user': from_user,
            'message': message,
            'timestamp': current_time
        })
        
        self.data[from_user]['given'].append({
            'to_user': to_user,
            'message': message,
            'timestamp': current_time
        })
        
        self.save_data()

    def format_standings_message(self, app=None):
        """Format the current standings message for display"""
        app_instance = app or self.app
        if not app_instance:
            logger.error("No Slack app instance available")
            return self._get_empty_standings_message()
            
        self.load_data()
        
        # Calculate praise counts
        received = defaultdict(int)
        given = defaultdict(int)
        all_users = set()
        
        # Collect all users involved in praises
        for user_id, data in self.data.items():
            if data['received'] or data['given']:
                all_users.add(user_id)
            for praise in data['given']:
                all_users.add(praise['to_user'])
            for praise in data['received']:
                all_users.add(praise['from_user'])
        
        # Calculate counts for all users
        for user_id in all_users:
            if user_id in self.data:
                received[user_id] = len(self.data[user_id]['received'])
                given[user_id] = len(self.data[user_id]['given'])
        
        # Calculate and sort total scores
        total_scores = {uid: received[uid] + given[uid] for uid in all_users}
        sorted_users = sorted(
            [(uid, score) for uid, score in total_scores.items()],
            key=lambda x: x[1],
            reverse=True
        )
        
        if not sorted_users:
            return self._get_empty_standings_message()
        
        return self._format_standings_output(app_instance, sorted_users, received, given, total_scores)

    def _get_empty_standings_message(self):
        """Get the message for when no praises have been given"""
        return """Below you can see the statistics of praises in our team.
Each person's score is calculated as the sum of praises received and given.

_No praises have been given yet. Be the first to praise someone using_ `/hloppy @username Your praise message`!"""

    def _format_standings_output(self, app, sorted_users, received, given, total_scores):
        """Format the standings output message"""
        message = """Below you can see the statistics of praises in our team.
Each person's score is calculated as the sum of praises received and given.

*🏆 Current Standings:*"""
        
        for user_id, _ in sorted_users:
            try:
                user_info = app.client.users_info(user=user_id)
                if user_info["ok"]:
                    message += f"\n• <@{user_id}>: {received[user_id]} received + {given[user_id]} given = {total_scores[user_id]} total"
            except Exception as e:
                logger.exception(f"Error getting user info for {user_id}")
                continue
        
        return message

    def get_praise_count(self, user_id):
        """Get the total number of praises received by a user"""
        # Always load fresh data before counting
        self.load_data()
        return len(self.data.get(user_id, {}).get('received', []))

    def get_sorted_users(self):
        """Get sorted list of users with their praise statistics"""
        self.load_data()
        
        # Calculate praise counts
        received = defaultdict(int)
        given = defaultdict(int)
        all_users = set()
        
        # Collect all users involved in praises
        for user_id, data in self.data.items():
            if data['received'] or data['given']:
                all_users.add(user_id)
            for praise in data['given']:
                all_users.add(praise['to_user'])
            for praise in data['received']:
                all_users.add(praise['from_user'])
        
        # Calculate counts for all users
        for user_id in all_users:
            if user_id in self.data:
                received[user_id] = len(self.data[user_id]['received'])
                given[user_id] = len(self.data[user_id]['given'])
        
        # Calculate total scores and sort users
        users_with_stats = [
            (uid, received[uid], given[uid], received[uid] + given[uid])
            for uid in all_users
        ]
        
        return sorted(users_with_stats, key=lambda x: x[3], reverse=True)

class HloppyBot:
    """Main bot class handling Slack interactions and command processing"""
    
    def __init__(self):
        """Initialize the bot with required configurations"""
        load_dotenv()
        self._validate_env()
        
        self.app = App(token=os.environ["SLACK_BOT_TOKEN"])
        self.praise_data = PraiseData(app=self.app)
        
        # Register command handlers
        self.app.command("/hloppy")(self.handle_hloppy_command)
        self.app.command("/stats")(self.handle_stats_command)
        
        # Setup scheduler for leaderboard updates
        schedule.every(LEADERBOARD_SCHEDULE_DAYS).days.at(LEADERBOARD_POST_TIME).do(self.post_leaderboard)
        self.scheduler_thread = threading.Thread(target=self._run_schedule, daemon=True)

    def _validate_env(self):
        """Validate required environment variables"""
        required_vars = {
            "SLACK_BOT_TOKEN": "Bot token must be set",
            "SLACK_APP_TOKEN": "App token must be set and start with 'xapp-'",
            "SLACK_SIGNING_SECRET": "Signing secret must be set"
        }
        
        for var, message in required_vars.items():
            if not os.getenv(var):
                raise ValueError(f"{message}")
        
        if not os.environ["SLACK_APP_TOKEN"].startswith("xapp-"):
            raise ValueError("SLACK_APP_TOKEN must start with 'xapp-'")

    def _run_schedule(self):
        """Run the scheduler loop for periodic tasks"""
        while True:
            schedule.run_pending()
            time.sleep(60)

    def start(self):
        """Start the bot and socket mode handler"""
        try:
            logger.info("Starting Socket Mode handler...")
            handler = SocketModeHandler(
                app_token=os.environ["SLACK_APP_TOKEN"],
                app=self.app
            )
            self.scheduler_thread.start()
            handler.start()
        except Exception as e:
            logger.exception("Failed to start the bot")
            raise

    def handle_hloppy_command(self, ack, command, say):
        """Handle the /hloppy command for giving praises"""
        ack()
        
        user_id = command["user_id"]
        channel_id = command["channel_id"]
        command_text = command.get("text", "").strip()
        
        if not command_text:
            say("Please mention one or more people using @ and write your praise message.\nFormat: `/hloppy @Person1 @Person2 Your praise message`")
            return

        try:
            # Parse mentions and validate weekly limits
            mentions = self._parse_mentions(command_text)
            if not mentions:
                say("Could not find any valid users to praise. Please make sure you're mentioning active Slack users.")
                return

            weekly_count = self.praise_data.get_user_weekly_praises(user_id)
            remaining_praises = WEEKLY_PRAISE_LIMIT - weekly_count
            
            logger.info(f"User {user_id} has given {weekly_count} praises this week, {remaining_praises} remaining")
            
            if weekly_count >= WEEKLY_PRAISE_LIMIT:
                say(f"You've reached your weekly limit of {WEEKLY_PRAISE_LIMIT} praises. Please wait until next week to give more praises! (Current count: {weekly_count})")
                return

            if len(mentions) > remaining_praises:
                say(f"You can only give {remaining_praises} more praise(s) this week. Please mention fewer people or wait until next week.")
                return

            # Extract and validate praise message
            praise_message = self._extract_praise_message(command_text, mentions[-1]["end"])
            if not praise_message:
                say("Please provide a praise message after mentioning the people.\nFormat: `/hloppy @Person1 @Person2 Your praise message`")
                return

            # Process the praises
            self._process_praises(user_id, mentions, praise_message, channel_id, remaining_praises, say)

        except Exception as e:
            logger.exception("Error processing praise command")
            say("An error occurred while processing your praise. Please try again or contact support if the issue persists.")

    def _parse_mentions(self, text):
        """Parse and validate @ mentions from text"""
        mentions = []
        pos = 0
        
        while "@" in text[pos:]:
            mention_start = text.index("@", pos)
            mention = self._parse_single_mention(text, mention_start)
            
            if mention:
                mentions.append(mention)
                pos = mention["end"]
            else:
                pos = mention_start + 1
                
        return mentions

    def _parse_single_mention(self, text, start):
        """Parse a single @ mention and validate the user"""
        # Handle Slack's converted format (<@U1234ABCD>)
        if start > 0 and text[start-1:start+1] == "<@":
            end_bracket = text.find(">", start)
            if end_bracket != -1:
                user_id = text[start+1:end_bracket].strip()
                if self._verify_user(user_id):
                    return {
                        "id": user_id,
                        "mention": text[start-1:end_bracket+1],
                        "end": end_bracket + 1
                    }
        
        # Handle raw @ mentions
        next_space = text.find(" ", start)
        if next_space != -1:
            username = text[start+1:next_space].strip()
            user_id = self._find_user_by_name(username)
            if user_id:
                return {
                    "id": user_id,
                    "mention": f"<@{user_id}>",
                    "end": next_space
                }
        
        return None

    def _verify_user(self, user_id):
        """Verify that a user exists and is active in Slack"""
        try:
            response = self.app.client.users_info(user=user_id)
            return response["ok"] and not response["user"].get("deleted", False)
        except Exception:
            return False

    def _find_user_by_name(self, username):
        """Find a user ID by username, real name, or display name"""
        try:
            response = self.app.client.users_list()
            for user in response["members"]:
                if any([
                    user.get("name", "").lower() == username.lower(),
                    user.get("real_name", "").lower() == username.lower(),
                    user.get("profile", {}).get("display_name", "").lower() == username.lower(),
                    username.lower() in user.get("real_name", "").lower().split()
                ]):
                    return user["id"]
        except Exception:
            logger.exception("Error searching for user")
        return None

    def _extract_praise_message(self, text, last_mention_end):
        """Extract the praise message after the last mention"""
        return text[last_mention_end:].strip()

    def _process_praises(self, user_id, mentions, praise_message, channel_id, remaining_praises, say):
        """Process and record praises for mentioned users"""
        try:
            user_info = self.app.client.users_info(user=user_id)
            praises_given = 0
            
            for mention in mentions:
                target_user = mention["id"]
                if target_user == user_id:
                    continue  # Skip self-praise
                
                if praises_given >= remaining_praises:
                    say("Weekly praise limit reached. Some praises were not recorded.")
                    break
                    
                self.praise_data.add_praise(user_id, target_user, praise_message)
                praises_given += 1
                
                praise_count = self.praise_data.get_praise_count(target_user)
                blocks = self._create_praise_message_blocks(
                    user_id, mention["mention"], praise_message,
                    praise_count,
                    remaining_praises - praises_given
                )
                
                target_info = self.app.client.users_info(user=target_user)
                self.app.client.chat_postMessage(
                    channel=channel_id,
                    blocks=blocks,
                    text=f"🌟 {user_info['user']['real_name']} praised {target_info['user']['real_name']}: {praise_message}"
                )
                
        except Exception as e:
            logger.exception("Error processing praise")
            raise

    def _create_praise_message_blocks(self, user_id, target_mention, message, praise_count, remaining):
        """Create formatted message blocks for a praise notification"""
        return [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "🌟 *New Praise Alert!*"}
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*<@{user_id}>* praised *{target_mention}*:\n>{message}"}
            },
            {
                "type": "context",
                "elements": [{
                    "type": "mrkdwn",
                    "text": f"This is praise #{praise_count} for {target_mention} (You have {remaining} praise(s) remaining this week)"
                }]
            }
        ]

    def handle_stats_command(self, ack, command, say):
        """Handle the /stats command for displaying standings"""
        ack()
        message = self.praise_data.format_standings_message(app=self.app)
        blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "Below you can see the statistics of praises in our team.\nEach person's score is calculated as the sum of praises received and given.\n"
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*🏆 Current Standings:*"
                }
            }
        ]
        
        # Add each user's stats in a separate block
        sorted_users = self.praise_data.get_sorted_users()
        for user_id, received, given, total in sorted_users:
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"• <@{user_id}>: {received} received + {given} given = {total} total"
                }
            })
        
        if not sorted_users:
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "_No praises have been given yet. Be the first to praise someone using_ `/hloppy @username Your praise message`!"
                }
            })
        
        say(blocks=blocks, text=message)

    def post_leaderboard(self):
        """Post the leaderboard to the general channel"""
        try:
            response = self.app.client.conversations_list(types="public_channel")
            if response["ok"]:
                general_channel = next(
                    (channel for channel in response["channels"] if channel["name"] == "general"),
                    None
                )
                if general_channel:
                    message = self.praise_data.format_standings_message(app=self.app)
                    blocks = [
                        {
                            "type": "section",
                            "text": {
                                "type": "mrkdwn",
                                "text": "Below you can see the statistics of praises in our team.\nEach person's score is calculated as the sum of praises received and given.\n"
                            }
                        },
                        {
                            "type": "section",
                            "text": {
                                "type": "mrkdwn",
                                "text": "*🏆 Current Standings:*"
                            }
                        }
                    ]
                    
                    # Add each user's stats in a separate block
                    sorted_users = self.praise_data.get_sorted_users()
                    for user_id, received, given, total in sorted_users:
                        blocks.append({
                            "type": "section",
                            "text": {
                                "type": "mrkdwn",
                                "text": f"• <@{user_id}>: {received} received + {given} given = {total} total"
                            }
                        })
                    
                    if not sorted_users:
                        blocks.append({
                            "type": "section",
                            "text": {
                                "type": "mrkdwn",
                                "text": "_No praises have been given yet. Be the first to praise someone using_ `/hloppy @username Your praise message`!"
                            }
                        })
                    
                    self.app.client.chat_postMessage(
                        channel=general_channel["id"],
                        text=message,
                        blocks=blocks
                    )
        except Exception as e:
            logger.exception("Error posting leaderboard")

if __name__ == "__main__":
    bot = HloppyBot()
    bot.start() 