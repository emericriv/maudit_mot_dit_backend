import json
from math import e
import random
import asyncio
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.apps import apps


class GameConsumer(AsyncWebsocketConsumer):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.timer_task = None
        self.current_timer_id = 0  # Pour suivre les timers actifs

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
        print(f"Received message: {msg_type}")

        if msg_type == "init":
            await self.handle_init(data)
        elif msg_type == "message" and self.pseudo:
            await self.handle_message(data)
        elif msg_type == "start_game":
            await self.handle_start_game()
        elif msg_type == "word_choice":
            await self.handle_word_choice(data)
        elif msg_type == "give_clue":
            await self.handle_give_clue(data)
        elif msg_type == "make_guess":
            await self.handle_make_guess(data)
        elif msg_type == "join_game":
            await self.handle_join_game()

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

        words = await self.generate_word_choices()

        # Stocke l'état du jeu dans la room
        await self.set_game_state(
            {
                "current_player": first_player,
                "time_left": 30,
                "phase": "choice",
                "given_clues": [],
                "required_clues": None,
                "current_word": "",
            }
        )
        await self.set_current_word_choices(words)

        await self.channel_layer.group_send(
            self.room_group_name,
            {
                "type": "start_game",
                "currentPlayer": first_player,
                "wordChoices": words,
                "timeLeft": 30,
            },
        )

        await self.switch_timer(30, "choice", first_player)

    async def handle_word_choice(self, data):
        word = data.get("word")
        if not word:
            return

        word_choice = await self.get_word_choice(word)
        if not word_choice:
            return

        # Met à jour le game_state avec le mot choisi, la phase et le nombre d'indices requis
        game_state = await self.get_game_state()
        game_state["phase"] = "clue"
        game_state["current_word"] = word
        game_state["required_clues"] = word_choice["clues"]
        await self.set_game_state(game_state)

        # Informer tous les joueurs que le mot a été choisi
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                "type": "word_selected",
                "word": word,
                "required_clues": word_choice["clues"],
            },
        )

        # Change le timer pour la nouvelle phase
        await self.switch_timer(60, "clue", game_state["current_player"])

    async def handle_give_clue(self, data):
        clue = data.get("clue")
        if not clue:
            return

        # Vérifier si le clue n'a pas déjà été utilisé
        game_state = await self.get_game_state()
        if clue.lower() in [c.lower() for c in game_state.get("given_clues", [])]:
            return

        # Ajouter l'indice à la liste
        await self.add_clue(clue)

        # Informer tous les joueurs du nouvel indice
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                "type": "clue_given",
                "clue": clue,
                "playerId": self.player_id,
            },
        )

        # Vérifier si tous les indices requis ont été donnés
        if len(game_state.get("given_clues", [])) + 1 >= game_state.get(
            "required_clues", 0
        ):
            # Passer au joueur suivant si personne n'a trouvé
            await self.end_turn()

    async def handle_make_guess(self, data):
        guess = data.get("guess")
        if not guess:
            return

        game_state = await self.get_game_state()
        current_word = game_state.get("current_word", "").lower()

        # Informer tous les joueurs de la tentative
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                "type": "guess_made",
                "playerId": self.player_id,
                "guess": guess,
            },
        )

        # Si le mot est correct
        if guess.lower() == current_word:
            # Calculer les points
            clues_used = len(game_state.get("given_clues", []))
            required_clues = game_state.get("required_clues", 0)

            points = clues_used
            if clues_used <= required_clues:
                # Mettre à jour les scores
                await self.update_score(
                    self.player_id, points
                )  # Points pour celui qui devine
                await self.update_score(
                    game_state["current_player"], points
                )  # Points pour celui qui fait deviner

            # Fin du tour
            await self.end_turn()

    async def handle_join_game(self):
        room = await self.get_room()
        if hasattr(room, "game_state") and room.game_state:
            await self.send(
                text_data=json.dumps(
                    {
                        "type": "game_started",
                        "currentPlayer": room.game_state.get("current_player"),
                        "wordChoices": room.current_word_choices,
                        "timeLeft": room.game_state.get("time_left", 30),
                    }
                )
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

    @database_sync_to_async
    def get_word_choice(self, word):
        GameRoom = apps.get_model("game", "GameRoom")
        room = GameRoom.objects.get(code=self.room_code)
        word_choices = room.current_word_choices
        if word_choices:
            if word == word_choices["word1"]["word"]:
                return word_choices["word1"]
            elif word == word_choices["word2"]["word"]:
                return word_choices["word2"]
        return None

    @database_sync_to_async
    def get_game_state(self):
        GameRoom = apps.get_model("game", "GameRoom")
        room = GameRoom.objects.get(code=self.room_code)
        return room.game_state

    @database_sync_to_async
    def add_clue(self, clue):
        GameRoom = apps.get_model("game", "GameRoom")
        room = GameRoom.objects.get(code=self.room_code)
        game_state = room.game_state or {}
        game_state["given_clues"] = game_state.get("given_clues", []) + [clue]
        room.game_state = game_state
        room.save()

    @database_sync_to_async
    def update_score(self, player_id, points):
        Player = apps.get_model("game", "Player")
        player = Player.objects.get(id=player_id)
        player.score = (player.score or 0) + points
        player.save()

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

    @database_sync_to_async
    def set_game_state(self, state):
        GameRoom = apps.get_model("game", "GameRoom")
        room = GameRoom.objects.get(code=self.room_code)
        room.game_state = state
        room.save()

    @database_sync_to_async
    def set_current_word_choices(self, word_choices):
        GameRoom = apps.get_model("game", "GameRoom")
        room = GameRoom.objects.get(code=self.room_code)
        room.current_word_choices = word_choices
        room.save()

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
        await self.send(
            text_data=json.dumps(
                {
                    "type": "game_started",
                    "currentPlayer": event["currentPlayer"],
                    "wordChoices": event["wordChoices"],
                    "timeLeft": event["timeLeft"],
                }
            )
        )

    async def owner_changed(self, event):
        await self.send(
            text_data=json.dumps({"type": "owner_changed", "player": event["player"]})
        )

    async def end_turn(self):
        # Choisir le prochain joueur
        players = await self.get_room_players()
        current_player_index = next(
            (
                i
                for i, p in enumerate(players)
                if p["id"] == await self.get_current_player()
            ),
            0,
        )
        next_player = players[(current_player_index + 1) % len(players)]["id"]

        # Générer de nouveaux mots pour le prochain tour
        new_words = await self.generate_word_choices()

        # Informer tous les joueurs de la fin du tour
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                "type": "turn_end",
                "nextPlayer": next_player,
                "wordChoices": new_words,
            },
        )

    async def word_selected(self, event):
        await self.send(text_data=json.dumps(event))

    async def clue_given(self, event):
        await self.send(text_data=json.dumps(event))

    async def guess_made(self, event):
        await self.send(text_data=json.dumps(event))

    async def run_timer(self, duration, phase, current_player, timer_id):
        try:
            for t in range(duration, 0, -1):
                # Vérifie si ce timer est toujours le timer actif
                if timer_id != self.current_timer_id:
                    print(f"Timer {timer_id} abandonné")
                    return

                await asyncio.sleep(1)
                await self.channel_layer.group_send(
                    self.room_group_name,
                    {
                        "type": "timer_update",
                        "timeLeft": t,
                        "phase": phase,
                        "currentPlayer": current_player,
                    },
                )
        except asyncio.CancelledError:
            print(f"Timer {timer_id} cancelled")
            return

    async def timer_update(self, event):
        await self.send(
            text_data=json.dumps(
                {
                    "type": "timer_update",
                    "timeLeft": event["timeLeft"],
                    "phase": event["phase"],
                    "currentPlayer": event["currentPlayer"],
                }
            )
        )

    async def switch_timer(self, duration, phase, current_player):
        # Incrémente l'ID du timer pour abandonner l'ancien
        self.current_timer_id += 1
        current_id = self.current_timer_id

        # Annule l'ancien timer
        if self.timer_task and not self.timer_task.done():
            self.timer_task.cancel()
            try:
                await self.timer_task
            except asyncio.CancelledError:
                pass

        # Attend un court instant
        await asyncio.sleep(0.1)

        # Vérifie si un autre timer n'a pas été démarré entre temps
        if current_id != self.current_timer_id:
            return

        # Démarre le nouveau timer
        self.timer_task = asyncio.create_task(
            self.run_timer(duration, phase, current_player, current_id)
        )
