import os
import yaml
import logging

logger = logging.getLogger(__name__)

CONFIG_PATH = "config.yaml"

def load_config() -> dict:
    """Загружает конфигурацию из config.yaml"""
    if not os.path.exists(CONFIG_PATH):
        logger.warning(f"Config file {CONFIG_PATH} not found, using defaults")
        return {}
    
    try:
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f) or {}
        logger.info("Configuration loaded successfully")
        return config
    except Exception as e:
        logger.error(f"Error loading config: {e}")
        return {}

def save_config(config: dict) -> bool:
    """Сохраняет конфигурацию в config.yaml"""
    try:
        with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
            yaml.dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
        logger.info("Configuration saved")
        return True
    except Exception as e:
        logger.error(f"Error saving config: {e}")
        return False
