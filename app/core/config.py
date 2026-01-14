from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "dev"
    database_url: str

    whatsapp_verify_token: str
    whatsapp_access_token: str
    whatsapp_phone_number_id: str

    stripe_secret_key: str
    stripe_webhook_secret: str
    stripe_deposit_amount_pence: int = 5000

    fresha_booking_url: str

    ai_provider: str = "openai"
    openai_api_key: str | None = None


settings = Settings()
