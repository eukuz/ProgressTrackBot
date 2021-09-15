import math
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


def make_progress_bar(n: int, m: int):
    percent = round(n / m * 100, 2)
    tens = int(percent // 10) * 2
    fulls = strings.one * tens
    halves = 1 if percent % 10 != 0 else 0
    half = (strings.half1 + strings.half2) * halves
    zeros = strings.zero * (20 - tens - halves - (1 * halves))
    return fulls + half + zeros


def progress_format(progress):
    deadline = progress['deadline']
    days_left = (deadline - datetime.today()).days
    n = progress['n_completed']
    m = progress['n_full']

    if n == m:
        deadline_info = strings.CONGRATS_DONE_MSG
    elif days_left < -1:
        deadline_info = strings.OVERDUE.format(datetime.strftime(deadline, strings.DATE_FORMAT))
    elif days_left == -1:
        deadline_info = strings.DEADLINE_TODAY
    else:
        per_day = math.ceil((m - n) / days_left)
        per_week = math.ceil((m - n) / (days_left / 7))
        deadline_info = strings.PER_DAY.format(per_week, per_day, make_progress_bar(n, m))

    return strings.PROGRESS.format(progress['name'], m, n, deadline_info)


def calculateN(n_completed, n_full, control_char):
    if control_char == '+':
        return n_completed + 1 if n_completed < n_full else n_full
    elif control_char == '-':
        return n_completed - 1 if n_completed > 0 else 0


def make_progress_inline_kb(callback):
    return InlineKeyboardMarkup().row(InlineKeyboardButton('-', callback_data='-' + callback),
                                      InlineKeyboardButton(strings.nums, callback_data=strings.nums + callback),
                                      InlineKeyboardButton(strings.trash, callback_data=strings.trash + callback),
                                      InlineKeyboardButton('+', callback_data='+' + callback))


def make_ensure_deletion_kb(chat_id, message_id, process_id):
    callback = '_{0}_{1}_{2}'.format(chat_id, message_id, process_id)
    return InlineKeyboardMarkup().row(InlineKeyboardButton(text='✅', callback_data=strings.delete + callback),
                                      InlineKeyboardButton(text='❌', callback_data=strings.save + callback))


def format_id(process_id):
    return {'_id': ObjectId(process_id)}


async def deleteMessages(state, chat_id, bot):
    data = await state.get_data()
    print(data)
    if 'delete_from' and 'delete_to' in data:
        for j in range(data['delete_from'], data['delete_to']):
            try:
                await bot.delete_message(chat_id, j)
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
        await deleteMessages(state, msg.chat.id, bot)
        i = 1
        await state.update_data(delete_from=msg.message_id)
        progresses = col.find({"user_id": msg.from_user.id}).sort("priority", -1)
        if progresses is not None:
            for progress in progresses:
                callback = '_{0}_{1}_{2}'.format(msg.from_user.id, (msg.message_id + i), progress['_id'])
                await bot.send_message(msg.from_user.id, progress_format(progress),
                                       reply_markup=make_progress_inline_kb(callback))
                i += 1
        await state.update_data(delete_to=msg.message_id + i)
        await States.default.set()

    @dp.callback_query_handler(state=States.deletion)
    async def proceed_deleting(call: types.CallbackQuery, state: FSMContext):
        control_char, chat_id, msg_id, progress_id = call.data.split('_')
        data = await state.get_data()
        if control_char == strings.trash:
            await bot.delete_message(chat_id, message_id=data['delete_to'])
            await States.default.set()
            await proceed_callback(call, state)
            return
        search = format_id(progress_id)
        progress = col.find_one(search)
        p_format = progress_format(progress)
        if control_char == strings.delete:
            col.delete_one(search)
            await bot.delete_message(chat_id=chat_id, message_id=msg_id)
            await bot.answer_callback_query(callback_query_id=call.id, text=strings.WAS_DELETED.format(p_format))
        elif control_char == strings.save:
            await bot.answer_callback_query(callback_query_id=call.id, text=strings.WONT_BE_DELETED.format(p_format))

        await bot.delete_message(chat_id=chat_id, message_id=call.message.message_id)
        await States.default.set()

    @dp.message_handler(state=States.setting_n)
    async def proceed_setting_n(msg: types.Message, state: FSMContext):
        data = await state.get_data()
        search = format_id(data['progress_id_to_set_n'])
        progress = col.find_one(search)
        error = strings.INT_GTZ_LTM_ERROR.format(progress['n_full'])

        try:
            n = int(msg.text)
            if n < 0 or n > progress['n_full']:
                await msg.answer(error)
                return
        except ValueError:
            await msg.answer(error)
            return
        finally:
            await state.update_data(delete_to=msg.message_id + 1)

        col.update_one(search, {'$set': {'n_completed': n}})
        await deleteMessages(state, msg.chat.id, bot)
        await get_progresses(msg, state)

        await States.default.set()

    @dp.callback_query_handler(state='*')
    async def proceed_callback(call: types.CallbackQuery, state: FSMContext):
        control_char, chat_id, msg_id, process_id = call.data.split('_')
        callback = call.data[1:]
        search = format_id(process_id)
        progress = col.find_one(search)
        if control_char == '-' or control_char == '+':
            n = calculateN(progress['n_completed'], progress['n_full'], control_char)
            if progress['n_completed'] != n:
                col.update_one(search, {'$set': {'n_completed': n}})
                progress['n_completed'] = n
                await bot.edit_message_text(chat_id=chat_id, message_id=msg_id, text=progress_format(progress),
                                            reply_markup=make_progress_inline_kb(callback))
                await bot.answer_callback_query(callback_query_id=call.id)
            elif n == 0:
                await bot.answer_callback_query(callback_query_id=call.id, text=strings.PROHIBITED_LTZ)
            else:
                await bot.answer_callback_query(callback_query_id=call.id, text=strings.CONGRATS_DONE)

        elif control_char == strings.nums:
            current_state = await state.get_state()
            data = await state.get_data()
            if current_state == States.setting_n.state:
                await bot.delete_message(chat_id,data['delete_to'])

            await bot.answer_callback_query(callback_query_id=call.id)
            num_msg = await bot.send_message(chat_id=chat_id, text=strings.SET_N.format(progress_format(progress)))
            await state.update_data(progress_id_to_set_n=process_id)
            await state.update_data(delete_to=num_msg.message_id)
            await States.setting_n.set()

        elif control_char == strings.trash:
            await bot.answer_callback_query(callback_query_id=call.id)
            del_msg = await bot.send_message(chat_id=chat_id, text=strings.ENSURE_DELETING + progress_format(progress),
                                             reply_markup=make_ensure_deletion_kb(chat_id, msg_id, process_id))
            await state.update_data(delete_to=del_msg.message_id)
            await States.deletion.set()

    @dp.message_handler(lambda msg: msg.text == strings.CREATE_PROGRESS, state=['*'])
    async def create_progress(msg: types.Message, state: FSMContext):
        await deleteMessages(state, msg.chat.id, bot)
        await state.update_data(delete_from=msg.message_id)
        await state.update_data(delete_to=msg.message_id + 2)
        await msg.reply(strings.INPUT_NAME)
        await States.name.set()

    @dp.message_handler(state=States.name, content_types=['text'])
    async def name_chosen(msg: types.Message, state: FSMContext):
        await state.update_data(delete_to=msg.message_id + 2)
        await state.update_data(name=msg.text)
        await msg.answer(strings.INPUT_NUMBER_OF_ELEMENTS)
        await States.next()

    @dp.message_handler(state=States.n_full, content_types=['text'])
    async def n_chosen(msg: types.Message, state: FSMContext):
        await state.update_data(delete_to=msg.message_id + 2)
        try:
            n = int(msg.text)
            if n < 0:
                await msg.answer(strings.INT_GTZ_ERROR)
                return
        except ValueError:
            await msg.answer(strings.INT_GTZ_ERROR)
            return

        await state.update_data(n_full=n)
        await msg.answer(strings.INPUT_DEADLINE + (date.today() + timedelta(days=n)).strftime(strings.DATE_FORMAT))
        await States.next()

    @dp.message_handler(state=States.deadline, content_types=['text'])
    async def deadline_chosen(msg: types.Message, state: FSMContext):
        await state.update_data(delete_to=msg.message_id + 2)
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
        await state.update_data(delete_to=msg.message_id + 2)
        try:
            p = int(msg.text)
            if p < 0 or p > 100:
                await msg.answer(strings.INT_GTZ_ERROR)
                return
        except ValueError:
            await msg.answer(strings.INT_GTZ_ERROR)
            return

        await state.update_data(priority=p)
        d = dict(await state.get_data())
        for i in range(d['delete_from'], msg.message_id + 1):
            await bot.delete_message(msg.chat.id, i)

        d['user_id'] = msg.from_user.id
        d.pop('delete_from', 20)
        d.pop('delete_to', 20)
        d.pop('progress_id_to_set_n', 20)
        d['n_completed'] = 0

        await msg.answer(strings.CREATED.format(d['name'], d['n_full'], d['deadline'], d['priority']))
        col.insert_one(d)
        await States.default.set()

    if __name__ == '__main__':
        executor.start_polling(dp)


main()
