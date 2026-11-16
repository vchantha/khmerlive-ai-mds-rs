from datetime import datetime
from sqlalchemy import String,Text,ForeignKey,DateTime,BigInteger,func,UniqueConstraint
from sqlalchemy.orm import Mapped,mapped_column
from app.db import Base

class MediaAsset(Base):
    __tablename__="media_assets"
    id:Mapped[str]=mapped_column(String(36),primary_key=True)
    filename:Mapped[str]=mapped_column(String(255))
    object_key:Mapped[str]=mapped_column(String(500),unique=True)
    content_type:Mapped[str]=mapped_column(String(100))
    size_bytes:Mapped[int]=mapped_column(BigInteger)
    sha256:Mapped[str]=mapped_column(String(64))
    owner_user_id:Mapped[str|None]=mapped_column(ForeignKey("app_users.id"),nullable=True)
    source_url:Mapped[str|None]=mapped_column(Text,nullable=True)
    source_kind:Mapped[str]=mapped_column(String(16),default="upload",server_default="upload")
    capture_seconds:Mapped[int|None]=mapped_column(nullable=True)
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),server_default=func.now())
    # Soft delete: set when moved to the Trash; only an admin purge removes the row and files.
    deleted_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True),nullable=True,index=True)
    deleted_by:Mapped[str|None]=mapped_column(String(200),nullable=True)

class TranslationJob(Base):
    __tablename__="translation_jobs"
    id:Mapped[str]=mapped_column(String(36),primary_key=True)
    media_id:Mapped[str]=mapped_column(ForeignKey("media_assets.id"))
    source_lang:Mapped[str]=mapped_column(String(2))
    target_lang:Mapped[str]=mapped_column(String(2))
    status:Mapped[str]=mapped_column(String(32),default="queued")
    progress:Mapped[int]=mapped_column(default=0)
    stage:Mapped[str|None]=mapped_column(String(64),nullable=True)
    cancel_requested:Mapped[bool]=mapped_column(default=False,server_default="false")
    error:Mapped[str|None]=mapped_column(Text,nullable=True)
    transcript:Mapped[str|None]=mapped_column(Text,nullable=True)
    translation:Mapped[str|None]=mapped_column(Text,nullable=True)
    output_key:Mapped[str|None]=mapped_column(String(500),nullable=True)
    subtitle_key:Mapped[str|None]=mapped_column(String(500),nullable=True)
    processing_mode:Mapped[str]=mapped_column(String(32),default="demo",server_default="demo")
    # JSON: seconds per pipeline stage, devices and engines used (performance tuning).
    timings:Mapped[str|None]=mapped_column(Text,nullable=True)
    owner_user_id:Mapped[str|None]=mapped_column(ForeignKey("app_users.id"),nullable=True)
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),server_default=func.now())
    updated_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),server_default=func.now(),onupdate=func.now())
    deleted_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True),nullable=True,index=True)
    deleted_by:Mapped[str|None]=mapped_column(String(200),nullable=True)


class AppUser(Base):
    __tablename__="app_users"
    id:Mapped[str]=mapped_column(String(36),primary_key=True)
    display_name:Mapped[str]=mapped_column(String(200))
    email:Mapped[str|None]=mapped_column(String(320),nullable=True)
    avatar_url:Mapped[str|None]=mapped_column(String(1000),nullable=True)
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),server_default=func.now())

class SocialIdentity(Base):
    __tablename__="social_identities"
    __table_args__=(UniqueConstraint("provider","subject",name="uq_social_provider_subject"),UniqueConstraint("user_id","provider",name="uq_user_provider"))
    id:Mapped[str]=mapped_column(String(36),primary_key=True)
    user_id:Mapped[str]=mapped_column(ForeignKey("app_users.id",ondelete="CASCADE"))
    provider:Mapped[str]=mapped_column(String(30))
    subject:Mapped[str]=mapped_column(String(255))
    display_name:Mapped[str|None]=mapped_column(String(200),nullable=True)
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),server_default=func.now())
