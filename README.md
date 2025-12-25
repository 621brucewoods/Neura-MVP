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

Create a `.env` file in the project root with the following variables:

```bash
# Database
DATABASE_URL=postgresql+asyncpg://postgres:password@localhost:5432/cashflow_db

# JWT Authentication
JWT_SECRET_KEY=your-secret-key-here

# Xero Integration
XERO_CLIENT_ID=your-xero-client-id
XERO_CLIENT_SECRET=your-xero-client-secret
XERO_REDIRECT_URI=http://localhost:8000/integrations/xero/callback

# OpenAI (optional for MVP)
OPENAI_API_KEY=your-openai-api-key

# Application Settings
DEBUG=true
ENVIRONMENT=development
```

### 5. Set up the database

```bash
# Create PostgreSQL database
createdb cashflow_db

# Run database migrations
cd Neura-MVP
alembic upgrade head
```

### 6. Run the application

```bash
# Development mode with auto-reload
uvicorn app.main:app --reload

# Or using uvicorn directly
uvicorn app.main:app --host 0.0.0.0 --port 8000
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
│   ├── auth/                # Authentication logic
│   ├── insights/            # Financial insights & calculations
│   ├── integrations/       # External integrations (Xero)
│   └── alembic/             # Database migrations
├── requirements.txt         # Python dependencies
└── README.md                # This file
```

## 🔑 API Endpoints

### Authentication
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/auth/signup` | Register new user |
| POST | `/auth/login` | Login, get tokens |
| POST | `/auth/refresh` | Refresh access token |
| POST | `/auth/logout` | Logout and revoke tokens |
| POST | `/auth/change-password` | Change user password |
| GET | `/auth/me` | Get current user profile |

### Xero Integration
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/integrations/xero/connect` | Start Xero OAuth connection |
| GET | `/integrations/xero/callback` | Handle Xero OAuth callback |
| GET | `/integrations/xero/status` | Check Xero connection status |
| POST | `/integrations/xero/disconnect` | Disconnect Xero integration |
| POST | `/integrations/xero/refresh` | Manually refresh Xero tokens |
| GET | `/integrations/xero/sync` | Sync financial data from Xero |

### Insights
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/insights` | Get all financial insights (cash runway, trends, leading indicators) |

### System
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | API information |
| GET | `/health` | Health check |

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

| Variable | Description | Required | Default |
|----------|-------------|----------|---------|
| `DATABASE_URL` | PostgreSQL connection string | ✅ | - |
| `JWT_SECRET_KEY` | Secret for JWT signing | ✅ | - |
| `XERO_CLIENT_ID` | Xero app client ID | ✅ | - |
| `XERO_CLIENT_SECRET` | Xero app client secret | ✅ | - |
| `XERO_REDIRECT_URI` | Xero OAuth redirect URI | ❌ | `http://localhost:8000/integrations/xero/callback` |
| `OPENAI_API_KEY` | OpenAI API key | ❌ | - |
| `DEBUG` | Enable debug mode | ❌ | `false` |
| `CACHE_TTL_MINUTES` | Cache duration in minutes | ❌ | `15` |
| `CORS_ORIGINS` | Allowed CORS origins (comma-separated) | ❌ | `http://localhost:3000,http://localhost:5173` |

## 🔒 Security Notes

- Never commit `.env` file to version control
- Use strong, unique values for `SECRET_KEY` and `JWT_SECRET_KEY`
- In production, disable debug mode and API docs
- Xero tokens are sensitive - encrypt in production


