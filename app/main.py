import logging
import logging.config
from fastapi import FastAPI, Request, Form, BackgroundTasks, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import yaml
import os

from .database import engine, Base
from . import models
from .services.collector import Collector
from .parsers.vk_parser import VKParser
from .parsers.pikabu_parser import PikabuParser
from .parsers.joyreactor_parser import JoyReactorParser
from .parsers.dvach_parser import DvachParser

# Настройка логирования
LOGGING_CONFIG = "logging.conf"
if os.path.exists(LOGGING_CONFIG):
    logging.config.fileConfig(LOGGING_CONFIG, disable_existing_loggers=False)

logger = logging.getLogger("app")

app = FastAPI(title="МемоСбор")

# Создание таблиц при старте
Base.metadata.create_all(bind=engine)

# Статика и шаблоны
os.makedirs("app/static", exist_ok=True)
os.makedirs("data", exist_ok=True)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

CONFIG_PATH = "config.yaml"

def load_config():
    if not os.path.exists(CONFIG_PATH): 
        logger.warning(f"Config file {CONFIG_PATH} not found, using defaults")
        return {}
    with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f) or {}
        logger.info("Configuration loaded successfully")
        return config

def save_config(data):
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    logger.info("Configuration saved")

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    # Получаем статистику из БД
    from sqlalchemy.orm import Session
    from .database import get_db
    from .models import Meme, RunLog
    
    db = next(get_db())
    total_memes = db.query(Meme).count()
    new_memes = db.query(Meme).filter(Meme.status == "new").count()
    approved_memes = db.query(Meme).filter(Meme.status == "approved").count()
    rejected_memes = db.query(Meme).filter(Meme.status == "rejected").count()
    
    # Последние логи
    last_runs = db.query(RunLog).order_by(RunLog.started_at.desc()).limit(5).all()
    
    db.close()
    
    return templates.TemplateResponse("dashboard.html", {
        "request": request, 
        "title": "Дашборд",
        "total_memes": total_memes,
        "new_memes": new_memes,
        "approved_memes": approved_memes,
        "rejected_memes": rejected_memes,
        "last_runs": last_runs
    })

@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, saved: int = 0):
    config = load_config()
    return templates.TemplateResponse("settings.html", {
        "request": request, 
        "config": config, 
        "title": "Настройки API",
        "saved": saved
    })

@app.post("/settings/save")
async def save_settings(
    vk_token: str = Form(""),
    tg_api_id: str = Form("0"),
    tg_api_hash: str = Form(""),
    time_window: int = Form(24)
):
    config = load_config()
    
    # Обновление VK
    if "vk" not in config: config["vk"] = {}
    config["vk"]["service_token"] = vk_token
    
    # Обновление Telegram
    if "telegram" not in config: config["telegram"] = {}
    try:
        config["telegram"]["api_id"] = int(tg_api_id)
    except ValueError:
        config["telegram"]["api_id"] = 0
    config["telegram"]["api_hash"] = tg_api_hash
    
    config["time_window_hours"] = time_window
    
    save_config(config)
    return RedirectResponse(url="/settings?saved=1", status_code=303)

@app.post("/collect")
async def collect_memes(background_tasks: BackgroundTasks):
    """Запуск сбора мемов вручную"""
    logger.info("Manual collection started")
    
    try:
        config = load_config()
        from .database import get_db
        db = next(get_db())
        collector = Collector(config, db)
        
        # Запускаем в фоне, чтобы не блокировать запрос
        async def run_collection():
            try:
                result = await collector.run_all_parsers()
                logger.info(f"Collection completed: {result}")
                return JSONResponse({"status": "success", "result": result})
            except Exception as e:
                logger.error(f"Collection failed: {e}", exc_info=True)
                return JSONResponse({"status": "error", "message": str(e)}, status_code=500)
        
        background_tasks.add_task(run_collection)
        
        return JSONResponse({
            "status": "started", 
            "message": "Сбор мемов запущен в фоновом режиме"
        })
    except Exception as e:
        logger.error(f"Failed to start collection: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/memos", response_class=HTMLResponse)
async def memos_page(request: Request, status: str = "new", section: str = ""):
    """Страница модерации мемов"""
    from sqlalchemy.orm import Session
    from .database import get_db
    from .models import Meme
    
    db = next(get_db())
    
    query = db.query(Meme)
    if status:
        query = query.filter(Meme.status == status)
    if section:
        query = query.filter(Meme.section == section)
    
    memes = query.order_by(Meme.fetched_at.desc()).limit(50).all()
    db.close()
    
    return templates.TemplateResponse("memos.html", {
        "request": request,
        "title": "Модерация мемов",
        "memes": memes,
        "current_status": status,
        "current_section": section
    })

@app.post("/memo/{meme_id}/approve")
async def approve_meme(meme_id: int):
    """Одобрить мем"""
    from sqlalchemy.orm import Session
    from .database import get_db
    from .models import Meme
    
    db = next(get_db())
    meme = db.query(Meme).filter(Meme.id == meme_id).first()
    if not meme:
        db.close()
        raise HTTPException(status_code=404, detail="Мем не найден")
    
    meme.status = "approved"
    db.commit()
    logger.info(f"Meme {meme_id} approved")
    db.close()
    
    return JSONResponse({"status": "success", "message": "Мем одобрен"})

@app.post("/memo/{meme_id}/reject")
async def reject_meme(meme_id: int):
    """Отклонить мем"""
    from sqlalchemy.orm import Session
    from .database import get_db
    from .models import Meme
    
    db = next(get_db())
    meme = db.query(Meme).filter(Meme.id == meme_id).first()
    if not meme:
        db.close()
        raise HTTPException(status_code=404, detail="Мем не найден")
    
    meme.status = "rejected"
    db.commit()
    logger.info(f"Meme {meme_id} rejected")
    db.close()
    
    return JSONResponse({"status": "success", "message": "Мем отклонён"})

@app.get("/logs", response_class=HTMLResponse)
async def logs_page(request: Request):
    """Страница логов"""
    from sqlalchemy.orm import Session
    from .database import get_db
    from .models import RunLog
    
    db = next(get_db())
    logs = db.query(RunLog).order_by(RunLog.started_at.desc()).limit(20).all()
    db.close()
    
    return templates.TemplateResponse("logs.html", {
        "request": request,
        "title": "Логи запусков",
        "logs": logs
    })
