from aiogram.dispatcher.filters.state import State, StatesGroup


class States(StatesGroup):
    default = State()
    name = State()
    n_full = State()
    deadline = State()
    priority = State()
