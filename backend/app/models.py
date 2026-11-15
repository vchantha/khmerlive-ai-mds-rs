from datetime import datetime
from sqlalchemy import String,Text,ForeignKey,DateTime,BigInteger,func
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
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),server_default=func.now())

class TranslationJob(Base):
    __tablename__="translation_jobs"
    id:Mapped[str]=mapped_column(String(36),primary_key=True)
    media_id:Mapped[str]=mapped_column(ForeignKey("media_assets.id"))
    source_lang:Mapped[str]=mapped_column(String(2))
    target_lang:Mapped[str]=mapped_column(String(2))
    status:Mapped[str]=mapped_column(String(32),default="queued")
    error:Mapped[str|None]=mapped_column(Text,nullable=True)
    transcript:Mapped[str|None]=mapped_column(Text,nullable=True)
    translation:Mapped[str|None]=mapped_column(Text,nullable=True)
    output_key:Mapped[str|None]=mapped_column(String(500),nullable=True)
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),server_default=func.now())
    updated_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),server_default=func.now(),onupdate=func.now())
