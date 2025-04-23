# game/consumers.py
import json
from channels.generic.websocket import AsyncWebsocketConsumer


class GameConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.room_code = self.scope["url_route"]["kwargs"]["room_code"]
        self.room_group_name = f"game_{self.room_code}"

        # Rejoindre le salon
        await self.channel_layer.group_add(self.room_group_name, self.channel_name)

        await self.accept()

    async def disconnect(self, close_code):
        # Quitter le salon
        await self.channel_layer.group_discard(self.room_group_name, self.channel_name)

    # Recevoir un message depuis WebSocket
    async def receive(self, text_data):
        text_data_json = json.loads(text_data)
        message = text_data_json.get("message")

        # Envoyer le message à tous les joueurs du salon
        await self.channel_layer.group_send(
            self.room_group_name, {"type": "game_message", "message": message}
        )

    # Recevoir un message du groupe
    async def game_message(self, event):
        message = event["message"]

        # Envoyer le message au WebSocket
        await self.send(text_data=json.dumps({"message": message}))
