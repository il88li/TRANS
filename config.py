import os

class Config:
    BOT_TOKEN = os.getenv("BOT_TOKEN", "8052900952:AAEvZKao98ibPDlUqxBVcj6In1YOa4cbW18")
    API_ID = int(os.getenv("API_ID", 23656977))
    API_HASH = os.getenv("API_HASH", "49d3f43531a92b3f5bc403766313ca1e")
    ADMIN_ID = int(os.getenv("ADMIN_ID", 6689435577))
    DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///bot.db")
