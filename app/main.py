import logging
import logging.config
from pathlib import Path
from typing import List, Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Form, BackgroundTasks, HTTPException, Depends
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import desc
import yaml
import os

# Импорт локальных модулей
from .database import engine, Base, get_db, init_db
from . import models
from .models import Meme, RunLog, Setting
from .config_loader import load_config
from .parsers.vk_parser import VKParser
from .parsers.pikabu_parser import PikabuParser
from .parsers.joyreactor_parser import JoyReactorParser
from .parsers.dvach_parser import DvachParser

from .services.collector import Collector
from .services.compressor import ImageCompressor
from .services.mailer import MailerService
from .services.scheduler import SchedulerService

# --- Конфигурация логирования ---
LOG_DIR = Path("data")
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / "app.log"

# Простая конфигурация, если файл logging.conf отсутствует
if not Path("logging.conf").exists():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler(LOG_FILE, encoding='utf-8'),
            logging.StreamHandler()
        ]
    )
else:
    logging.config.fileConfig("logging.conf", disable_existing_loggers=False)

logger = logging.getLogger(__name__)

# --- Глобальные переменные ---
config = {}
scheduler_service = None
collector_service = None
compressor_service = None
mailer_service = None

# --- Инициализация при старте приложения ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    global config, scheduler_service, collector_service, compressor_service, mailer_service
    
    logger.info("Starting MemoSbor application...")
    
    # 1. Загрузка конфига
    config = load_config()
    logger.info("Configuration loaded successfully.")
    
    # 2. Инициализация БД
    init_db()
    logger.info("Database initialized.")
    
    # 3. Инициализация сервисов
    compress_cfg = config.get("compress", {})
    compressor_service = ImageCompressor(
        target_kb=compress_cfg.get("target_kb", 150),
        min_quality=compress_cfg.get("min_quality", 60),
        min_dimension=compress_cfg.get("min_dimension", 800)
    )
    
    if config.get("mail", {}).get("enabled", False):
        mailer_service = MailerService(config.get("mail", {}))
        logger.info("Mailer service initialized.")
    else:
        logger.info("Mailer service disabled in config.")
        
    collector_service = Collector(config, db_func=get_db)
    
    # 4. Запуск планировщика
    scheduler_service = SchedulerService()
    schedule_times = config.get("schedule", [])
    if schedule_times:
        # Передаем функцию сбора как задачу
        scheduler_service.add_job(run_collection_task, schedule_times)
        logger.info(f"Scheduled collection tasks: {schedule_times}")
    else:
        logger.info("No scheduled tasks configured.")

    yield
    
    # Shutdown
    logger.info("Shutting down application...")
    if scheduler_service:
        scheduler_service.shutdown()

# --- Фоновая задача для планировщика ---
def run_collection_task():
    """Обертка для запуска коллектора из планировщика (синхронный вызов)."""
    try:
        logger.info("Scheduler triggered collection task.")
        # Создаем новую сессию БД для фонового процесса
        from .database import SessionLocal
        db = SessionLocal()
        try:
            collector = Collector(config, db_func=lambda: db)
            stats = collector.run_all()
            logger.info(f"Collection finished: {stats}")
        finally:
            db.close()
    except Exception as e:
        logger.error(f"Error in scheduled collection task: {e}", exc_info=True)

# --- Создание приложения FastAPI ---
app = FastAPI(title="МемоСбор", description="Парсер мемов с модерацией", lifespan=lifespan)

# Статика и шаблоны
BASE_DIR = Path(__file__).resolve().parent
static_path = BASE_DIR / "static"
templates_path = BASE_DIR / "templates"

# Создаем папки, если нет
static_path.mkdir(exist_ok=True)
templates_path.mkdir(exist_ok=True)

app.mount("/static", StaticFiles(directory=str(static_path)), name="static")
templates = Jinja2Templates(directory=str(templates_path))

CONFIG_PATH = "config.yaml"

def get_collector():
    if not collector_service:
        raise HTTPException(status_code=503, detail="Collector service not initialized")
    return collector_service

# --- Роуты (Web Interface) ---

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, db: Session = Depends(get_db)):
    """Главная страница - Галерея новых мемов."""
    memes = db.query(Meme).filter(Meme.status == "new").order_by(desc(Meme.fetched_at)).limit(50).all()
    
    # Статистика
    total_new = db.query(Meme).filter(Meme.status == "new").count()
    total_approved = db.query(Meme).filter(Meme.status == "approved").count()
    total_rejected = db.query(Meme).filter(Meme.status == "rejected").count()
    
    last_run = db.query(RunLog).order_by(desc(RunLog.id)).first()
    
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "memes": memes,
        "stats": {"new": total_new, "approved": total_approved, "rejected": total_rejected},
        "last_run": last_run
    })

