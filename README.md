# Telegram Movie Search Bot

This is a Telegram bot built with **Pyrogram** and **MongoDB**. It can:

- Save posts from a specific channel
- Search movies by title
- Show results with posters (forwards original channel message)
- Filter results (year, language, type)
- Collect feedback from users
- Broadcast messages to all users
- Track basic stats (users, feedback, movies)
- Let users vote if a movie is found or not
- Admin commands to delete movies or enable/disable notify

## Deployment (Render / Koyeb / Railway etc.)

### 1. Clone or Upload the Project
Upload all files to your Render service (or GitHub if using autodeploy).

### 2. Set Environment Variables

| Key             | Value Description                      |
|------------------|-----------------------------------------|
| `API_ID`        | Telegram API ID from [my.telegram.org](https://my.telegram.org) |
| `API_HASH`      | Telegram API Hash from my.telegram.org |
| `BOT_TOKEN`     | Your bot token from BotFather           |
| `DATABASE_URL`  | MongoDB connection string (e.g., from MongoDB Atlas) |
| `CHANNEL_ID`    | Channel ID to save posts from (must be integer, e.g., `-1001234567890`) |
| `ADMIN_ID`      | Your Telegram User ID                   |
| `RESULTS_COUNT` | (Optional) Number of search results to show (default: 5) |
| `UPDATE_CHANNEL`| (Optional) Your channel link for "Update Channel" button |
| `START_PIC`     | (Optional) URL of the start photo       |

### 3. Install Dependencies

```bash
pip install -r requirements.txt
