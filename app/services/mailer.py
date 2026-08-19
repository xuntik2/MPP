import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from pathlib import Path
import logging
from typing import List, Dict

logger = logging.getLogger(__name__)

class MailerService:
    """
    Сервис отправки почтовых рассылок с подборками мемов.
    Поддерживает SSL, HTML-письма и вложения изображений.
    """
    
    def __init__(self, config: dict):
        self.host = config.get("smtp_host")
        self.port = config.get("smtp_port", 465)
        self.login = config.get("login")
        self.password = config.get("password")
        self.recipients = config.get("recipients", [])
        self.sender = config.get("login", "")
        
        if not self.host or not self.login:
            logger.warning("MailerService initialized with incomplete config. Sending will fail.")

    def send_digest(self, memes: List[Dict], subject: str = "Подборка мемов МемоСбор 🤡") -> bool:
        """
        Отправляет HTML-письмо с вложенными мемами.
        :param memes: Список словарей с ключами 'section', 'file_path', 'text'.
        :param subject: Тема письма.
        :return: True если успешно, иначе False.
        """
        if not self.host or not self.login or not self.recipients:
            logger.error("SMTP credentials or recipients missing. Email not sent.")
            return False

        msg = MIMEMultipart("related")
        msg["Subject"] = subject
        msg["From"] = self.sender
        msg["To"] = ", ".join(self.recipients)

        # Формируем HTML тело
        html = """
        <html>
        <head>
            <style>
                body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #f4f4f4; padding: 20px; color: #333; }
                h2 { color: #2c3e50; border-bottom: 2px solid #3498db; padding-bottom: 10px; }
                h3 { color: #e67e22; text-transform: capitalize; margin-top: 20px; }
                .meme-container { display: flex; flex-wrap: wrap; gap: 15px; justify-content: center; }
                .meme-card { background: white; border-radius: 8px; overflow: hidden; box-shadow: 0 2px 5px rgba(0,0,0,0.1); max-width: 300px; }
                .meme-card img { width: 100%; height: auto; display: block; }
                .meme-text { padding: 10px; font-size: 14px; color: #555; }
                hr { border: 0; border-top: 1px solid #ddd; margin: 20px 0; }
                footer { margin-top: 30px; font-size: 12px; color: #888; text-align: center; }
            </style>
        </head>
        <body>
            <h2>Свежая подборка мемов 🤡</h2>
        """
        
        # Группировка по разделам
        sections = {}
        for meme in memes:
            sec = meme.get('section', 'other')
            if sec not in sections:
                sections[sec] = []
            sections[sec].append(meme)

        if not sections:
            logger.warning("No memes to include in the digest.")
            return False

        for section, items in sections.items():
            html += f"<h3>{section}</h3><div class='meme-container'>"
            for item in items:
                path_str = item.get('compressed_path') or item.get('file_path')
                if not path_str:
                    continue
                    
                path = Path(path_str)
                if not path.exists():
                    logger.warning(f"Meme file not found: {path}")
                    continue
                
                try:
                    with open(path, "rb") as f:
                        img_data = f.read()
                    
                    # Добавляем вложение
                    image = MIMEImage(img_data, name=path.name)
                    image.add_header('Content-ID', f'<{path.name}>')
                    image.add_header('Content-Disposition', 'inline', filename=path.name)
                    msg.attach(image)
                    
                    # Добавляем в HTML
                    text_preview = item.get('text', '')[:100] + "..." if item.get('text') else ""
                    html += f"""
                    <div class='meme-card'>
                        <img src='cid:{path.name}' alt='Meme'>
                        <div class='meme-text'>{text_preview}</div>
                    </div>
                    """
                except Exception as e:
                    logger.error(f"Error attaching image {path}: {e}")
            
            html += "</div><hr>"

        html += """
            <footer>
                <p>Сгенерировано автоматически сервисом <strong>МемоСбор</strong>.</p>
            </footer>
        </body>
        </html>
        """
        
        msg.attach(MIMEText(html, "html"))

        try:
            logger.info(f"Connecting to SMTP server {self.host}:{self.port}...")
            with smtplib.SMTP_SSL(self.host, self.port) as server:
                server.set_debuglevel(0)
                server.login(self.login, self.password)
                server.send_message(msg)
            
            logger.info(f"Email digest sent successfully to {len(self.recipients)} recipients.")
            return True
            
        except Exception as e:
            logger.error(f"Failed to send email: {e}", exc_info=True)
            return False
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from pathlib import Path
from typing import List, Dict
import logging

logger = logging.getLogger(__name__)

class MailerService:
    def __init__(self, config: dict):
        self.host = config.get('smtp_host')
        self.port = config.get('smtp_port', 465)
        self.login = config.get('login')
        self.password = config.get('password')
        self.recipients = config.get('recipients', [])
        self.enabled = config.get('enabled', False)

    def send_digest(self, memes: List[Dict], section_name: str = "Подборка мемов") -> bool:
        if not self.enabled or not memes:
            logger.info("Mail disabled or no memes to send.")
            return False

        msg = MIMEMultipart('related')
        msg['Subject'] = f"🔥 {section_name} ({len(memes)} шт.)"
        msg['From'] = self.login
        msg['To'] = ", ".join(self.recipients)

        # HTML тело
        html = f"""
        <html>
        <body style="font-family: Arial, sans-serif; background: #f4f4f4; padding: 20px;">
            <h2>{section_name}</h2>
            <div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 10px;">
        """
        
        for i, meme in enumerate(memes):
            path = meme.get('compressed_path') or meme.get('file_path')
            if path and Path(path).exists():
                cid = f"meme{i}"
                html += f"""
                <div style="border: 1px solid #ddd; padding: 5px; background: white;">
                    <img src="cid:{cid}" style="width: 100%; height: auto;">
                    <p style="font-size: 12px; color: #555;">{meme.get('text', '')[:50]}</p>
                </div>
                """
                # Добавляем картинку
                with open(path, 'rb') as img_file:
                    img = MIMEImage(img_file.read())
                    img.add_header('Content-ID', f'<{cid}>')
                    msg.attach(img)
        
        html += "</div></body></html>"
        msg.attach(MIMEText(html, 'html'))

        try:
            with smtplib.SMTP_SSL(self.host, self.port) as server:
                server.login(self.login, self.password)
                server.send_message(msg)
            logger.info(f"Email sent to {self.recipients}")
            return True
        except Exception as e:
            logger.error(f"Failed to send email: {e}")
            return False
