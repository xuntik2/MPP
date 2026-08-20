import logging
import logging.config
from pathlib import Path
from datetime import datetime
from typing import List, Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Form, BackgroundTasks, HTTPException, Depends
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import desc, text

# Импорт локальных модулей (Относительные импорты для пакета app)
from .database import engine, Base, get_db, init_db, SessionLocal
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
        
    collector_service = Collector(config, SessionLocal())
    
    # 4. Запуск планировщика
    scheduler_service = SchedulerService()
    schedule_times = config.get("schedule", [])
    if schedule_times:
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
        db = SessionLocal()
        try:
            collector = Collector(config, db)
            stats = collector.run_collection()
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

static_path.mkdir(exist_ok=True)
templates_path.mkdir(exist_ok=True)

app.mount("/static", StaticFiles(directory=str(static_path)), name="static")
templates = Jinja2Templates(directory=str(templates_path))

def get_collector():
    if not collector_service:
        raise HTTPException(status_code=503, detail="Collector service not initialized")
    return collector_service

# --- Роуты (Web Interface) ---

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, db: Session = Depends(get_db)):
    memes = db.query(Meme).filter(Meme.status == "new").order_by(desc(Meme.fetched_at)).limit(50).all()
    
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
    memes = db.query(Meme).filter(Meme.status == "approved").order_by(desc(Meme.fetched_at)).all()
    return templates.TemplateResponse("approved.html", {
        "request": request,
        "memes": memes
    })

@app.get("/logs", response_class=HTMLResponse)
async def logs_page(request: Request, db: Session = Depends(get_db)):
    logs = db.query(RunLog).order_by(desc(RunLog.id)).limit(20).all()
    return templates.TemplateResponse("logs.html", {
        "request": request,
        "logs": logs
    })

@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    return templates.TemplateResponse("settings.html", {
        "request": request,
        "config": config
    })

# --- API Роуты (Actions) ---

@app.get("/health")
async def health_check(db: Session = Depends(get_db)):
    """
    Health check endpoint для мониторинга доступности сервиса и источников.
    Возвращает статус компонентов приложения.
    """
    health_status = {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "components": {
            "database": {"status": "unknown", "latency_ms": None},
            "vk_api": {"status": "unknown", "message": "Token not configured"},
            "parsers": {"status": "unknown", "active": 0, "total": 0},
            "scheduler": {"status": "unknown", "jobs_count": 0},
            "compressor": {"status": "unknown"},
            "mailer": {"status": "unknown"}
        }
    }
    
    # Проверка БД
    try:
        start_time = datetime.now()
        db.execute(text("SELECT 1"))
        latency = (datetime.now() - start_time).total_seconds() * 1000
        health_status["components"]["database"] = {
            "status": "healthy",
            "latency_ms": round(latency, 2)
        }
    except Exception as e:
        health_status["components"]["database"] = {
            "status": "unhealthy",
            "error": str(e)
        }
        health_status["status"] = "degraded"
    
    # Проверка VK API конфигурации
    if config.get("vk", {}).get("service_token"):
        health_status["components"]["vk_api"] = {
            "status": "configured",
            "communities_count": len(config.get("vk", {}).get("communities", []))
        }
    else:
        health_status["components"]["vk_api"] = {
            "status": "not_configured",
            "message": "VK service token is missing"
        }
    
    # Проверка парсеров
    active_parsers = sum([
        1 if config.get("vk", {}).get("service_token") else 0,
        1 if config.get("parsers", {}).get("pikabu", True) else 0,
        1 if config.get("parsers", {}).get("joyreactor", True) else 0,
        1 if config.get("parsers", {}).get("dvach", False) else 0
    ])
    health_status["components"]["parsers"] = {
        "status": "healthy" if active_parsers > 0 else "no_active",
        "active": active_parsers,
        "total": 4,
        "sources": {
            "vk": bool(config.get("vk", {}).get("service_token")),
            "pikabu": config.get("parsers", {}).get("pikabu", True),
            "joyreactor": config.get("parsers", {}).get("joyreactor", True),
            "dvach": config.get("parsers", {}).get("dvach", False)
        }
    }
    
    # Проверка планировщика
    if scheduler_service:
        jobs_count = len(scheduler_service.scheduler.get_jobs())
        health_status["components"]["scheduler"] = {
            "status": "healthy" if jobs_count > 0 else "no_jobs",
            "jobs_count": jobs_count
        }
    else:
        health_status["components"]["scheduler"] = {
            "status": "not_initialized"
        }
    
    # Проверка компрессора
    if compressor_service:
        health_status["components"]["compressor"] = {
            "status": "ready",
            "config": {
                "target_kb": compressor_service.target_kb,
                "min_quality": compressor_service.min_quality
            }
        }
    else:
        health_status["components"]["compressor"] = {
            "status": "not_initialized"
        }
    
    # Проверка mailer
    if mailer_service and mailer_service.enabled:
        health_status["components"]["mailer"] = {
            "status": "configured",
            "smtp_host": mailer_service.host,
            "recipients_count": len(mailer_service.recipients)
        }
    elif mailer_service:
        health_status["components"]["mailer"] = {
            "status": "disabled",
            "message": "Mailer is disabled in config"
        }
    else:
        health_status["components"]["mailer"] = {
            "status": "not_initialized"
        }
    
    # Определение общего статуса
    db_status = health_status["components"]["database"]["status"]
    if db_status == "unhealthy":
        health_status["status"] = "unhealthy"
        return JSONResponse(status_code=503, content=health_status)
    
    parser_status = health_status["components"]["parsers"]["status"]
    if parser_status == "no_active":
        health_status["status"] = "degraded"
    
    return JSONResponse(content=health_status)


@app.get("/health/ready")
async def readiness_check(db: Session = Depends(get_db)):
    """
    Readiness probe - проверяет готовность приложения принимать запросы.
    Используется Kubernetes-style readiness probes.
    """
    try:
        # Быстрая проверка БД
        db.execute(text("SELECT 1"))
        return JSONResponse(content={"status": "ready"})
    except Exception as e:
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "reason": str(e)}
        )


@app.get("/health/live")
async def liveness_check():
    """
    Liveness probe - простая проверка что приложение живо.
    Используется Kubernetes-style liveness probes.
    """
    return JSONResponse(content={"status": "alive"})

@app.post("/api/collect")
async def trigger_collect(background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    logger.info("Manual collection triggered via API.")
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
        
    memes_to_send = db.query(Meme).filter(
        (Meme.status == "compressed") | (Meme.status == "approved")
    ).all()
    
    if not memes_to_send:
        return {"status": "info", "message": "Нет мемов для отправки."}
        
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
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)