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
    inference_device:str="cpu"
    auth_session_secret:str="replace_with_generated_session_secret"
    auth_public_base_url:str="http://localhost:8080"
    auth_cookie_secure:bool=False
    google_client_id:str=""
    google_client_secret:str=""
    facebook_client_id:str=""
    facebook_client_secret:str=""
    whisper_model_path:str="/models/asr"
    translation_model_path:str="/models/mt"
    max_upload_mb:int=1024
settings=Settings()
