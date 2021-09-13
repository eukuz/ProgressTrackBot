from aiogram.types import ReplyKeyboardRemove, \
    ReplyKeyboardMarkup, KeyboardButton, \
    InlineKeyboardMarkup, InlineKeyboardButton

import strings

kb = ReplyKeyboardMarkup(resize_keyboard=True).row(KeyboardButton(strings.GET_PROGRESSES),
                                                   KeyboardButton(strings.CREATE_PROGRESS))
