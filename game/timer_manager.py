import asyncio
from channels.layers import get_channel_layer


class RoomTimerManager:
    _instances = {}

    @classmethod
    def get_instance(cls, room_code):
        if room_code not in cls._instances:
            cls._instances[room_code] = cls(room_code)
        return cls._instances[room_code]

    def __init__(self, room_code):
        self.room_code = room_code
        self.room_group_name = f"game_{room_code}"
        self.timer_task = None
        self.current_timer_id = 0

    async def switch_timer(self, duration, phase, current_player):
        self.current_timer_id += 1
        current_id = self.current_timer_id

        if self.timer_task and not self.timer_task.done():
            self.timer_task.cancel()
            try:
                await self.timer_task
            except asyncio.CancelledError:
                pass

        self.timer_task = asyncio.create_task(
            self.run_timer(duration, phase, current_player, current_id)
        )

    async def run_timer(self, duration, phase, current_player, timer_id):
        channel_layer = get_channel_layer()
        try:
            for t in range(duration, 0, -1):
                if timer_id != self.current_timer_id:
                    return

                await asyncio.sleep(1)
                await channel_layer.group_send(
                    self.room_group_name,
                    {
                        "type": "timer_update",
                        "timeLeft": t,
                        "phase": phase,
                        "currentPlayer": current_player,
                    },
                )

            # Timer terminé
            await channel_layer.group_send(
                self.room_group_name,
                {
                    "type": "timer_end",
                    "phase": phase,
                    "currentPlayer": current_player,
                },
            )
        except asyncio.CancelledError:
            print(f"Timer {timer_id} cancelled")
            return
