import uuid
from django.db import models


class GameRoom(models.Model):
    code = models.CharField(max_length=6, unique=True)  # ex: ABCD12
    created_at = models.DateTimeField(auto_now_add=True)
    current_turn = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"Room {self.code}"


class Player(models.Model):
    room = models.ForeignKey(GameRoom, related_name="players", on_delete=models.CASCADE)
    pseudo = models.CharField(max_length=50)
    session_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    is_owner = models.BooleanField(default=False)
    score = models.IntegerField(default=0)

    def __str__(self):
        return self.pseudo
