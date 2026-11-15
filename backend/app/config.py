from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import model_validator
import hashlib

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
    github_client_id:str=""
    github_client_secret:str=""
    whisper_model_path:str="/models/asr"
    translation_model_path:str="/models/mt"
    max_upload_mb:int=1024
    max_video_duration_seconds:int=600
    stream_url_allow_users:bool=False
    # Hard Celery limit per job; a soft limit fires 5 min earlier so the job is marked failed cleanly.
    job_time_limit_seconds:int=3600
    # CTranslate2 threads for Whisper on CPU (0 = library default, which uses only 4 cores).
    asr_cpu_threads:int=0
    @model_validator(mode="after")
    def protect_session_secret(self):
        if self.auth_session_secret in ("replace_with_generated_session_secret","change_this_auth_session_secret"):
            # Older installations have no AUTH_SESSION_SECRET yet. Derive a stable
            # fallback from their private random API key; set a dedicated key in .env.
            self.auth_session_secret=hashlib.sha256((self.api_key+"|khmerlive-auth-session-v1").encode()).hexdigest()
        if len(self.auth_session_secret)<32:
            raise ValueError("AUTH_SESSION_SECRET must contain at least 32 characters")
        return self
settings=Settings()
