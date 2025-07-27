# handlers/filters.py
from telegram.ext import filters
from telegram import Message
import database

class AdminFilter(filters.BaseFilter):
    def filter(self, message: Message) -> bool:
        if not message.from_user:
            return False
        return database.is_admin(message.from_user.id)

admin_filter = AdminFilter()