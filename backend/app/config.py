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
    khmer_tts_model_path:str="/models/tts"
    enable_khmer_dubbing:bool=True
    llm_postedit_enabled:bool=False
    llm_provider:str="ollama"
    llm_base_url:str="http://ollama:11434/v1"
    llm_model:str="qwen3:4b-instruct"
    llm_timeout_seconds:float=180.0
    llm_max_tokens:int=256
    llm_fail_open:bool=True
    llm_total_budget_seconds:float=900.0
    vllm_postedit_enabled:bool=False
    vllm_base_url:str="http://vllm:8000/v1"
    vllm_model:str="khmerlive-postedit"
    vllm_timeout_seconds:float=60.0
    vllm_max_tokens:int=256
    vllm_fail_open:bool=True
    max_upload_mb:int=1024
    max_video_duration_seconds:int=600
    stream_url_allow_users:bool=False
    # YouTube links are resolved with yt-dlp (single public videos only).
    youtube_enabled:bool=True
    # Hard Celery limit per job; a soft limit fires 5 min earlier so the job is marked failed cleanly.
    job_time_limit_seconds:int=3600
    # ---- Performance ----
    # Jobs processed in parallel by one worker container (Celery prefork processes).
    worker_concurrency:int=1
    # Recycle the worker process after N jobs (0 = never). GPU setups use 1 so every job
    # starts with empty GPU memory (models reload in a few seconds).
    worker_max_tasks_per_child:int=0
    # CPU threads per job for Whisper/M2M100/TTS. 0 = auto: all cores / WORKER_CONCURRENCY.
    cpu_threads:int=0
    # Deprecated alias of CPU_THREADS kept for existing .env files.
    asr_cpu_threads:int=0
    # Per-stage device. Empty = INFERENCE_DEVICE. Values: cpu | cuda
    asr_device:str=""
    mt_device:str=""
    tts_device:str=""
    # CTranslate2 precision for Whisper. Empty = auto (cuda: int8_float16, cpu: int8).
    asr_compute_type:str=""
    # Translation engine: auto uses the CTranslate2 model at MT_CT2_PATH when present.
    mt_engine:str="auto"
    mt_ct2_path:str="/models/mt-ct2"
    mt_beam_size:int=4
    # Parallel LLM post-edit requests (match OLLAMA_NUM_PARALLEL). 1 = sequential.
    llm_concurrency:int=1
    # Drop Whisper from GPU memory after each use (~1 s reload) so TTS/LLM fit on small GPUs.
    asr_release_after_use:bool=False
    # Free the post-edit LLM from GPU memory before GPU speech recognition (small GPUs).
    llm_unload_before_gpu_asr:bool=False

    def device_for(self,stage:str)->str:
        return (getattr(self,stage+"_device","") or self.inference_device or "cpu").strip().lower()

    def threads_per_job(self)->int:
        import os
        if self.cpu_threads>0:return self.cpu_threads
        if self.asr_cpu_threads>0:return self.asr_cpu_threads
        try:cores=len(os.sched_getaffinity(0))
        except (AttributeError,OSError):cores=os.cpu_count() or 4
        return max(1,cores//max(1,self.worker_concurrency))
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
