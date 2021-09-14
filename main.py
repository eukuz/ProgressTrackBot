from datetime import date, timedelta, datetime

import pymongo as pymongo
from aiogram import Bot, types
from aiogram.contrib.fsm_storage.mongo import MongoStorage
from aiogram.dispatcher import Dispatcher, FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils import executor
from bson import ObjectId

import keyboards
from states import States
import strings
from config import TOKEN, HOST, PORT, DB, COLLECTION, CONNECTION


def progress_format(progress):
    return strings.PROGRESS.format(progress['name'], progress['n_full'], progress['n_completed'])


def calculateN(n_completed, n_full, data):
    if data[0] == '+':
        return n_completed + 1 if n_completed < n_full else n_full
    elif data[0] == '-':
        return n_completed - 1 if n_completed > 0 else 0


def main():
    client = pymongo.MongoClient(CONNECTION)
    db = client[DB]
    col = db[COLLECTION]

    bot = Bot(token=TOKEN)
    dp = Dispatcher(bot, storage=MongoStorage(host=HOST, port=PORT, db_name=DB))

    @dp.message_handler(commands=['start'], state=['*'])
    async def process_start_command(msg: types.Message):
        await msg.reply(strings.HELLO, reply_markup=keyboards.kb)
        await States.default.set()

    @dp.message_handler(lambda msg: msg.text == strings.GET_PROGRESSES, state=['*'])
    async def get_progresses(msg: types.Message):
        i = 1
        progresses = col.find({"user_id": msg.from_user.id}).sort("priority", -1)
        if progresses is not None:
            for progress in progresses:
                callback = '_{0}_{1}_{2}'.format(msg.from_user.id, (msg.message_id + i), progress['_id'])
                kb = InlineKeyboardMarkup().row(InlineKeyboardButton('-', callback_data='-' + callback),
                                                InlineKeyboardButton('+', callback_data='+' + callback))
                await bot.send_message(msg.from_user.id, progress_format(progress), reply_markup=kb)
                i += 1

    @dp.callback_query_handler(state='*')
    async def proceed_callback(call: types.CallbackQuery):
        data = call.data.split('_')
        callback = '_{1}_{2}_{3}'.format(data[0], data[1], data[2], data[3])
        kb = InlineKeyboardMarkup().row(InlineKeyboardButton('-', callback_data='-' + callback),
                                        InlineKeyboardButton('+', callback_data='+' + callback))
        search = {'_id': ObjectId(data[3])}
        progress = col.find_one(search)
        n = calculateN(progress['n_completed'], progress['n_full'], data)
        if progress['n_completed'] != n:
            col.update_one(search, {'$set': {'n_completed': n}})
            progress['n_completed'] = n
            await bot.edit_message_text(chat_id=data[1], message_id=data[2], text=progress_format(progress),
                                        reply_markup=kb)
        elif n == 0:
            await bot.answer_callback_query(callback_query_id=call.id, text=strings.PROHIBITED_LTZ)
        else:
            await bot.answer_callback_query(callback_query_id=call.id, text=strings.CONGRATS_DONE)

    @dp.message_handler(lambda msg: msg.text == strings.CREATE_PROGRESS, state=['*'])
    async def create_progress(msg: types.Message):
        await msg.reply(strings.INPUT_NAME)
        await States.name.set()

    @dp.message_handler(state=States.name, content_types=['text'])
    async def name_chosen(msg: types.Message, state: FSMContext):
        await state.update_data(name=msg.text)
        await msg.answer(strings.INPUT_NUMBER_OF_ELEMENTS)
        await States.next()

    @dp.message_handler(state=States.n_full, content_types=['text'])
    async def n_chosen(msg: types.Message, state: FSMContext):
        try:
            n = int(msg.text)
            if n < 0:
                await msg.answer(strings.NUMBER_OF_ELEMENTS_ERROR)
                return
        except ValueError:
            await msg.answer(strings.NUMBER_OF_ELEMENTS_ERROR)
            return

        await state.update_data(n_full=n)
        await msg.answer(strings.INPUT_DEADLINE + (date.today() + timedelta(days=n)).strftime(strings.DATE_FORMAT))
        await States.next()

    @dp.message_handler(state=States.deadline, content_types=['text'])
    async def deadline_chosen(msg: types.Message, state: FSMContext):
        try:
            d = datetime.strptime(msg.text, strings.DATE_FORMAT)
        except ValueError:
            await msg.answer(strings.DEADLINE_ERROR)
            return

        await state.update_data(deadline=d)
        await msg.answer(strings.INPUT_PRIORITY)
        await States.next()

    @dp.message_handler(state=States.priority, content_types=['text'])
    async def priority_chosen(msg: types.Message, state: FSMContext):
        try:
            p = int(msg.text)
            if p < 0 or p > 100:
                await msg.answer(strings.NUMBER_OF_ELEMENTS_ERROR)
                return
        except ValueError:
            await msg.answer(strings.NUMBER_OF_ELEMENTS_ERROR)
            return

        await state.update_data(priority=p)
        data = await state.get_data()
        data['user_id'] = msg.from_user.id
        data['n_completed'] = 0
        await msg.answer(strings.CREATED.format(data['name'], data['n_full'], data['deadline'],data['priority']))
        col.insert_one(data)
        await States.default.set()

    if __name__ == '__main__':
        executor.start_polling(dp)


main()
