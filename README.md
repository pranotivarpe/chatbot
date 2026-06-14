# 🤖 AI Chatbot — Flask + OpenAI

![Python](https://img.shields.io/badge/Python-3.8+-3776AB?style=flat-square&logo=python&logoColor=white)
![Flask](https://img.shields.io/badge/Flask-2.x-000000?style=flat-square&logo=flask&logoColor=white)
![OpenAI](https://img.shields.io/badge/OpenAI-GPT--4o--mini-412991?style=flat-square&logo=openai&logoColor=white)
![MySQL](https://img.shields.io/badge/MySQL-Database-4479A1?style=flat-square&logo=mysql&logoColor=white)

A conversational AI chatbot built with **Flask** and **OpenAI GPT-4o-mini**. The bot maintains full conversation history in a MySQL database, enabling context-aware multi-turn dialogue, and supports searching through past conversations.

---

## Features

- 💬 **Multi-turn Conversations** — Full chat history sent as context to the LLM for coherent dialogue
- 💾 **Persistent History** — All conversations stored in MySQL and loaded on startup
- 🔍 **Search** — Filter through past messages by keyword
- 😊 **Emoji Responses** — Bot is configured to add expressive emojis to replies
- 🌐 **Web Interface** — Clean HTML/CSS chat UI rendered with Jinja2 templates

---

## Tech Stack

| Technology | Purpose |
|-----------|---------|
| Python + Flask | Web framework |
| OpenAI GPT-4o-mini | Language model |
| MySQL | Chat history storage |
| python-dotenv | Environment variable management |
| Jinja2 | HTML templating |

---

## Project Structure

```
chatbot/
├── app.py              # Flask app, routes, and OpenAI integration
├── templates/
│   └── index.html      # Chat UI template
├── static/             # CSS and JS assets
├── .env                # API keys (not committed)
└── requirements.txt
```

---

## Getting Started

### Prerequisites

- Python 3.8+
- MySQL server running
- OpenAI API key

### Setup

```bash
# Clone the repository
git clone https://github.com/pranotivarpe/chatbot.git
cd chatbot

# Create virtual environment
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate

# Install dependencies
pip install flask openai python-dotenv mysql-connector-python
```

Create a `.env` file:

```env
OPENAI_API_KEY=your-openai-api-key
DB_HOST=localhost
DB_USER=root
DB_PASSWORD=your-db-password
DB_NAME=chatbot_db
```

Create the MySQL table:

```sql
CREATE DATABASE chatbot_db;
USE chatbot_db;
CREATE TABLE chat_history (
  id INT AUTO_INCREMENT PRIMARY KEY,
  user_message TEXT NOT NULL,
  bot_response TEXT NOT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

```bash
python app.py
```

Visit `http://localhost:5000`