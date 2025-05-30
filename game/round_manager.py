from datetime import datetime
import time
from channels.db import database_sync_to_async
from django.apps import apps


class RoundManager:
    def __init__(self, room_code):
        self.room_code = room_code

    @database_sync_to_async
    def start_new_round(self, player_id):
        GameRoom = apps.get_model("game", "GameRoom")
        Round = apps.get_model("game", "Round")

        room = GameRoom.objects.get(code=self.room_code)
        round = Round.objects.create(
            game_room=room, current_player_id=player_id, phase="choice"
        )
        room.current_round = round
        room.save()
        return round

    @database_sync_to_async
    def update_phase(self, phase, **kwargs):
        GameRoom = apps.get_model("game", "GameRoom")
        room = GameRoom.objects.get(code=self.room_code)
        round = room.current_round
        round.phase = phase

        # reset les joueurs qui ont deviné
        if phase == "guess":
            round.guessing_players = []

        for key, value in kwargs.items():
            setattr(round, key, value)

        round.save()
        return round

    @database_sync_to_async
    def add_clue(self, clue):
        GameRoom = apps.get_model("game", "GameRoom")
        room = GameRoom.objects.get(code=self.room_code)
        round = room.current_round
        round.given_clues = round.given_clues + [clue]
        round.save()

    @database_sync_to_async
    def add_guessing_player(self, player_id):
        GameRoom = apps.get_model("game", "GameRoom")
        room = GameRoom.objects.get(code=self.room_code)
        round = room.current_round
        if player_id not in round.guessing_players:
            round.guessing_players = round.guessing_players + [player_id]
            round.save()

    @database_sync_to_async
    def add_guess(self, player_id, word):
        GameRoom = apps.get_model("game", "GameRoom")
        room = GameRoom.objects.get(code=self.room_code)
        round = room.current_round
        timestamp = datetime.now().isoformat()

        # Ajoute la tentative à l'historique
        new_guess = {
            "playerId": player_id,
            "word": word,
            "timestamp": timestamp,
        }

        if not round.given_guesses:
            round.given_guesses = []

        if not round.guessing_players:
            round.guessing_players = []

        # Vérifie si le joueur n'a pas déjà deviné dans cette phase
        if player_id not in round.guessing_players:
            round.given_guesses.append(new_guess)
            round.guessing_players.append(player_id)
            round.save()

        return round.given_guesses, round.guessing_players, timestamp

    @database_sync_to_async
    def complete_round(self, word_found=False, winner_id=None):
        GameRoom = apps.get_model("game", "GameRoom")
        room = GameRoom.objects.get(code=self.room_code)
        round = room.current_round
        round.is_completed = True
        round.word_found = word_found
        if winner_id:
            round.winner_id = winner_id
        round.save()

    @database_sync_to_async
    def get_current_round(self):
        GameRoom = apps.get_model("game", "GameRoom")
        try:
            room = GameRoom.objects.get(code=self.room_code)
            return room.current_round
        except GameRoom.DoesNotExist:
            return None

    @database_sync_to_async
    def get_current_round_with_player(self):
        """Récupère le round actuel avec les informations du joueur"""
        GameRoom = apps.get_model("game", "GameRoom")
        try:
            room = GameRoom.objects.get(code=self.room_code)
            round = room.current_round
            if round:
                return {
                    "id": round.id,
                    "phase": round.phase,
                    "word": round.word,
                    "required_clues": round.required_clues,
                    "given_clues": round.given_clues,
                    "given_guesses": round.given_guesses,
                    "can_malus": round.can_malus,
                    "guessing_players": round.guessing_players,
                    "current_player": {
                        "id": str(round.current_player.id),
                        "pseudo": round.current_player.pseudo,
                    },
                }
            return None
        except GameRoom.DoesNotExist:
            return None

    @database_sync_to_async
    def set_player_order(self, player_order):
        """Définit l'ordre dans lequel les joueurs vont jouer"""
        GameRoom = apps.get_model("game", "GameRoom")
        room = GameRoom.objects.get(code=self.room_code)
        room.player_order = player_order
        room.save()
        return room

    @database_sync_to_async
    def get_player_order(self):
        """Récupère l'ordre des joueurs"""
        GameRoom = apps.get_model("game", "GameRoom")
        room = GameRoom.objects.get(code=self.room_code)
        return room.player_order
