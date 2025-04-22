import uuid
import random
import string

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from .models import GameRoom, Player


def generate_room_code(length=6):
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=length))


class CreateRoomView(APIView):
    def post(self, request):
        pseudo = request.data.get("pseudo")
        if not pseudo:
            return Response(
                {"error": "Pseudo is required"}, status=status.HTTP_400_BAD_REQUEST
            )

        # Générer un code unique
        code = generate_room_code()
        while GameRoom.objects.filter(code=code).exists():
            code = generate_room_code()

        room = GameRoom.objects.create(code=code)
        player = Player.objects.create(
            room=room,
            pseudo=pseudo,
            session_id=uuid.uuid4(),
            is_owner=True,
        )

        return Response(
            {
                "room_code": room.code,
                "session_id": str(player.session_id),
                "player_id": player.id,
                "pseudo": player.pseudo,
            },
            status=status.HTTP_201_CREATED,
        )


class JoinRoomView(APIView):
    def post(self, request):
        code = request.data.get("room_code")
        pseudo = request.data.get("pseudo")

        if not code or not pseudo:
            return Response(
                {"error": "Missing room code or pseudo"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            room = GameRoom.objects.get(code=code)
        except GameRoom.DoesNotExist:
            return Response(
                {"error": "Room not found"}, status=status.HTTP_404_NOT_FOUND
            )

        if Player.objects.filter(room=room, pseudo=pseudo).exists():
            return Response(
                {"error": "Pseudo already taken in this room"},
                status=status.HTTP_409_CONFLICT,
            )

        player = Player.objects.create(
            room=room,
            pseudo=pseudo,
            session_id=uuid.uuid4(),
            is_owner=False,
        )

        return Response(
            {
                "room_code": room.code,
                "session_id": str(player.session_id),
                "player_id": player.id,
                "pseudo": player.pseudo,
            },
            status=status.HTTP_201_CREATED,
        )