@app.get("/approved", response_class=HTMLResponse)
async def approved_gallery(request: Request, db: Session = Depends(get_db)):
    """Страница одобренных мемов (для сжатия и отправки)."""
    memes = db.query(Meme).filter(Meme.status == "approved").order_by(desc(Meme.fetched_at)).all()
    return templates.TemplateResponse("approved.html", {
        "request": request,
        "memes": memes
    })

@app.get("/logs", response_class=HTMLResponse)
async def logs_page(request: Request, db: Session = Depends(get_db)):
    """Страница логов запусков."""
    logs = db.query(RunLog).order_by(desc(RunLog.id)).limit(20).all()
    return templates.TemplateResponse("logs.html", {
        "request": request,
        "logs": logs
    })

@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    """Страница настроек (конфиг)."""
    return templates.TemplateResponse("settings.html", {
        "request": request,
        "config": config
    })

# --- API Роуты (Actions) ---

@app.post("/api/collect")
async def trigger_collect(background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """Запуск сбора мемов вручную."""
    logger.info("Manual collection triggered via API.")
    
    # Запускаем в фоне, чтобы не блокировать UI
    background_tasks.add_task(run_collection_task)
    
    return {"status": "started", "message": "Сбор мемов запущен в фоновом режиме."}

@app.post("/api/meme/{meme_id}/approve")
async def approve_meme(meme_id: int, db: Session = Depends(get_db)):
    meme = db.query(Meme).filter(Meme.id == meme_id).first()
    if not meme:
        raise HTTPException(status_code=404, detail="Meme not found")
    
    meme.status = "approved"
    db.commit()
    logger.info(f"Meme {meme_id} approved.")
    return {"status": "ok"}

@app.post("/api/meme/{meme_id}/reject")
async def reject_meme(meme_id: int, db: Session = Depends(get_db)):
    meme = db.query(Meme).filter(Meme.id == meme_id).first()
    if not meme:
        raise HTTPException(status_code=404, detail="Meme not found")
    
    meme.status = "rejected"
    db.commit()
    logger.info(f"Meme {meme_id} rejected.")
    return {"status": "ok"}

@app.post("/api/meme/{meme_id}/compress")
async def compress_meme(meme_id: int, db: Session = Depends(get_db)):
    if not compressor_service:
        raise HTTPException(status_code=503, detail="Compressor not initialized")
        
    meme = db.query(Meme).filter(Meme.id == meme_id).first()
    if not meme or not meme.file_path:
        raise HTTPException(status_code=404, detail="Meme or file not found")
        
    if meme.status != "approved":
        raise HTTPException(status_code=400, detail="Only approved memes can be compressed")
        
    # Путь к сжатому файлу
    file_path = Path(meme.file_path)
    output_path = file_path.parent / "compressed" / f"{file_path.stem}_webp{file_path.suffix}"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    result = compressor_service.compress(str(file_path), str(output_path))
    
    if result.get("success"):
        meme.compressed_path = str(output_path)
        meme.status = "compressed"
        db.commit()
        logger.info(f"Meme {meme_id} compressed: {result['compressed_kb']}KB")
        return {"status": "ok", "details": result}
    else:
        logger.error(f"Compression failed for {meme_id}: {result.get('error')}")
        raise HTTPException(status_code=500, detail=result.get('error'))

@app.post("/api/send-digest")
async def send_digest(db: Session = Depends(get_db)):
    if not mailer_service:
        raise HTTPException(status_code=503, detail="Mailer service is disabled or not configured")
        
    # Берем все сжатые или одобренные (если сжатие не обязательно)
    memes_to_send = db.query(Meme).filter(
        (Meme.status == "compressed") | (Meme.status == "approved")
    ).all()
    
    if not memes_to_send:
        return {"status": "info", "message": "Нет мемов для отправки."}
        
    # Формируем список словарей для mailer
    data = [
        {
            "id": m.id,
            "section": m.section,
            "file_path": m.compressed_path or m.file_path,
            "text": m.text
        }
        for m in memes_to_send
    ]
    
    success = mailer_service.send_digest(data)
    
    if success:
        # Обновляем статус
        for m in memes_to_send:
            m.status = "sent"
        db.commit()
        logger.info("Digest email sent successfully.")
        return {"status": "ok", "count": len(data)}
    else:
        logger.error("Failed to send digest email.")
        raise HTTPException(status_code=500, detail="Failed to send email. Check logs.")
import os
import logging
import logging.config
from pathlib import Path
from typing import List, Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, BackgroundTasks, HTTPException, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import desc

# Импорт локальных модулей
from database import engine, get_db, init_db
from models import Meme, RunLog, Setting
from config_loader import load_config
from parsers.vk_parser import VKParser
from parsers.pikabu_parser import PikabuParser
from parsers.joyreactor_parser import JoyReactorParser
from parsers.dvach_parser import DvachParser
# from parsers.telegram_parser import TelegramParser # Закомментировано, т.к. требует async контекста при старте

from services.collector import Collector
from services.compressor import ImageCompressor
from services.mailer import MailerService
from services.scheduler import SchedulerService

# --- Конфигурация логирования ---
LOG_DIR = Path("data")
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / "app.log"

# Простая конфигурация, если файл logging.conf отсутствует
if not Path("logging.conf").exists():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler(LOG_FILE, encoding='utf-8'),
            logging.StreamHandler()
        ]
    )
