import datetime


class Progress:

    def __init__(self, user_id: int, name: str, n_full: int, deadline: datetime.date, priority: int):
        self.user_id = user_id
        self.name = name
        self.n_full = n_full
        self.n_completed = 0
        self.deadline = deadline
        self.priority = priority

    def increase(self):
        self.n_completed = self.n_completed + 1 if self.n_completed < self.n_full else self.n_full

    def decrease(self):
        self.n_completed = self.n_completed - 1 if self.n_completed > 0 else 0
