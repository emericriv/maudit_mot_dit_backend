# Generated by Django 5.2 on 2025-05-10 08:36

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('game', '0004_remove_gameroom_game_state'),
    ]

    operations = [
        migrations.AddField(
            model_name='round',
            name='all_guesses',
            field=models.JSONField(default=list),
        ),
    ]