else:
    logging.config.fileConfig("logging.conf", disable_existing_loggers=False)

logger = logging.getLogger(__name__)

# --- Глобальные переменные ---
config = {}
scheduler_service = None
collector_service = None
compressor_service = None
mailer_service = None

# --- Инициализация при старте приложения ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    global config, scheduler_service, collector_service, compressor_service, mailer_service
    
    logger.info("Starting MemoSbor application...")
    
    # 1. Загрузка конфига
    config = load_config()
    logger.info("Configuration loaded successfully.")
    
    # 2. Инициализация БД
    init_db()
    logger.info("Database initialized.")
    
    # 3. Инициализация сервисов
    compressor_service = ImageCompressor(
        target_kb=config.get("compress", {}).get("target_kb", 150),
        min_quality=config.get("compress", {}).get("min_quality", 60),
        min_dimension=config.get("compress", {}).get("min_dimension", 800)
    )
    
    if config.get("mail", {}).get("enabled", False):
        mailer_service = MailerService(config.get("mail", {}))
        logger.info("Mailer service initialized.")
    else:
        logger.info("Mailer service disabled in config.")
        
    collector_service = Collector(config, db_func=get_db)
    
    # 4. Запуск планировщика
    scheduler_service = SchedulerService()
    schedule_times = config.get("schedule", [])
    if schedule_times:
        # Передаем функцию сбора как задачу
        scheduler_service.add_job(run_collection_task, schedule_times)
        logger.info(f"Scheduled collection tasks: {schedule_times}")
    else:
        logger.info("No scheduled tasks configured.")

    yield
    
    # Shutdown
    logger.info("Shutting down application...")
    if scheduler_service:
        scheduler_service.shutdown()

# --- Фоновая задача для планировщика ---
def run_collection_task():
    """Обертка для запуска коллектора из планировщика (синхронный вызов)."""
    try:
        logger.info("Scheduler triggered collection task.")
        # Создаем новую сессию БД для фонового процесса
        from database import SessionLocal
        db = SessionLocal()
        try:
            collector = Collector(config, db_func=lambda: db)
            stats = collector.run_all()
            logger.info(f"Collection finished: {stats}")
        finally:
            db.close()
    except Exception as e:
        logger.error(f"Error in scheduled collection task: {e}", exc_info=True)

# --- Создание приложения FastAPI ---
app = FastAPI(title="МемоСбор", description="Парсер мемов с модерацией", lifespan=lifespan)

# Подключение статики и шаблонов
BASE_DIR = Path(__file__).resolve().parent
static_path = BASE_DIR / "static"
templates_path = BASE_DIR / "templates"

# Создаем папки, если нет
static_path.mkdir(exist_ok=True)
templates_path.mkdir(exist_ok=True)

app.mount("/static", StaticFiles(directory=str(static_path)), name="static")
templates = Jinja2Templates(directory=str(templates_path))

# --- Вспомогательные функции ---
def get_collector():
    if not collector_service:
        raise HTTPException(status_code=503, detail="Collector service not initialized")
    return collector_service

# --- Роуты (Web Interface) ---

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, db: Session = Depends(get_db)):
    """Главная страница - Галерея новых мемов."""
    memes = db.query(Meme).filter(Meme.status == "new").order_by(desc(Meme.fetched_at)).limit(50).all()
    
    # Статистика
    total_new = db.query(Meme).filter(Meme.status == "new").count()
    total_approved = db.query(Meme).filter(Meme.status == "approved").count()
    total_rejected = db.query(Meme).filter(Meme.status == "rejected").count()
    
    last_run = db.query(RunLog).order_by(desc(RunLog.id)).first()
    
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "memes": memes,
        "stats": {"new": total_new, "approved": total_approved, "rejected": total_rejected},
        "last_run": last_run
    })

