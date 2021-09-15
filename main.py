from datetime import date, timedelta, datetime

import pymongo as pymongo
from aiogram import Bot, types
from aiogram.contrib.fsm_storage.mongo import MongoStorage
from aiogram.dispatcher import Dispatcher, FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils import executor
from aiogram.utils.exceptions import MessageToDeleteNotFound
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


def make_progress_inline_kb(callback):
    return InlineKeyboardMarkup().row(InlineKeyboardButton('-', callback_data='-' + callback),
                                      InlineKeyboardButton(strings.nums, callback_data=strings.nums + callback),
                                      InlineKeyboardButton(strings.trash, callback_data=strings.trash + callback),
                                      InlineKeyboardButton('+', callback_data='+' + callback))


def make_ensure_deletion_kb(chat_id, message_id, process_id):
    callback = '_{0}_{1}_{2}'.format(chat_id, message_id, process_id)
    return InlineKeyboardMarkup().row(InlineKeyboardButton(text='👍', callback_data=strings.delete + callback),
                                      InlineKeyboardButton(text='👎', callback_data=strings.save + callback))


def format_id(process_id):
    return {'_id': ObjectId(process_id)}


async def deleteMessages(state, msg, bot):
    data = await state.get_data()
    if 'delete_list_from' and 'delete_to' in data:
        for j in range(data['delete_list_from'],data['delete_to']):
            try:
                await bot.delete_message(msg.chat.id, j)
            except MessageToDeleteNotFound:
                continue


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
    async def get_progresses(msg: types.Message, state: FSMContext):
        await deleteMessages(state, msg, bot)
        i = 1
        await state.update_data(delete_list_from=msg.message_id)
        progresses = col.find({"user_id": msg.from_user.id}).sort("priority", -1)
        if progresses is not None:
            for progress in progresses:
                callback = '_{0}_{1}_{2}'.format(msg.from_user.id, (msg.message_id + i), progress['_id'])
                await bot.send_message(msg.from_user.id, progress_format(progress),
                                       reply_markup=make_progress_inline_kb(callback))
                i += 1
        await state.update_data(delete_to=msg.message_id+i)

    @dp.callback_query_handler(state=States.waiting)
    async def proceed_deletion(call: types.CallbackQuery):
        data = call.data.split('_')
        search = format_id(data[3])
        progress = col.find_one(search)
        p_format = progress_format(progress)
        if data[0] == strings.delete:
            col.delete_one(search)
            await bot.delete_message(chat_id=data[1], message_id=data[2])
            await bot.answer_callback_query(callback_query_id=call.id, text=strings.WAS_DELETED.format(p_format))
        elif data[0] == strings.save:
            await bot.answer_callback_query(callback_query_id=call.id, text=strings.WONT_BE_DELETED.format(p_format))

        await bot.delete_message(chat_id=data[1], message_id=call.message.message_id)
        await States.default.set()

    @dp.callback_query_handler(state='*')
    async def proceed_callback(call: types.CallbackQuery):
        data = call.data.split('_')
        callback = '_{1}_{2}_{3}'.format(data[0], data[1], data[2], data[3])
        search = format_id(data[3])
        progress = col.find_one(search)
        if data[0] == '-' or data[0] == '+':
            n = calculateN(progress['n_completed'], progress['n_full'], data)
            if progress['n_completed'] != n:
                col.update_one(search, {'$set': {'n_completed': n}})
                progress['n_completed'] = n
                await bot.edit_message_text(chat_id=data[1], message_id=data[2], text=progress_format(progress),
                                            reply_markup=make_progress_inline_kb(callback))
                await bot.answer_callback_query(callback_query_id=call.id, text=strings.smile)
            elif n == 0:
                await bot.answer_callback_query(callback_query_id=call.id, text=strings.PROHIBITED_LTZ)
            else:
                await bot.answer_callback_query(callback_query_id=call.id, text=strings.CONGRATS_DONE)

        elif data[0] == '🔢':
            await bot.answer_callback_query(callback_query_id=call.id,
                                            text="УСТАНОВКА КОЛ-ВА ПРОЙДЕННЫХ ЭЛЕМНТОВ В РАЗРАБОТКЕ!")
        elif data[0] == '🗑️':
            await bot.answer_callback_query(callback_query_id=call.id, text=strings.ENSURE)
            await bot.send_message(chat_id=data[1], text=strings.ENSURE_DELETING + progress_format(progress),
                                   reply_markup=make_ensure_deletion_kb(data[1], data[2], data[3]))
            await States.waiting.set()

    @dp.message_handler(lambda msg: msg.text == strings.CREATE_PROGRESS, state=['*'])
    async def create_progress(msg: types.Message, state: FSMContext):
        await deleteMessages(state, msg, bot)
        await state.update_data(delete_from=msg.message_id)
        await msg.reply(strings.INPUT_NAME)
        await States.name.set()

    @dp.message_handler(state=States.name, content_types=['text'])
    async def name_chosen(msg: types.Message, state: FSMContext):
        await state.update_data(delete_to=msg.message_id+2)
        await state.update_data(name=msg.text)
        await msg.answer(strings.INPUT_NUMBER_OF_ELEMENTS)
        await States.next()

    @dp.message_handler(state=States.n_full, content_types=['text'])
    async def n_chosen(msg: types.Message, state: FSMContext):
        await state.update_data(delete_to=msg.message_id+2)
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
        await state.update_data(delete_to=msg.message_id+2)
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
        await state.update_data(delete_to=msg.message_id+2)
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
        d = data.copy()
        d['user_id'] = msg.from_user.id
        d['n_completed'] = 0
        delete_id = d['delete_from']
        d.pop('delete_from')
        d.pop('delete_to')
        for i in range(delete_id, msg.message_id + 1):
            await bot.delete_message(msg.chat.id, i)

        await msg.answer(strings.CREATED.format(d['name'], d['n_full'], d['deadline'], d['priority']))
        col.insert_one(d)
        await States.default.set()

    if __name__ == '__main__':
        executor.start_polling(dp)


main()
