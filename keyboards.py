from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

import strings

kb = ReplyKeyboardMarkup(resize_keyboard=True).row(KeyboardButton(strings.GET_PROGRESSES),
                                                   KeyboardButton(strings.CREATE_PROGRESS))

