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
leaderboard = []

async def broadcast_leaderboard():
    """Send leaderboard updates to all clients"""
    if not clients:
        return
    
    # Sort players by score (highest first)
    sorted_players = sorted(
        [{"id": pid, "score": p["score"], "name": p.get("name", f"Player{pid}")} 
         for pid, p in players.items()],
        key=lambda x: x["score"],
        reverse=True
    )[:10]  # Top 10
    
    leaderboard_msg = json.dumps({
        "type": "leaderboard",
        "leaderboard": sorted_players
    })
    
    await asyncio.gather(*(client.send(leaderboard_msg) for client in clients), return_exceptions=True)

async def move_bullets():
    while True:
        await asyncio.sleep(0.05)
        for bullet in bullets[:]:
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
                if dist < 18 + 5:
                    # Calculate damage dealt
                    bullet_damage = bullet.get("damage", 1)  # Default to 1 damage
                    health_before = enemy["health"]
                    enemy["health"] -= bullet_damage
                    damage_dealt = health_before - max(0, enemy["health"])  # Can't go negative
                    
                    # Award points based on actual damage dealt (1 point per damage)
                    if bullet["owner"] in players and damage_dealt > 0:
                        players[bullet["owner"]]["score"] = players[bullet["owner"]].get("score", 0) + damage_dealt
                    
                    # If enemy dies, remove it
                    if enemy["health"] <= 0:
                        enemies.remove(enemy)
                    
                    bullets.remove(bullet)
                    
                    # Broadcast updated leaderboard after any score change
                    await broadcast_leaderboard()
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
    
    # Player starts at center with score
    players[player_id] = {
        "x": 400,
        "y": 300,
        "angle": 0,
        "health": 100,
        "score": 0,
        "name": f"Player{player_id}"  # Default name
    }

    print(f"Player {player_id} connected. Total players: {len(players)}")
    
    # Send player their ID and current leaderboard
    await websocket.send(json.dumps({
        "type": "init", 
        "id": player_id,
        "leaderboard": [{"id": pid, "score": p["score"], "name": p.get("name", f"Player{pid}")} 
                        for pid, p in sorted(players.items(), key=lambda x: x[1]["score"], reverse=True)[:10]]
    }))

    try:
        async for message in websocket:
            data = json.loads(message)
            print(f"Received from player {player_id}: {data['type']}")  

            if data["type"] == "move":
                players[player_id]["x"] = data["x"]
                players[player_id]["y"] = data["y"]
                players[player_id]["angle"] = data["angle"]
            
            elif data["type"] == "set_name":
                # Allow player to set custom name
                players[player_id]["name"] = data["name"][:15]  # Limit length
                await broadcast_leaderboard()
            
            elif data["type"] == "chat":
                print(f"📨 Chat from player {player_id}: {data['message']}")
                
                chat_message = json.dumps({
                    "type": "chat",
                    "playerId": player_id,
                    "playerName": players[player_id].get("name", f"Player{player_id}"),
                    "message": data["message"]
                })
                
                await asyncio.gather(*(client.send(chat_message) for client in clients))
                
            elif data["type"] == "shoot":
                bullet = data["bullet"]
                bullet["owner"] = player_id
                bullets.append(bullet)
                
            elif data["type"] == "spawn_enemy":
                print(f"🧟 Player {player_id} spawned an enemy")
                enemies.append(data["enemy"])
            
            # Broadcast game state after each message
            game_update = json.dumps({
                "type": "update",
                "players": players,
                "enemies": enemies,
                "bullets": bullets
            })
            await asyncio.gather(*(client.send(game_update) for client in clients))
            
    except websockets.exceptions.ConnectionClosed:
        print(f"Player {player_id} disconnected")
        # Broadcast leaderboard when player leaves
        await broadcast_leaderboard()
    finally:
        if player_id in players:
            del players[player_id]
        clients.remove(websocket)

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
