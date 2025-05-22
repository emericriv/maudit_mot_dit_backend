import uuid
import jsonfield
from django.db import models


class Round(models.Model):
    PHASE_CHOICES = [
        ("choice", "Choix du mot"),
        ("clue", "Donner un indice"),
        ("guess", "Deviner le mot"),
    ]

    game_room = models.ForeignKey(
        "GameRoom", on_delete=models.CASCADE, related_name="rounds"
    )
    current_player = models.ForeignKey("Player", on_delete=models.CASCADE)
    phase = models.CharField(max_length=10, choices=PHASE_CHOICES, default="choice")
    word = models.CharField(max_length=100, blank=True)
    required_clues = models.IntegerField(null=True)
    given_clues = models.JSONField(default=list)  # Liste des indices donnés
    given_guesses = models.JSONField(
        default=list
    )  # Liste des tentatives avec {playerId, word, timestamp}
    guessing_players = models.JSONField(
        default=list
    )  # Liste des IDs des joueurs ayant deviné dans la phase actuelle
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_completed = models.BooleanField(default=False)
    word_found = models.BooleanField(default=False)
    winner = models.ForeignKey(
        "Player", null=True, on_delete=models.SET_NULL, related_name="won_rounds"
    )
    all_guesses = models.JSONField(default=list)


class GameRoom(models.Model):
    code = models.CharField(max_length=6, unique=True)  # ex: ABCD12
    created_at = models.DateTimeField(auto_now_add=True)
    current_word_choices = jsonfield.JSONField(null=True)
    current_turn = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)
    current_round = models.ForeignKey(
        "Round", null=True, on_delete=models.SET_NULL, related_name="+"
    )
    total_rounds = models.IntegerField(default=2)  # Nombre total de tours
    completed_rounds = models.IntegerField(default=0)  # Tours complétés
    player_order = models.JSONField(default=list)

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
