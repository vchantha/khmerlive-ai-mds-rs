from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config=SettingsConfigDict(env_file=".env",extra="ignore")
    database_url:str="postgresql+psycopg://khmerlive:khmerlive@localhost:5432/khmerlive"
    redis_url:str="redis://localhost:6379/0"
    minio_endpoint:str="localhost:9000"
    minio_bucket:str="khmerlive"
    minio_access_key:str="khmerlive"
    minio_secret_key:str="khmerlive"
    api_key:str="development_only_key"
    model_mode:str="demo"
    whisper_model_path:str="/models/asr"
    translation_model_path:str="/models/mt"
    max_upload_mb:int=100
settings=Settings()
