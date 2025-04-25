import json
import uuid
from channels.generic.websocket import AsyncWebsocketConsumer


class GameConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.room_code = self.scope["url_route"]["kwargs"]["room_code"]
        self.room_group_name = f"game_{self.room_code}"

        # Initialiser les infos du joueur (remplies plus tard via un message "init")
        self.player_id = None
        self.pseudo = None

        # Ajouter le joueur au groupe
        await self.channel_layer.group_add(self.room_group_name, self.channel_name)

        # Accepter la connexion WebSocket
        await self.accept()

        # Envoyer un message de bienvenue
        await self.send(
            text_data=json.dumps(
                {
                    "type": "welcome",
                    "message": f"Bienvenue dans la room {self.room_code} !",
                }
            )
        )

    async def disconnect(self, close_code):
        if self.pseudo:  # seulement si l'utilisateur s'est bien initialisé
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    "type": "player_left",
                    "player": {"id": self.player_id, "pseudo": self.pseudo},
                },
            )

        await self.channel_layer.group_discard(self.room_group_name, self.channel_name)

    async def receive(self, text_data):
        data = json.loads(text_data)
        msg_type = data.get("type")

        # Message d'initialisation du joueur
        if msg_type == "init":
            self.pseudo = data.get("pseudo")
            self.player_id = str(uuid.uuid4())  # Génère un ID temporaire

            # Notifie les autres joueurs
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    "type": "player_joined",
                    "player": {"id": self.player_id, "pseudo": self.pseudo},
                },
            )

        # Message classique
        elif msg_type == "message":
            message = data.get("message")
            if message and self.pseudo:
                await self.channel_layer.group_send(
                    self.room_group_name,
                    {
                        "type": "game_message",
                        "message": message,
                        "player": {"id": self.player_id, "pseudo": self.pseudo},
                    },
                )

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
