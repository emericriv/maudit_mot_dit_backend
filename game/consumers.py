import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.apps import apps


class GameConsumer(AsyncWebsocketConsumer):

    @database_sync_to_async
    def get_room_players(self):
        GameRoom = apps.get_model("game", "GameRoom")
        room = GameRoom.objects.get(code=self.room_code)
        return [
            {"id": str(player.id), "pseudo": player.pseudo, "is_owner": player.is_owner}
            for player in room.players.all()
        ]

    async def connect(self):
        self.room_code = self.scope["url_route"]["kwargs"]["room_code"]
        self.room_group_name = f"game_{self.room_code}"

        # Vérifier si la room existe
        room = await self.get_room()
        if not room:
            await self.close()
            return

        await self.channel_layer.group_add(self.room_group_name, self.channel_name)
        await self.accept()

        players = await self.get_room_players()
        await self.send(json.dumps({"type": "room_state", "players": players}))

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

    async def receive(self, text_data):
        data = json.loads(text_data)
        msg_type = data.get("type")

        if msg_type == "init":
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

            # Envoyer un message de bienvenue
            await self.send(
                json.dumps(
                    {
                        "type": "welcome",
                        "message": f"Bienvenue dans la room {self.room_code} !",
                    }
                )
            )

            # Notifier les autres joueurs
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

        elif msg_type == "message" and self.pseudo:
            message = data.get("message")
            if message:
                await self.channel_layer.group_send(
                    self.room_group_name,
                    {
                        "type": "game_message",
                        "message": message,
                        "player": {"id": self.player_id, "pseudo": self.pseudo},
                    },
                )

    async def disconnect(self, close_code):
        if self.pseudo:
            # Notifier les autres joueurs du départ
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
        await self.channel_layer.group_discard(self.room_group_name, self.channel_name)

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
