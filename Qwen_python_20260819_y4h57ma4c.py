from sqlalchemy import Column, Integer, String, DateTime, Text
from datetime import datetime
from .database import Base

class Meme(Base):
    __tablename__ = "memes"
    id = Column(Integer, primary_key=True, index=True)
    phash = Column(String, unique=True, index=True, nullable=True)
    source = Column(String, index=True)
    source_ref = Column(String)
    post_url = Column(String)
    section = Column(String, index=True)
    file_path = Column(String)
    compressed_path = Column(String, nullable=True)
    media_type = Column(String)
    text = Column(Text, nullable=True)
    popularity = Column(Integer, nullable=True)
    published_at = Column(DateTime, nullable=True)
    fetched_at = Column(DateTime, default=datetime.utcnow)
    status = Column(String, default="new") # new / approved / rejected