@app.get("/approved", response_class=HTMLResponse)
async def approved_gallery(request: Request, db: Session = Depends(get_db)):
    """Страница одобренных мемов (для сжатия и отправки)."""
    memes = db.query(Meme).filter(Meme.status == "approved").order_by(desc(Meme.fetched_at)).all()
    return templates.TemplateResponse("approved.html", {
        "request": request,
        "memes": memes
    })

@app.get("/logs", response_class=HTMLResponse)
async def logs_page(request: Request, db: Session = Depends(get_db)):
    """Страница логов запусков."""
    logs = db.query(RunLog).order_by(desc(RunLog.id)).limit(20).all()
    return templates.TemplateResponse("logs.html", {
        "request": request,
        "logs": logs
    })

@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    """Страница настроек (конфиг)."""
    return templates.TemplateResponse("settings.html", {
        "request": request,
        "config": config
    })

# --- API Роуты (Actions) ---

@app.post("/api/collect")
async def trigger_collect(background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """Запуск сбора мемов вручную."""
    logger.info("Manual collection triggered via API.")
    
    # Запускаем в фоне, чтобы не блокировать UI
    background_tasks.add_task(run_collection_task)
    
    return {"status": "started", "message": "Сбор мемов запущен в фоновом режиме."}

@app.post("/api/meme/{meme_id}/approve")
async def approve_meme(meme_id: int, db: Session = Depends(get_db)):
    meme = db.query(Meme).filter(Meme.id == meme_id).first()
    if not meme:
        raise HTTPException(status_code=404, detail="Meme not found")
    
    meme.status = "approved"
    db.commit()
    logger.info(f"Meme {meme_id} approved.")
    return {"status": "ok"}

@app.post("/api/meme/{meme_id}/reject")
async def reject_meme(meme_id: int, db: Session = Depends(get_db)):
    meme = db.query(Meme).filter(Meme.id == meme_id).first()
    if not meme:
        raise HTTPException(status_code=404, detail="Meme not found")
    
    meme.status = "rejected"
    db.commit()
    logger.info(f"Meme {meme_id} rejected.")
    return {"status": "ok"}

@app.post("/api/meme/{meme_id}/compress")
async def compress_meme(meme_id: int, db: Session = Depends(get_db)):
    if not compressor_service:
        raise HTTPException(status_code=503, detail="Compressor not initialized")
        
    meme = db.query(Meme).filter(Meme.id == meme_id).first()
    if not meme or not meme.file_path:
        raise HTTPException(status_code=404, detail="Meme or file not found")
        
    if meme.status != "approved":
        raise HTTPException(status_code=400, detail="Only approved memes can be compressed")
        
    # Путь к сжатому файлу
    file_path = Path(meme.file_path)
    output_path = file_path.parent / "compressed" / f"{file_path.stem}_webp{file_path.suffix}"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    result = compressor_service.compress(str(file_path), str(output_path))
    
    if result.get("success"):
        meme.compressed_path = str(output_path)
        meme.status = "compressed"
        db.commit()
        logger.info(f"Meme {meme_id} compressed: {result['compressed_kb']}KB")
        return {"status": "ok", "details": result}
    else:
        logger.error(f"Compression failed for {meme_id}: {result.get('error')}")
        raise HTTPException(status_code=500, detail=result.get('error'))

@app.post("/api/send-digest")
async def send_digest(db: Session = Depends(get_db)):
    if not mailer_service:
        raise HTTPException(status_code=503, detail="Mailer service is disabled or not configured")
        
    # Берем все сжатые или одобренные (если сжатие не обязательно)
    memes_to_send = db.query(Meme).filter(
        (Meme.status == "compressed") | (Meme.status == "approved")
    ).all()
    
    if not memes_to_send:
        return {"status": "info", "message": "Нет мемов для отправки."}
        
    # Формируем список словарей для mailer
    data = [
        {
            "id": m.id,
            "section": m.section,
            "file_path": m.compressed_path or m.file_path,
            "text": m.text
        }
        for m in memes_to_send
    ]
    
    success = mailer_service.send_digest(data)
    
    if success:
        # Обновляем статус
        for m in memes_to_send:
            m.status = "sent"
        db.commit()
        logger.info("Digest email sent successfully.")
        return {"status": "ok", "count": len(data)}
    else:
        logger.error("Failed to send digest email.")
        raise HTTPException(status_code=500, detail="Failed to send email. Check logs.")

if __name__ == "__main__":
    import uvicorn
    # Запуск через uvicorn напрямую (для отладки)
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
