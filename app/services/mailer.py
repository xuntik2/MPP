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