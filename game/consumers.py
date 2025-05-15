import json
from math import e
import random
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.apps import apps

from .round_manager import RoundManager
from .timer_manager import RoomTimerManager
from .word_list import WORDS


class GameConsumer(AsyncWebsocketConsumer):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.timer_manager = None

    # --- Méthodes de connexion/déconnexion ---
    async def connect(self):
        self.room_code = self.scope["url_route"]["kwargs"]["room_code"]
        self.room_group_name = f"game_{self.room_code}"
        self.timer_manager = RoomTimerManager.get_instance(self.room_code)
        self.round_manager = RoundManager(self.room_code)

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
        elif msg_type == "timer_end":
            phase = data.get("phase")
            if phase:
                await self.handle_timer_end(phase)
        elif msg_type == "start_new_round":
            await self.start_new_round()

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

        # Crée un nouveau round
        await self.round_manager.start_new_round(first_player)
        # Stocke les choix de mots dans la room
        await self.set_current_word_choices(words)

        # Informe les joueurs
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

        # Met à jour le round avec le mot choisi
        await self.round_manager.update_phase(
            "clue", word=word, required_clues=word_choice["clues"]
        )

        # Informe les joueurs
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                "type": "word_selected",
                "word": word,
                "required_clues": word_choice["clues"],
            },
        )

        await self.switch_timer(60, "clue", self.player_id)

    async def handle_give_clue(self, data):
        clue = data.get("clue")
        if not clue:
            return

        round = await self.round_manager.get_current_round()

        # Vérifie si le clue n'a pas déjà été utilisé comme indice ou comme guess
        if clue.lower() in [c.lower() for c in round.given_clues]:
            await self.send(
                json.dumps({"type": "error", "message": "Cet indice a déjà été donné"})
            )
            return

        if any(guess["word"].lower() == clue.lower() for guess in round.given_guesses):
            await self.send(
                json.dumps(
                    {
                        "type": "error",
                        "message": "Ce mot a déjà été proposé comme réponse, il ne peut pas être utilisé comme indice",
                    }
                )
            )
            return

        # Ajoute l'indice et met à jour la phase
        await self.round_manager.add_clue(clue)
        await self.round_manager.update_phase("guess")

        # Informe les joueurs
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                "type": "clue_given",
                "clue": clue,
                "playerId": self.player_id,
            },
        )

        await self.switch_timer(60, "guess", self.player_id)

    async def handle_make_guess(self, data):
        guess = data.get("guess")
        if not guess:
            return

        # Récupère les informations du round de manière asynchrone
        round_info = await self.round_manager.get_current_round_with_player()
        if not round_info or self.player_id in round_info["guessing_players"]:
            return

        # Ajoute la tentative et met à jour les joueurs ayant deviné
        given_guesses, guessing_players, timestamp = await self.round_manager.add_guess(
            self.player_id, guess
        )

        # Informe tous les joueurs de la tentative
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                "type": "guess_made",
                "playerId": self.player_id,
                "guess": guess,
                "timestamp": timestamp,
                "allGuesses": given_guesses,
            },
        )

        # Vérifie si c'est le bon mot
        if guess.lower() == round_info["word"].lower():
            # Le mot est trouvé
            clues_used = len(round_info["given_clues"])

            # Attribution des points
            points = clues_used
            await self.update_score(self.player_id, points)
            perfect_guess = (
                len(round_info["given_clues"]) == round_info["required_clues"]
            )

            if perfect_guess:
                await self.update_score(round_info["current_player"]["id"], points)

            # Marque le round comme terminé
            await self.round_manager.complete_round(
                word_found=True, winner_id=self.player_id
            )

            # Récupérer les scores mis à jour
            updated_players = await self.get_room_players()

            # Envoyer le message de fin de round
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    "type": "round_complete",
                    "winner": {"id": self.player_id, "pseudo": self.pseudo},
                    "cluesCount": clues_used,
                    "requiredClues": round_info["required_clues"],
                    "word": round_info["word"],
                    "currentPlayer": round_info["current_player"],
                    "perfect": perfect_guess,
                    "players": updated_players,
                },
            )

            # Arrêter le timer
            await self.timer_manager.cancel_timer()

        else:
            # Vérifie si tous les joueurs ont deviné
            all_players = await self.get_room_players()
            non_current_players = [
                p["id"]
                for p in all_players
                if p["id"] != round_info["current_player"]["id"]
            ]

            if len(guessing_players) >= len(non_current_players):
                if len(round_info["given_clues"]) >= round_info["required_clues"]:
                    # Récupérer les informations nécessaires
                    round_info = (
                        await self.round_manager.get_current_round_with_player()
                    )

                    # Marquer le round comme terminé
                    await self.round_manager.complete_round(word_found=False)

                    # Récupérer les scores mis à jour
                    updated_players = await self.get_room_players()

                    # Informer tous les joueurs que le round est terminé sans gagnant
                    await self.channel_layer.group_send(
                        self.room_group_name,
                        {
                            "type": "round_complete",
                            "winner": None,
                            "word": round_info["word"],
                            "cluesCount": len(round_info["given_clues"]),
                            "requiredClues": round_info["required_clues"],
                            "currentPlayer": round_info["current_player"],
                            "perfect": False,
                            "players": updated_players,
                        },
                    )

                    await self.timer_manager.cancel_timer()
                else:
                    await self.round_manager.update_phase("clue")
                    await self.switch_timer(
                        60, "clue", round_info["current_player"]["id"]
                    )

    async def handle_join_game(self):
        round_data = await self.round_manager.get_current_round_with_player()

        if round_data:
            # Récupère les choix de mots actuels
            word_choices = await self.get_current_word_choices()

            # Envoie l'état actuel du jeu au joueur qui rejoint
            await self.send(
                text_data=json.dumps(
                    {
                        "type": "game_started",
                        "currentPlayer": round_data["current_player"]["id"],
                        "wordChoices": word_choices,
                        "timeLeft": 30,  # ou récupérer depuis le timer manager
                        "phase": round_data["phase"],
                        "givenClues": round_data["given_clues"],
                        "guesses": round_data["given_guesses"],
                        "requiredClues": round_data["required_clues"],
                    }
                )
            )

    async def handle_timer_end(self, phase):
        round = await self.round_manager.get_current_round()

        if phase == "choice":
            # Le joueur n'a pas choisi de mot
            await self.start_new_round()
        elif phase == "clue":
            # Le joueur n'a pas donné d'indice
            await self.update_score(round.current_player.id, -round.required_clues)
            await self.start_new_round()
        elif phase == "guess":
            if len(round.given_clues) >= round.required_clues:
                # Récupérer les informations nécessaires
                round_info = await self.round_manager.get_current_round_with_player()

                # Marquer le round comme terminé
                await self.round_manager.complete_round(word_found=False)

                # Récupérer les scores mis à jour
                updated_players = await self.get_room_players()

                # Informer tous les joueurs que le round est terminé sans gagnant
                await self.channel_layer.group_send(
                    self.room_group_name,
                    {
                        "type": "round_complete",
                        "winner": None,
                        "word": round_info["word"],
                        "cluesCount": len(round_info["given_clues"]),
                        "requiredClues": round_info["required_clues"],
                        "currentPlayer": round_info["current_player"],
                        "perfect": False,
                        "players": updated_players,
                    },
                )

                await self.timer_manager.cancel_timer()
            else:
                await self.round_manager.update_phase("clue")
                await self.switch_timer(60, "clue", round.current_player.id)

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
            {
                "id": str(player.id),
                "pseudo": player.pseudo,
                "is_owner": player.is_owner,
                "score": player.score,
            }
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
    def update_score(self, player_id, points):
        Player = apps.get_model("game", "Player")
        player = Player.objects.get(id=player_id)
        player.score = (player.score or 0) + points
        player.save()

    @database_sync_to_async
    def generate_word_choices(self):
        # Sélectionner deux mots différents au hasard
        word1, word2 = random.sample(WORDS, 2)

        # Générer deux nombres d'indices différents entre 1 et 5
        indices_possibles = list(range(1, 6))
        nb_indices1 = random.choice(indices_possibles)
        indices_possibles.remove(nb_indices1)
        nb_indices2 = random.choice(indices_possibles)
        while nb_indices2 == nb_indices1:
            nb_indices2 = random.choice(indices_possibles)

        return {
            "word1": {"word": word1, "clues": nb_indices1},
            "word2": {"word": word2, "clues": nb_indices2},
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
    def set_current_word_choices(self, word_choices):
        GameRoom = apps.get_model("game", "GameRoom")
        room = GameRoom.objects.get(code=self.room_code)
        room.current_word_choices = word_choices
        room.save()

    @database_sync_to_async
    def get_current_word_choices(self):
        GameRoom = apps.get_model("game", "GameRoom")
        try:
            room = GameRoom.objects.get(code=self.room_code)
            return room.current_word_choices
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

    async def word_selected(self, event):
        await self.send(text_data=json.dumps(event))

    async def clue_given(self, event):
        await self.send(text_data=json.dumps(event))

    async def guess_made(self, event):
        await self.send(text_data=json.dumps(event))

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

    async def timer_end(self, event):
        """Gestionnaire pour l'événement timer_end"""
        await self.send(
            text_data=json.dumps({"type": "timer_end", "phase": event["phase"]})
        )

    async def new_round(self, event):
        """Gestionnaire pour l'événement new_round"""
        await self.send(
            text_data=json.dumps(
                {
                    "type": "new_round",
                    "nextPlayer": event["nextPlayer"],
                    "wordChoices": event["wordChoices"],
                    "players": event["players"],
                }
            )
        )

    async def round_complete(self, event):
        """Gestionnaire pour l'événement round_complete"""
        await self.send(text_data=json.dumps(event))

    # === Méthodes utilitaires ===
    async def switch_timer(self, duration, phase, current_player):
        await self.timer_manager.switch_timer(duration, phase, current_player)

    async def start_new_round(self):
        # Récupérer le round actuel avec les infos joueur
        round_info = await self.round_manager.get_current_round_with_player()

        # Choisir le prochain joueur
        players = await self.get_room_players()
        current_player_index = next(
            (
                i
                for i, p in enumerate(players)
                if p["id"] == round_info["current_player"]["id"]
            ),
            0,
        )
        next_player = players[(current_player_index + 1) % len(players)]["id"]

        # Générer de nouveaux mots pour le prochain tour
        new_words = await self.generate_word_choices()

        # Stocker les nouveaux choix de mots
        await self.set_current_word_choices(new_words)

        # Créer un nouveau round pour le prochain joueur
        await self.round_manager.start_new_round(next_player)

        # Récupérer les scores mis à jour
        updated_players = await self.get_room_players()

        # Informer tous les joueurs de la fin du tour
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                "type": "new_round",
                "nextPlayer": next_player,
                "wordChoices": new_words,
                "players": updated_players,
            },
        )
