General description:
This program is a bot that automatically rewrites news articles from RSS feeds of gaming web publications. It uses the Gemini API to generate news texts in a specific, fan-style format as defined in a customizable prompt. After rewriting, the bot sends the generated news, including a link to the original source, directly to a specified Telegram chat or channel.

Setup Instructions:

1. Download and Extract
	- Download the project archive.
	- Extract all files to your desired directory.

2. Install Dependencies
	- Open a terminal in the project folder.
	- Run the following command to install required Python packages:
	  pip install -r requirements.txt

3. Configure Settings
	- Place your custom prompt in a separate file (e.g., prompt.txt) in the project folder. See the section "Custom Prompt Format" below for details.
	- Edit the `.env` configuration file to add your Gemini API key and Telegram bot token.

4. Run the Bot
	- Start the bot with:
	  python main.py
	- The bot will begin fetching news from RSS feeds, rewriting them, and posting to Telegram.

Note:
Make sure you have Python 3.8 or newer installed.
Refer to the README and comments in the code for further customization options.

---

Configuration (.env file):

Create a file named `.env` in the project root and add the following variables:

```
GEMINI_API_KEY=your_gemini_api_key_here
TELEGRAM_TOKEN=your_telegram_bot_token_here
TELEGRAM_CHAT_ID=your_telegram_chat_id_here
```

Replace the values with your actual Gemini API key, Telegram bot token, and Telegram chat or channel ID.
