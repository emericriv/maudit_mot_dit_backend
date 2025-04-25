# 🎮 Maudit Mot Dit - Backend

Ce backend repose sur **Django**, **Django REST Framework** et **Django Channels** avec WebSockets pour la communication en temps réel.

---

## 🛠️ Installation

1. Clone ce repo et place-toi dans le dossier `backend/`
2. Crée et active un environnement virtuel :
   ```bash
   python -m venv venv
   source venv/bin/activate  # ou venv\Scripts\activate sous Windows
   ```
3. Installe les dépendances :
   ```bash
   pip install -r requirements.txt
   ```

---

## ⚙️ Configuration

1. Crée un fichier `.env` si besoin (selon ton usage)
2. Ajoute les clés nécessaires dans `core/settings.py`
3. Installe et lance **Redis** (nécessaire pour les WebSockets) :
   ```bash
   redis-server
   ```

---

## 🚀 Lancement

### Serveur ASGI avec Daphne (requis pour Channels) :
```bash
daphne -p 8000 core.asgi:application
```

---

## 📦 API REST

- `/api/game/create-room/` : Création de salle
- `/api/game/join-room/` : Rejoindre une salle

Toutes les routes sont accessibles en JSON via axios côté frontend.

---

## 🌐 WebSockets

- Endpoint : `ws://localhost:8000/ws/game/<room_code>/`
- Gère la connexion en temps réel, les messages, les départs, etc.

---

## ✅ Dépendances principales

- Django
- djangorestframework
- django-channels
- redis
- django-cors-headers
