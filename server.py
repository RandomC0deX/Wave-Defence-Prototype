#for later: import struct
import websockets
import asyncio
import json
import os
import math
import random

players = {}
next_player_id = 1
clients = set()

enemies = []
walls = []
bullets = []

async def move_bullets():
    while True:
        await asyncio.sleep(0.05)   # 20 updates per second
        for bullet in bullets[:]:
            # Time‑based movement 
            bullet["x"] += bullet["vx"] * 0.05
            bullet["y"] += bullet["vy"] * 0.05

            # Out of bounds
            if (bullet["x"] < 0 or bullet["x"] > 2000 or
                bullet["y"] < 0 or bullet["y"] > 2000):
                bullets.remove(bullet)
                continue

            # Enemy collisions
            for enemy in enemies[:]:
                dist = math.hypot(bullet["x"] - enemy["x"], bullet["y"] - enemy["y"])
                if dist < 18 + 5:   # ENEMY_SIZE + BULLET_SIZE
                    enemy["health"] -= 1
                    bullets.remove(bullet)
                    if enemy["health"] <= 0:
                        enemies.remove(enemy)
                    break

# Enemy movement and collision task
async def move_enemies():
    while True:
        await asyncio.sleep(0.05)  # 20 updates per second
        
        # Move enemies toward closest player
        if enemies and players:
            for enemy in enemies:
                closest_player = None
                closest_dist = float('inf')
                
                for player_id, player in players.items():
                    dist = math.sqrt((enemy["x"] - player["x"])**2 + (enemy["y"] - player["y"])**2)
                    if dist < closest_dist:
                        closest_dist = dist
                        closest_player = player
                
                if closest_player and closest_dist > 1:
                    dx = closest_player["x"] - enemy["x"]
                    dy = closest_player["y"] - enemy["y"]
                    dist = math.sqrt(dx*dx + dy*dy)
                    
                    enemy["x"] += (dx / dist) * 1.5
                    enemy["y"] += (dy / dist) * 1.5
        
        # Check enemy-to-enemy collision (push apart)
        for i in range(len(enemies)):
            for j in range(i + 1, len(enemies)):
                e1 = enemies[i]
                e2 = enemies[j]
                
                dx = e1["x"] - e2["x"]
                dy = e1["y"] - e2["y"]
                dist = math.sqrt(dx*dx + dy*dy)
                
                if dist < 36:  # 2 * ENEMY_SIZE
                    # Push enemies apart
                    if dist == 0:
                        angle = random.random() * math.pi * 2
                        push_x = math.cos(angle) * 2
                        push_y = math.sin(angle) * 2
                    else:
                        push_x = (dx / dist) * 2
                        push_y = (dy / dist) * 2
                    
                    e1["x"] += push_x
                    e1["y"] += push_y
                    e2["x"] -= push_x
                    e2["y"] -= push_y
        
        # Check player-enemy collisions
        for enemy in enemies[:]:  # Copy list to safely modify
            for player_id, player in list(players.items())[:]:  # Copy players dict
                dist = math.sqrt((enemy["x"] - player["x"])**2 + 
                                (enemy["y"] - player["y"])**2)
                if dist < 18 + 20:  # ENEMY_SIZE + PLAYER_SIZE (20)
                    print(f"💥 Enemy hit player {player_id}!")
                    
                    # Reduce player health
                    player["health"] -= 20
                    
                    # Remove enemy on hit
                    enemies.remove(enemy)
                    
                    # Check if player died
                    if player["health"] <= 0:
                        print(f"💀 Player {player_id} died!")
                        # Respawn player
                        player["x"] = 400
                        player["y"] = 300
                        player["health"] = 100
                    
                    break  # Enemy is gone, stop checking
        
        # Broadcast updated positions
        if clients:
            game_update = json.dumps({
                "type": "update",
                "players": players,
                "enemies": enemies,
                "bullets": bullets
            })
            await asyncio.gather(*(client.send(game_update) for client in clients))

async def handle_client(websocket):
    global next_player_id
    player_id = next_player_id
    next_player_id += 1
    clients.add(websocket)
    
    # Player starts at center
    players[player_id] = {
        "x": 400,
        "y": 300,
        "angle": 0,
        "health": 100,
        "score": 0
    }

    print(f"Player {player_id} connected. Total players: {len(players)}")
    
    # Send player their ID
    await websocket.send(json.dumps({
        "type": "init", 
        "id": player_id
    }))

    try:
        async for message in websocket:
            data = json.loads(message)
            print(f"Received from player {player_id}: {data}")  

            if data["type"] == "move":
                players[player_id]["x"] = data["x"]
                players[player_id]["y"] = data["y"]
                players[player_id]["angle"] = data["angle"]
            
            elif data["type"] == "chat":
                print(f"📨 Chat from player {player_id}: {data['message']}")
                
                chat_message = json.dumps({
                    "type": "chat",
                    "playerId": player_id,
                    "message": data["message"]
                })
                
                await asyncio.gather(*(client.send(chat_message) for client in clients))
                print(f"✅ Chat broadcast complete")
                
            elif data["type"] == "shoot":
                
                # Add bullet to server's list
                bullet = data["bullet"]
                bullet["owner"] = player_id
                bullets.append(bullet)
                
                # Broadcast bullet to all clients 
                bullet_msg = json.dumps({
                    "type": "bullet",
                    "playerId": player_id,
                    "bullet": bullet
                })
                await asyncio.gather(*(client.send(bullet_msg) for client in clients))
                
            elif data["type"] == "spawn_enemy":
                print(f"🧟 Player {player_id} spawned an enemy at ({data['enemy']['x']}, {data['enemy']['y']})")
                print(f"Current enemy count: {len(enemies)}")
                enemies.append(data["enemy"])
                print(f"New enemy count: {len(enemies)}")
            
            # Broadcast game state after each message
            game_update = json.dumps({
                "type": "update",
                "players": players,
                "enemies": enemies,
                "bullets": bullets
            })
            await asyncio.gather(*(client.send(game_update) for client in clients))
            print(f"Broadcasting update with {len(enemies)} enemies")
            
    except websockets.exceptions.ConnectionClosed:
        print(f"Player {player_id} disconnected")
    finally:
        if player_id in players:
            del players[player_id]
        clients.remove(websocket)
        print(f"Player {player_id} removed. Total players: {len(players)}")

async def main():
    port = int(os.environ.get('PORT', 10000))
    
    print(f"🚀 Starting server on port {port}...")
    
    # Start movement tasks
    asyncio.create_task(move_enemies())
    asyncio.create_task(move_bullets())
    
    async with websockets.serve(handle_client, "0.0.0.0", port):
        print(f"✅ WebSocket server started on port {port}")
        print("🌐 Connect at: wss://project-rts.onrender.com")
        await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())
