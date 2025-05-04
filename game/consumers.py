import json
import random
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.apps import apps


class GameConsumer(AsyncWebsocketConsumer):
    # --- Méthodes de connexion/déconnexion ---
    async def connect(self):
        self.room_code = self.scope["url_route"]["kwargs"]["room_code"]
        self.room_group_name = f"game_{self.room_code}"

        room = await self.get_room()
        if not room:
            await self.close()
            return

        await self.channel_layer.group_add(self.room_group_name, self.channel_name)
        await self.accept()

        players = await self.get_room_players()
        await self.send(json.dumps({"type": "room_state", "players": players}))

    async def disconnect(self, close_code):
        if hasattr(self, "pseudo"):
            player = await self.get_player(self.session_id)
            was_owner = player and player.is_owner

            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    "type": "player_left",
                    "player": {
                        "id": self.player_id,
                        "pseudo": self.pseudo,
                    },
                },
            )

            if was_owner:
                new_owner = await self.transfer_ownership()
                if new_owner:
                    await self.channel_layer.group_send(
                        self.room_group_name,
                        {
                            "type": "owner_changed",
                            "player": {
                                "id": str(new_owner.id),
                                "pseudo": new_owner.pseudo,
                                "is_owner": True,
                            },
                        },
                    )

            await self.remove_player()

        await self.channel_layer.group_discard(self.room_group_name, self.channel_name)

    # --- Méthode principale de réception des messages ---
    async def receive(self, text_data):
        data = json.loads(text_data)
        msg_type = data.get("type")

        if msg_type == "init":
            await self.handle_init(data)
        elif msg_type == "message" and self.pseudo:
            await self.handle_message(data)
        elif msg_type == "start_game":
            await self.handle_start_game()
        elif msg_type == "word_choice":
            # Gérer le choix du mot
            pass
        elif msg_type == "give_clue":
            # Gérer les indices donnés
            pass
        elif msg_type == "make_guess":
            # Gérer les tentatives
            pass

    # --- Méthodes de traitement des messages ---
    async def handle_init(self, data):
        session_id = data.get("sessionId")
        if not session_id:
            await self.send(
                json.dumps({"type": "error", "message": "Session ID manquant"})
            )
            return

        player = await self.get_player(session_id)
        if not player:
            await self.send(
                json.dumps({"type": "error", "message": "Session invalide"})
            )
            await self.close()
            return

        self.player_id = str(player.id)
        self.pseudo = player.pseudo
        self.session_id = str(player.session_id)

        await self.send(
            json.dumps(
                {
                    "type": "welcome",
                    "message": f"Bienvenue dans la room {self.room_code} !",
                    "playerId": self.player_id,
                }
            )
        )

        await self.channel_layer.group_send(
            self.room_group_name,
            {
                "type": "player_joined",
                "player": {
                    "id": self.player_id,
                    "pseudo": self.pseudo,
                    "is_owner": player.is_owner,
                },
            },
        )

    async def handle_message(self, data):
        message = data.get("message")
        if message:
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    "type": "lobby_message",
                    "message": message,
                    "player": {"id": self.player_id, "pseudo": self.pseudo},
                },
            )

    async def handle_start_game(self):
        if not hasattr(self, "player_id") or not await self.is_room_owner():
            return

        players = await self.get_room_players()
        first_player = random.choice(players)["id"]

        await self.channel_layer.group_send(
            self.room_group_name,
            {"type": "start_game", "first_player": first_player},
        )

    # --- Méthodes d'accès à la base de données ---
    @database_sync_to_async
    def get_room(self):
        GameRoom = apps.get_model("game", "GameRoom")
        try:
            return GameRoom.objects.get(code=self.room_code)
        except GameRoom.DoesNotExist:
            return None

    @database_sync_to_async
    def get_player(self, session_id):
        Player = apps.get_model("game", "Player")
        try:
            return Player.objects.get(session_id=session_id, room__code=self.room_code)
        except Player.DoesNotExist:
            return None

    @database_sync_to_async
    def get_room_players(self):
        GameRoom = apps.get_model("game", "GameRoom")
        room = GameRoom.objects.get(code=self.room_code)
        return [
            {"id": str(player.id), "pseudo": player.pseudo, "is_owner": player.is_owner}
            for player in room.players.all()
        ]

    @database_sync_to_async
    def is_room_owner(self):
        Player = apps.get_model("game", "Player")
        try:
            player = Player.objects.get(id=self.player_id)
            return player.is_owner
        except Player.DoesNotExist:
            return False

    @database_sync_to_async
    def transfer_ownership(self):
        Player = apps.get_model("game", "Player")
        GameRoom = apps.get_model("game", "GameRoom")
        try:
            room = GameRoom.objects.get(code=self.room_code)
            new_owner = room.players.filter(is_owner=False).first()
            if new_owner:
                room.players.filter(is_owner=True).update(is_owner=False)
                new_owner.is_owner = True
                new_owner.save()
                return new_owner
            return None
        except GameRoom.DoesNotExist:
            return None

    # --- Gestionnaires d'événements ---
    async def game_message(self, event):
        await self.send(
            text_data=json.dumps(
                {
                    "type": "game_message",
                    "message": event["message"],
                    "player": event["player"],
                }
            )
        )

    async def player_joined(self, event):
        await self.send(
            text_data=json.dumps({"type": "player_joined", "player": event["player"]})
        )

    async def player_left(self, event):
        await self.send(
            text_data=json.dumps({"type": "player_left", "player": event["player"]})
        )

    async def lobby_message(self, event):
        await self.send(
            text_data=json.dumps(
                {
                    "type": "lobby_message",
                    "message": event["message"],
                    "player": event["player"],
                }
            )
        )

    async def start_game(self, event):
        words = await self.generate_word_choices()
        await self.send(
            text_data=json.dumps(
                {
                    "type": "game_started",
                    "currentPlayer": event["first_player"],
                    "wordChoices": words,
                }
            )
        )

    async def owner_changed(self, event):
        await self.send(
            text_data=json.dumps({"type": "owner_changed", "player": event["player"]})
        )

    @database_sync_to_async
    def generate_word_choices(self):
        return {
            "word1": {"word": "exemple1", "clues": 3},
            "word2": {"word": "exemple2", "clues": 4},
        }

    @database_sync_to_async
    def remove_player(self):
        Player = apps.get_model("game", "Player")
        try:
            player = Player.objects.get(id=self.player_id)
            player.delete()
        except Player.DoesNotExist:
            pass
