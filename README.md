# Tattoo Booking Bot

A WhatsApp-based tattoo booking bot built with FastAPI, integrating with Stripe for payments and Fresha for booking management.

## Features

- WhatsApp webhook integration for receiving messages
- Stripe payment processing for deposits
- AI-powered conversation handling
- PostgreSQL database for data persistence

## Security Notice

⚠️ **IMPORTANT**: This repository is configured for public use. All sensitive credentials are stored in environment variables and are **NOT** committed to the repository.

- Never commit `.env` files or any files containing secrets
- All API keys, tokens, and passwords are loaded from environment variables
- See `.env.example` for required environment variables

## Setup

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd tattoo-booking-bot
   ```

2. **Create environment file**
   ```bash
   cp .env.example .env
   ```
   Then edit `.env` with your actual credentials.

3. **Run with Docker Compose**
   ```bash
   docker compose up --build
   ```

   The API will be available at `http://localhost:8000`

## Environment Variables

See `.env.example` for all required environment variables. Key variables include:

- `DATABASE_URL`: PostgreSQL connection string
- `WHATSAPP_VERIFY_TOKEN`: Meta WhatsApp webhook verification token
- `WHATSAPP_ACCESS_TOKEN`: Meta WhatsApp API access token
- `STRIPE_SECRET_KEY`: Stripe secret key
- `STRIPE_WEBHOOK_SECRET`: Stripe webhook signing secret
- `OPENAI_API_KEY`: OpenAI API key (if using OpenAI)

## Development

The application uses:
- FastAPI for the web framework
- SQLAlchemy for database ORM
- PostgreSQL for the database
- Docker Compose for containerization

## API Endpoints

- `GET /health` - Health check endpoint
- `GET /webhooks/whatsapp` - WhatsApp webhook verification
- `POST /webhooks/whatsapp` - WhatsApp inbound message handler
