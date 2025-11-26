from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    # Database settings
    db_host: str
    db_port: int
    db_name: str
    db_user: str
    db_pass: str
    
    # JWT settings
    secret_key: str
    jwt_algorithm: str = "HS256"
    jwt_expiration_hours: int = 24
    
    # Crypto payment settings
    eth_rpc_url: str
    usdt_contract_address: str
    wallet_address: str
    min_usdt_payment: float = 1.0  # Minimum payment in USDT
    
    # Admin credentials
    admin_username: str
    admin_password: str
    
    # Stripe settings
    stripe_secret_key: str
    stripe_public_key: str
    stripe_webhook_secret: str
    
    # Coinbase Commerce settings
    coinbase_api_key: str
    coinbase_webhook_secret: str
    
    # Application settings
    app_name: str = "Word to PDF Converter"
    app_url: str = "http://localhost:8000"
    
    # Payment settings
    price_per_page: float = 0.10  # Price per page in USD
    free_page_limit: int = 50  # Number of free pages
    
    # File storage
    upload_folder: str = "uploads"
    pdf_folder: str = "pdfs"

    class Config:
        env_file = ".env"


settings = Settings()
