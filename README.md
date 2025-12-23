# Cash Flow Intelligence MVP

A Multi-Tenant SaaS Backend that connects to Xero, analyzes financial data, calculates Cash Runway, and provides AI-powered insights.

## 🚀 Features

- **User Authentication** - JWT-based secure authentication
- **Xero Integration** - OAuth 2.0 connection to Xero accounting
- **Cash Flow Analysis** - Calculate burn rate and runway
- **AI Insights** - GPT-4o powered financial summaries
- **Multi-Tenant** - Secure data isolation per organization

## 📋 Prerequisites

- Python 3.10+
- PostgreSQL 14+
- Xero Developer Account
- OpenAI API Key

## 🛠️ Installation

### 1. Clone the repository

```bash
cd Neura-MVP
```

### 2. Create virtual environment

```bash
# Windows
python -m venv venv
venv\Scripts\activate

# macOS/Linux
python3 -m venv venv
source venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Set up environment variables

```bash
# Copy the example file
cp env.example .env

# Edit .env with your values
# Required: DATABASE_URL, JWT_SECRET_KEY, XERO_CLIENT_ID, XERO_CLIENT_SECRET, OPENAI_API_KEY
```

### 5. Set up the database

```bash
# Create PostgreSQL database
createdb cashflow_db

# Run migrations (after Milestone 2)
alembic upgrade head
```

### 6. Run the application

```bash
# Development mode with auto-reload
uvicorn app.main:app --reload

# Or using Python directly
python -m app.main
```

The API will be available at `http://localhost:8000`

## 📚 API Documentation

When running in debug mode, interactive docs are available at:

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

## 🏗️ Project Structure

```
Neura-MVP/
├── app/
│   ├── __init__.py          # Package init
│   ├── main.py              # FastAPI entry point
│   ├── config.py            # Settings & configuration
│   ├── database/            # Database connection & base models
│   ├── models/              # SQLAlchemy models
│   ├── schemas/             # Pydantic schemas
│   ├── auth/                # Authentication logic
│   ├── integrations/        # External integrations (Xero)
│   ├── api/                 # API endpoints
│   ├── services/            # Business logic
│   └── prompts/             # AI prompt templates
├── alembic/                 # Database migrations
├── tests/                   # Test files
├── requirements.txt         # Python dependencies
├── .env.example             # Environment template
└── README.md                # This file
```

## 🔑 API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | API information |
| GET | `/health` | Health check |
| POST | `/auth/signup` | Register new user |
| POST | `/auth/login` | Login, get tokens |
| GET | `/integrations/xero/connect` | Start Xero OAuth |
| GET | `/integrations/xero/callback` | OAuth callback |
| GET | `/api/dashboard/cash-runway` | Get cash flow metrics |
| GET | `/api/dashboard/trends` | Get historical trends |

## 🧪 Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=app

# Run specific test file
pytest tests/test_auth.py
```

## 📝 Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `DATABASE_URL` | PostgreSQL connection string | ✅ |
| `JWT_SECRET_KEY` | Secret for JWT signing | ✅ |
| `XERO_CLIENT_ID` | Xero app client ID | ✅ |
| `XERO_CLIENT_SECRET` | Xero app client secret | ✅ |
| `OPENAI_API_KEY` | OpenAI API key | ✅ |
| `DEBUG` | Enable debug mode | ❌ |
| `CACHE_TTL_MINUTES` | Cache duration (default: 15) | ❌ |

## 🔒 Security Notes

- Never commit `.env` file to version control
- Use strong, unique values for `SECRET_KEY` and `JWT_SECRET_KEY`
- In production, disable debug mode and API docs
- Xero tokens are sensitive - encrypt in production


