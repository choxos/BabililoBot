# BabililoBot

Enterprise-ready Telegram chatbot powered by OpenRouter LLM models with 10+ features.

## Features

### Core
- **Multiple Free LLM Models**: Gemma, Llama, Mistral, Qwen, DeepSeek, Phi, Grok
- **Streaming Responses**: Real-time text with typing effect
- **Conversation Memory**: Context-aware conversations
- **PostgreSQL Persistence**: Enterprise-grade data storage

### New Features
- **🔍 Inline Mode**: Use `@babililobot` in any chat
- **📄 Export**: Download responses as PDF/TXT/Markdown
- **🎤 Voice**: Send voice messages, get audio replies
- **🎭 Personas**: Custom AI personalities (Coder, Writer, Tutor, etc.)
- **⭐ Favorites**: Save and recall best responses
- **👥 Groups**: Mention bot in group chats
- **🌐 Web Search**: Real-time internet search
- **📚 Documents**: Upload PDF/DOCX for Q&A
- **🎨 Images**: Generate images with `/imagine`
- **🛡️ Admin Tools**: Ban users, broadcast messages, stats

## Quick Start

### Docker Deployment (Recommended)

```bash
git clone https://github.com/choxos/BabililoBot.git
cd BabililoBot

# Create .env file
cat > .env << 'EOF'
TELEGRAM_BOT_TOKEN=your_token_here
OPENROUTER_API_KEY=your_api_key_here
OPENROUTER_DEFAULT_MODEL=google/gemma-3-27b-it:free
DATABASE_URL=postgresql+asyncpg://babililo:babililo_secret@postgres:5432/babililo_db
ADMIN_USER_IDS=[your_telegram_id]
EOF

# Start
docker-compose up -d

# View logs
docker-compose logs -f bot
```

### Local Development

```bash
pip install -r requirements.txt

# Use SQLite for local testing
export DATABASE_URL=sqlite+aiosqlite:///babililo.db

python -m src.main
```

## Commands

| Command | Description |
|---------|-------------|
| `/start` | Start the bot |
| `/help` | Show all commands |
| `/model` | Change AI model |
| `/persona` | Set AI personality |
| `/search <query>` | Web search |
| `/imagine <prompt>` | Generate image |
| `/voice on/off` | Toggle voice replies |
| `/doc` | Document Q&A info |
| `/export` | Export conversation |
| `/favorites` | View saved responses |
| `/clear` | Clear history |
| `/usage` | Your statistics |

### Admin Commands
| Command | Description |
|---------|-------------|
| `/stats` | Bot statistics |
| `/broadcast <msg>` | Message all users |
| `/ban <user_id>` | Ban user |
| `/unban <user_id>` | Unban user |
| `/users` | List users |
| `/groupsettings` | Group settings |

## Inline Mode

Type `@babililobot your question` in any chat to get AI responses!

## Group Chats

- Mention `@babililobot` or reply to the bot
- Use `/groupsettings` to configure (admin only)

## Configuration

| Variable | Description |
|----------|-------------|
| `TELEGRAM_BOT_TOKEN` | Bot token from BotFather |
| `OPENROUTER_API_KEY` | OpenRouter API key |
| `DATABASE_URL` | PostgreSQL connection URL |
| `ADMIN_USER_IDS` | JSON array of admin IDs |
| `RATE_LIMIT_MESSAGES` | Messages per window (default: 10) |
| `CONVERSATION_CONTEXT_SIZE` | Context messages (default: 20) |

## Architecture

```
src/
├── bot/handlers/     # Telegram handlers
│   ├── chat.py       # Main chat with streaming
│   ├── commands.py   # User commands
│   ├── admin.py      # Admin commands
│   ├── inline.py     # Inline queries
│   ├── voice.py      # Voice messages
│   ├── documents.py  # Document Q&A
│   ├── groups.py     # Group chat
│   └── export.py     # PDF/TXT export
├── services/         # Business logic
│   ├── openrouter.py # LLM API client
│   ├── conversation.py
│   ├── web_search.py
│   └── image_gen.py
├── database/         # Persistence
│   ├── models.py
│   └── repository.py
└── main.py           # Entry point
```

## License

MIT
