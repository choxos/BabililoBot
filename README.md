# BabililoBot

Enterprise-ready Telegram chatbot powered by OpenRouter LLM models.

## Features

- **Multiple Free LLM Models**: Choose from various free models including Gemma, Llama, Mistral, Qwen, DeepSeek, Phi, and Grok
- **Conversation Memory**: Maintains context across messages within a session
- **PostgreSQL Persistence**: All conversations and user data stored in database
- **Rate Limiting**: Token bucket algorithm to prevent abuse
- **Admin Commands**: Broadcast messages, ban/unban users, view statistics
- **Docker Ready**: Easy deployment with Docker Compose

## Quick Start

### Local Development

1. Clone the repository and install dependencies:
```bash
pip install -r requirements.txt
```

2. Copy `.env.example` to `.env` and fill in your credentials:
```bash
cp .env.example .env
```

3. Start PostgreSQL (or use Docker):
```bash
docker run -d --name babililo_postgres \
  -e POSTGRES_USER=babililo \
  -e POSTGRES_PASSWORD=babililo_secret \
  -e POSTGRES_DB=babililo_db \
  -p 5432:5432 \
  postgres:16-alpine
```

4. Run the bot:
```bash
python -m src.main
```

### Docker Deployment

1. Copy `.env.example` to `.env` and configure:
```bash
cp .env.example .env
# Edit .env with your tokens
```

2. Start with Docker Compose:
```bash
docker-compose up -d
```

3. View logs:
```bash
docker-compose logs -f bot
```

## Commands

### User Commands
| Command | Description |
|---------|-------------|
| `/start` | Start the bot and register |
| `/help` | Show available commands |
| `/model` | View or change AI model |
| `/clear` | Clear conversation history |
| `/usage` | View your usage statistics |

### Admin Commands
| Command | Description |
|---------|-------------|
| `/stats` | View bot statistics |
| `/broadcast <msg>` | Send message to all users |
| `/ban <user_id>` | Ban a user |
| `/unban <user_id>` | Unban a user |
| `/users` | List recent users |

## Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `TELEGRAM_BOT_TOKEN` | Telegram bot token | Required |
| `OPENROUTER_API_KEY` | OpenRouter API key | Required |
| `OPENROUTER_DEFAULT_MODEL` | Default LLM model | `google/gemma-3-27b-it:free` |
| `DATABASE_URL` | PostgreSQL connection URL | See .env.example |
| `ADMIN_USER_IDS` | JSON array of admin Telegram IDs | `[]` |
| `RATE_LIMIT_MESSAGES` | Messages allowed per window | `10` |
| `RATE_LIMIT_WINDOW_SECONDS` | Rate limit window in seconds | `60` |
| `CONVERSATION_CONTEXT_SIZE` | Messages to keep in context | `20` |
| `LOG_LEVEL` | Logging level | `INFO` |

## Available Models

The bot supports these free models from OpenRouter:

- `google/gemma-3-27b-it:free` - Gemma 3 27B
- `google/gemma-3-12b-it:free` - Gemma 3 12B
- `meta-llama/llama-4-scout:free` - Llama 4 Scout
- `meta-llama/llama-4-maverick:free` - Llama 4 Maverick
- `mistralai/mistral-small-3.1-24b-instruct:free` - Mistral Small 3.1
- `qwen/qwen3-32b:free` - Qwen 3 32B
- `qwen/qwen3-14b:free` - Qwen 3 14B
- `deepseek/deepseek-r1-0528:free` - DeepSeek R1
- `microsoft/phi-4:free` - Phi 4
- `x-ai/grok-4.1-fast:free` - Grok 4.1 Fast

## Database Migrations

Run migrations with Alembic:
```bash
alembic upgrade head
```

Create new migration:
```bash
alembic revision --autogenerate -m "description"
```

## License

MIT
