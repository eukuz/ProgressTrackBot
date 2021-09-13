from datetime import date, timedelta, datetime

import pymongo as pymongo
from aiogram import Bot, types
from aiogram.contrib.fsm_storage.mongo import MongoStorage
from aiogram.dispatcher import Dispatcher, FSMContext
from aiogram.utils import executor

import keyboards
from progress import Progress
from states import States
import strings
from config import TOKEN, HOST, PORT, DB, COLLECTION, CONNECTION

client = pymongo.MongoClient(CONNECTION)
db = client[DB]
col = db[COLLECTION]

bot = Bot(token=TOKEN)
dp = Dispatcher(bot, storage=MongoStorage(host=HOST, port=PORT, db_name=DB))


@dp.message_handler(commands=['start'])
async def process_start_command(msg: types.Message):
    await msg.reply(strings.HELLO, reply_markup=keyboards.kb)
    await States.default.set()


@dp.message_handler(lambda msg: msg.text == strings.GET_PROGRESSES, state=['*'])
async def get_progresses(msg: types.Message):
    progs = col.find({"user_id": msg.from_user.id}).sort("priority", -1)
    if progs is not None:
        for prog in progs:
            await bot.send_message(msg.from_user.id, strings.PROGRESS.format(prog['name'], prog['n_full'], prog['n_completed']))


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
    progress = Progress(msg.from_user.id, data['name'], data['n_full'], data['deadline'], data['priority'])
    await msg.answer(
        strings.CREATED.format(progress.name, progress.n_full, progress.deadline.strftime(strings.DATE_FORMAT),
                               progress.priority))
    col.insert_one(progress.__dict__)
    await States.default.set()


if __name__ == '__main__':
    executor.start_polling(dp)
