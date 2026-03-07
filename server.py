# for later: import struct
import websockets
import asyncio
import json
import os
import math
import random
import time

players = {}
next_player_id = 1
clients = set()

enemies = []
bullets = []
enemy_bullets = []

# Waves
wave_number = 0
wave_active = False
sub_wave_index = 0
enemies_spawned_this_wave = 0

WAVE_CONFIG = {
    1: [
        {"count": 5, "threshold": 0, "type": "normal"},       
        {"count": 5, "threshold": 2, "type": "fast"}    
    ],
    2: [
        {"count": 5, "threshold": 0, "type": "normal"},
        {"count": 2, "threshold": 3, "type": "explosive"},
        {"count": 3, "threshold": 2, "type": "fast"}
    ],
    3: [
        {"count": 5, "threshold": 0, "type": "normal"},
        {"count": 2, "threshold": 5, "type": "tank"},
        {"count": 5, "threshold": 5, "type": "fast"}
    ],
    4: [
        {"count": 4, "threshold": 0, "type": "shooter"},
        {"count": 1, "threshold": 0, "type": "tank"},
        {"count": 5, "threshold": 3, "type": "fast"}
    ],
    5:[
        {"count": 4, "threshold": 0, "type": "normal"},
        {"count": 5, "threshold": 0, "type": "shooter"},
        {"count": 5, "threshold": 5, "type": "fast"},
        {"count": 3, "threshold": 2, "type": "explosive"},
        {"count": 1, "threshold": 0, "type": "boss"}
    ]
}

# Enemy Types - speeds in pixels per second
ENEMY_TYPES = {
    "normal": {"health": 15, "size": 18, "speed": 100, "color": "#8B0000", "score": 10, "damage": 12},
    "fast": {"health": 5, "size": 15, "speed": 180, "color": "#FF6600", "score": 15, "damage": 8},
    "tank": {"health": 50, "size": 25, "speed": 60, "color": "#800080", "score": 25, "damage": 25},
    "boss": {"health": 160, "size": 40, "speed": 40, "color": "#FFD700", "score": 100, "damage": 40},
    "explosive": {"health": 1, "size": 20, "speed": 200, "color": "#FF4444", "score": 20, "damage": 30},
    "shooter": {"health": 15, "size": 20, "speed": 80, "color": "#00FFFF", "score": 25, "damage": 8, "shoot_cooldown": 2.0},
    "boss_projectile": {"health": 1, "size": 10, "speed": 150, "color": "#FF00FF", "score": 0, "damage": 15},
}

# Optimization constants
GRID_SIZE = 100
ENEMY_UPDATE_RATE = 0.03  # ~33 FPS
BULLET_UPDATE_RATE = 0.02  # 50 FPS
BROADCAST_RATE = 0.05  # 20 FPS

# Spatial grid functions
def get_grid_cell(x, y):
    return (int(x // GRID_SIZE), int(y // GRID_SIZE))

def build_spatial_grid():
    grid = {}
    for enemy in enemies:
        cell = get_grid_cell(enemy["x"], enemy["y"])
        if cell not in grid:
            grid[cell] = []
        grid[cell].append(enemy)
    return grid

def get_nearby_enemies(grid, enemy, radius=50):
    """Get all enemies in nearby grid cells"""
    x, y = enemy["x"], enemy["y"]
    center_cell = get_grid_cell(x, y)
    nearby = []
    
    # Check the 3x3 grid around the enemy
    for dx in [-1, 0, 1]:
        for dy in [-1, 0, 1]:
            cell = (center_cell[0] + dx, center_cell[1] + dy)
            if cell in grid:
                for other in grid[cell]:
                    if other != enemy:
                        nearby.append(other)
    return nearby

async def enemy_shooters():
    while True:
        await asyncio.sleep(0.1) 
        
        current_time = time.time()
        
        for enemy in enemies[:]:
            if enemy.get("type") != "shooter":
                continue
                
            last_shot = enemy.get("last_shot_time", 0)
            shoot_cooldown = enemy.get("shoot_cooldown", 2.0)
            
            if current_time - last_shot < shoot_cooldown:
                continue
                
            closest_player = None
            closest_dist = float('inf')
            
            for player in players.values():
                if player.get("ghost", False) or player.get("dead", False):
                    continue
                    
                dist = math.hypot(enemy["x"] - player["x"], enemy["y"] - player["y"])
                if dist < 400 and dist < closest_dist: 
                    closest_dist = dist
                    closest_player = player
            
            if closest_player:
                dx = closest_player["x"] - enemy["x"]
                dy = closest_player["y"] - enemy["y"]
                dist = math.hypot(dx, dy)
                
                if dist > 0:
                    enemy_bullet = {
                        "id": f"enemy_bullet_{current_time}_{random.randint(1000,9999)}",
                        "x": enemy["x"],
                        "y": enemy["y"],
                        "vx": (dx / dist) * 150, 
                        "vy": (dy / dist) * 150,
                        "damage": enemy.get("damage", 8),
                        "created_at": current_time,
                        "owner": "enemy",
                        "color": "#FF00FF",
                        "size": 8
                    }
                    enemy_bullets.append(enemy_bullet)
                    enemy["last_shot_time"] = current_time

async def move_enemy_bullets():
    last_time = time.time()
    BULLET_LIFETIME = 3
    
    while True:
        await asyncio.sleep(0.02)
        current_time = time.time()
        delta_time = current_time - last_time
        last_time = current_time
        
        for bullet in enemy_bullets[:]:
            bullet["x"] += bullet["vx"] * delta_time
            bullet["y"] += bullet["vy"] * delta_time
            
            if (bullet["x"] < 0 or bullet["x"] > 2000 or
                bullet["y"] < 0 or bullet["y"] > 2000):
                enemy_bullets.remove(bullet)
                continue
            
            if current_time - bullet["created_at"] > BULLET_LIFETIME:
                enemy_bullets.remove(bullet)
                continue

            for player_id, player in list(players.items()):
                if player.get("ghost", False) or player.get("dead", False):
                    continue
                    
                dist = math.hypot(bullet["x"] - player["x"], bullet["y"] - player["y"])
                if dist < 25: 
                    player["health"] -= bullet["damage"]
                    if bullet in enemy_bullets:
                        enemy_bullets.remove(bullet)
                    
                    if player["health"] <= 0:
                        print(f"💀 Player {player_id} killed by enemy projectile!")
                        player["dead"] = True
                        player["health"] = 0
                        player["ghost"] = True
                        
                        death_msg = json.dumps({
                            "type": "death",
                            "playerId": player_id,
                            "x": player["x"],
                            "y": player["y"]
                        })
                        await asyncio.gather(*(client.send(death_msg) for client in clients), return_exceptions=True)
                        await broadcast_leaderboard()
                    break

async def boss_attacks():
    """Handle boss special abilities"""
    while True:
        await asyncio.sleep(0.5)
        
        for enemy in enemies[:]:
            if enemy.get("type") != "boss":
                continue
                
            current_time = time.time()
            boss_health = enemy["health"]
            max_health = enemy["max_health"]
            health_percent = boss_health / max_health
            
            if health_percent > 0.66:
                if current_time - enemy.get("last_minion_time", 0) > 5:
                    angle = random.uniform(0, math.pi * 2)
                    distance = 100
                    minion_x = enemy["x"] + math.cos(angle) * distance
                    minion_y = enemy["y"] + math.sin(angle) * distance
                    
                    await spawn_enemy(minion_x, minion_y, "fast")
                    enemy["last_minion_time"] = current_time
                    print("👾 Boss spawned a minion!")

            elif health_percent > 0.33:
                if current_time - enemy.get("last_ring_time", 0) > 3:
                    for i in range(8):
                        angle = (i / 8) * math.pi * 2
                        bullet = {
                            "id": f"boss_bullet_{current_time}_{i}",
                            "x": enemy["x"],
                            "y": enemy["y"],
                            "vx": math.cos(angle) * 120,
                            "vy": math.sin(angle) * 120,
                            "damage": 10,
                            "created_at": current_time,
                            "owner": "enemy",
                            "color": "#FF4444",
                            "size": 8
                        }
                        enemy_bullets.append(bullet)
                    enemy["last_ring_time"] = current_time
                    print("💥 Boss fired ring of bullets!")
            
            else:
                enemy["speed"] = 80 
                
                if current_time - enemy.get("last_rapid_time", 0) > 0.5:
                    closest_player = None
                    closest_dist = float('inf')
                    
                    for player in players.values():
                        if player.get("ghost", False) or player.get("dead", False):
                            continue
                        dist = math.hypot(enemy["x"] - player["x"], enemy["y"] - player["y"])
                        if dist < closest_dist:
                            closest_dist = dist
                            closest_player = player
                    
                    if closest_player:
                        dx = closest_player["x"] - enemy["x"]
                        dy = closest_player["y"] - enemy["y"]
                        dist = math.hypot(dx, dy)
                        
                        if dist > 0:
                            for i in range(-1, 2):
                                spread = i * 0.2
                                bullet = {
                                    "id": f"boss_rapid_{current_time}_{i}",
                                    "x": enemy["x"],
                                    "y": enemy["y"],
                                    "vx": (dx / dist + spread) * 180,
                                    "vy": (dy / dist + spread) * 180,
                                    "damage": 15,
                                    "created_at": current_time,
                                    "owner": "enemy",
                                    "color": "#FFAA00",
                                    "size": 10
                                }
                                enemy_bullets.append(bullet)
                    enemy["last_rapid_time"] = current_time

async def spawn_enemy(x, y, enemy_type="normal"):
    global sub_wave_index
    enemy_config = ENEMY_TYPES[enemy_type]
    
    enemy = {
        "id": f"enemy_{wave_number}_{sub_wave_index}_{len(enemies)}_{random.randint(1000,9999)}",
        "x": x,
        "y": y,
        "health": enemy_config["health"],
        "max_health": enemy_config["health"],
        "size": enemy_config["size"],
        "speed": enemy_config["speed"],
        "type": enemy_type,
        "color": enemy_config["color"],
        "score_value": enemy_config["score"],
        "damage": enemy_config["damage"],
        "spawn_time": time.time(),
        "last_damage_time": 0
    }
    enemies.append(enemy)
    
    spawn_msg = json.dumps({
        "type": "enemy_spawn",
        "enemy": enemy
    })
    await asyncio.gather(*(client.send(spawn_msg) for client in clients), return_exceptions=True)

async def spawn_sub_wave(sub_wave_idx):
    global sub_wave_index, enemies_spawned_this_wave
    
    if wave_number not in WAVE_CONFIG:
        return
        
    wave = WAVE_CONFIG[wave_number]
    if sub_wave_idx >= len(wave):
        return
        
    sub_wave = wave[sub_wave_idx]
    enemy_count = sub_wave["count"]
    enemy_type = sub_wave.get("type", "normal")
    is_boss = sub_wave.get("boss", False)
    
    print(f"  ↳ Sub-wave {sub_wave_idx + 1}: {enemy_count} {enemy_type.upper()} enemies")
    
    if is_boss:
        center_x, center_y = 1000, 1000
        if players:
            player_positions = list(players.values())
            center_x = sum(p["x"] for p in player_positions) / len(player_positions)
            center_y = sum(p["y"] for p in player_positions) / len(player_positions)
        
        await spawn_enemy(center_x, center_y, enemy_type)
        
        boss_msg = json.dumps({
            "type": "boss_spawn",
            "wave": wave_number
        })
        await asyncio.gather(*(client.send(boss_msg) for client in clients), return_exceptions=True)
        
    else:
        for i in range(enemy_count):
            if players:
                target_player = random.choice(list(players.values()))
                base_x = target_player["x"]
                base_y = target_player["y"]
            else:
                base_x, base_y = 1000, 1000
            
            angle = (i / enemy_count) * math.pi * 2 + random.uniform(-0.3, 0.3)
            distance = 350 + random.uniform(-50, 50)
            
            enemy_x = base_x + math.cos(angle) * distance
            enemy_y = base_y + math.sin(angle) * distance
            
            enemy_x = max(50, min(1950, enemy_x))
            enemy_y = max(50, min(1950, enemy_y))
            
            await spawn_enemy(enemy_x, enemy_y, enemy_type)
            
            if i % 3 == 0:
                await asyncio.sleep(0.02)
    
    sub_wave_index = sub_wave_idx
    enemies_spawned_this_wave += enemy_count

async def start_next_wave():
    global wave_number, wave_active, sub_wave_index, enemies_spawned_this_wave
    
    wave_number += 1
    wave_active = True
    sub_wave_index = 0
    enemies_spawned_this_wave = 0
    
    print(f"\n🌊 WAVE {wave_number} STARTED! 🌊")
    
    wave_msg = json.dumps({
        "type": "wave_start",
        "wave": wave_number
    })
    await asyncio.gather(*(client.send(wave_msg) for client in clients), return_exceptions=True)
    
    if wave_number in WAVE_CONFIG:
        await spawn_sub_wave(0)

async def wave_manager():
    global wave_active, sub_wave_index, wave_number
    
    wave_cooldown = False
    
    while True:
        await asyncio.sleep(0.5)
        
        if players and not wave_active and not wave_cooldown and len(players) > 0:
            await start_next_wave()
        
        if wave_active and wave_number in WAVE_CONFIG:
            wave = WAVE_CONFIG[wave_number]
            current_enemy_count = len(enemies)
            
            if sub_wave_index + 1 < len(wave):
                next_sub_wave = wave[sub_wave_index + 1]
                threshold = next_sub_wave["threshold"]
                
                if current_enemy_count <= threshold:
                    print(f"  Enemy count {current_enemy_count} <= threshold {threshold}, spawning next sub-wave")
                    await spawn_sub_wave(sub_wave_index + 1)
            
            if current_enemy_count == 0 and sub_wave_index + 1 >= len(wave):
                wave_active = False
                wave_cooldown = True
                
                wave_bonus = wave_number * 100
                print(f"✅ Wave {wave_number} COMPLETE! Bonus: {wave_bonus} points")
                
                for player in players.values():
                    player["score"] = player.get("score", 0) + wave_bonus
                    
                    if player.get("ghost", False):
                        player["ghost"] = False
                        player["dead"] = False
                        player["health"] = 100
                        player["x"] = random.randint(100, 1900)
                        player["y"] = random.randint(100, 1900)
                
                wave_msg = json.dumps({
                    "type": "wave_end",
                    "wave": wave_number,
                    "bonus": wave_bonus
                })
                await asyncio.gather(*(client.send(wave_msg) for client in clients), return_exceptions=True)
                
                await asyncio.sleep(5)
                wave_cooldown = False

async def broadcast_leaderboard():
    if not clients:
        return
    
    sorted_players = sorted(
        [{"id": pid, "score": p.get("score", 0), "name": p.get("name", f"Player{pid}")} 
         for pid, p in players.items()],
        key=lambda x: x["score"],
        reverse=True
    )[:10]
    
    leaderboard_msg = json.dumps({
        "type": "leaderboard",
        "leaderboard": sorted_players
    })
    
    await asyncio.gather(*(client.send(leaderboard_msg) for client in clients), return_exceptions=True)

async def move_bullets():
    last_time = time.time()
    BULLET_LIFETIME = 5
    
    while True:
        await asyncio.sleep(BULLET_UPDATE_RATE)
        current_time = time.time()
        delta_time = current_time - last_time
        last_time = current_time
        
        for bullet in bullets[:]:  # Note the [:] to create a copy while iterating
            bullet["x"] += bullet["vx"] * delta_time
            bullet["y"] += bullet["vy"] * delta_time

            # Check bounds
            if (bullet["x"] < 0 or bullet["x"] > 2000 or
                bullet["y"] < 0 or bullet["y"] > 2000):
                bullets.remove(bullet)
                continue
            
            # Check lifetime
            if current_time - bullet.get('createdAt', current_time) > BULLET_LIFETIME:
                bullets.remove(bullet)
                continue

            # Check collisions with enemies
            for enemy in enemies[:]:
                dist = math.hypot(bullet["x"] - enemy["x"], bullet["y"] - enemy["y"])
                if dist < enemy.get("size", 18) + 5:
                    bullet_damage = bullet.get("damage", 5)
                    health_before = enemy["health"]
                    enemy["health"] -= bullet_damage
                    damage_dealt = health_before - max(0, enemy["health"])
                    
                    if bullet["owner"] in players and damage_dealt > 0:
                        players[bullet["owner"]]["score"] = players[bullet["owner"]].get("score", 0) + damage_dealt
                    
                    if bullet in bullets:
                        bullets.remove(bullet)
                    
                    if enemy["health"] <= 0:
                        enemies.remove(enemy)
                    
                    await broadcast_leaderboard()
                    break

async def move_enemies():
    last_time = time.time()
    
    while True:
        await asyncio.sleep(ENEMY_UPDATE_RATE)
        current_time = time.time()
        delta_time = current_time - last_time
        last_time = current_time
        
        if not enemies or not players:
            continue
        
        # Build spatial grid for this frame
        grid = build_spatial_grid()
        
        # Handle enemy-to-enemy collisions using spatial grid
        processed_pairs = set()
        
        for enemy in enemies:
            enemy_size = enemy.get("size", 18)
            nearby_enemies = get_nearby_enemies(grid, enemy, enemy_size * 2)
            
            for other in nearby_enemies:
                pair_id = f"{id(enemy)}-{id(other)}" if id(enemy) < id(other) else f"{id(other)}-{id(enemy)}"
                if pair_id in processed_pairs:
                    continue
                processed_pairs.add(pair_id)
                
                dx = enemy["x"] - other["x"]
                dy = enemy["y"] - other["y"]
                dist_sq = dx*dx + dy*dy
                
                if dist_sq == 0:
                    continue
                    
                dist = math.sqrt(dist_sq)
                size1 = enemy_size
                size2 = other.get("size", 18)
                min_dist = size1 + size2
                
                if dist < min_dist:
                    overlap = min_dist - dist
                    push_x = (dx / dist) * (overlap * 0.5)
                    push_y = (dy / dist) * (overlap * 0.5)
                    
                    new_enemy_x = enemy["x"] + push_x
                    new_enemy_y = enemy["y"] + push_y
                    new_other_x = other["x"] - push_x
                    new_other_y = other["y"] - push_y
                    
                    enemy_can_move = True
                    other_can_move = True
                    
                    for player in players.values():
                        if player.get("ghost", False) or player.get("dead", False):
                            continue
                        player_size = 20
                        
                        if math.hypot(new_enemy_x - player["x"], new_enemy_y - player["y"]) < size1 + player_size:
                            enemy_can_move = False
                        if math.hypot(new_other_x - player["x"], new_other_y - player["y"]) < size2 + player_size:
                            other_can_move = False
                    
                    if enemy_can_move:
                        enemy["x"] = new_enemy_x
                        enemy["y"] = new_enemy_y
                    if other_can_move:
                        other["x"] = new_other_x
                        other["y"] = new_other_y
        
        # Move enemies toward closest player
        for enemy in enemies:
            enemy_speed = enemy.get("speed", 100) * delta_time
            enemy_size = enemy.get("size", 18)
            
            closest_player = None
            closest_dist_sq = float('inf')
            
            for player in players.values():
                # Skip dead or ghost players - enemies ignore them
                if player.get("dead", False) or player.get("ghost", False) or player.get("health", 0) <= 0:
                    continue

                dx = enemy["x"] - player["x"]
                dy = enemy["y"] - player["y"]
                dist_sq = dx*dx + dy*dy
                if dist_sq < closest_dist_sq:
                    closest_dist_sq = dist_sq
                    closest_player = player
            
            if closest_player:
                player_size = 19
                min_distance = enemy_size + player_size
                
                if closest_dist_sq > min_distance * min_distance:
                    dx = closest_player["x"] - enemy["x"]
                    dy = closest_player["y"] - enemy["y"]
                    dist = math.sqrt(closest_dist_sq)
                    
                    move_x = (dx / dist) * enemy_speed
                    move_y = (dy / dist) * enemy_speed
                    
                    new_x = enemy["x"] + move_x
                    new_y = enemy["y"] + move_y
                    new_dist_sq = (closest_player["x"] - new_x)**2 + (closest_player["y"] - new_y)**2
                    
                    if new_dist_sq < min_distance * min_distance:
                        ratio = (dist - min_distance) / dist
                        enemy["x"] += move_x * ratio
                        enemy["y"] += move_y * ratio
                    else:
                        enemy["x"] = new_x
                        enemy["y"] = new_y
        
        # Check player-enemy collisions with damage
        for enemy in enemies[:]:
            enemy_size = enemy.get("size", 18)
            enemy_type = enemy.get("type", "normal")
            last_damage_time = enemy.get("last_damage_time", 0)
            damage_cooldown = 0.5
            
            for player_id, player in list(players.items()):
                # Skip ghosts and dead players - they don't take damage
                if player.get("ghost", False) or player.get("dead", False) or player.get("health", 0) <= 0:
                    continue

                dist = math.hypot(enemy["x"] - player["x"], enemy["y"] - player["y"])
                
                if dist < enemy_size + 20:
                    if current_time - last_damage_time >= damage_cooldown:
                        damage = enemy.get("damage", 10)
                        player["health"] -= damage
                        enemy["last_damage_time"] = current_time
                        
                        if enemy_type == "explosive":
                            for other_id, other_player in players.items():
                                if other_id != player_id and not other_player.get("ghost", False) and not other_player.get("dead", False):
                                    other_dist = math.hypot(enemy["x"] - other_player["x"], enemy["y"] - other_player["y"])
                                    if other_dist < 100:
                                        other_player["health"] -= 20
                            if enemy in enemies:
                                enemies.remove(enemy)
                        
                        if player["health"] <= 0:
                            print(f"💀 Player {player_id} died! Entering ghost mode...")
                            
                            # Mark player as dead and ghost
                            player["dead"] = True
                            player["health"] = 0
                            player["ghost"] = True
                            
                            # Send death notification
                            death_msg = json.dumps({
                                "type": "death",
                                "playerId": player_id,
                                "x": player["x"],
                                "y": player["y"]
                            })
                            await asyncio.gather(*(client.send(death_msg) for client in clients), return_exceptions=True)
                            await broadcast_leaderboard()
                    
                    break

async def handle_client(websocket):
    global next_player_id
    player_id = next_player_id
    next_player_id += 1
    clients.add(websocket)
    
    players[player_id] = {
        "x": 400,
        "y": 300,
        "angle": 0,
        "health": 100,
        "score": 0,
        "dead": False,
        "ghost": False,
        "name": f"Player{player_id}"
    }

    print(f"Player {player_id} connected. Total players: {len(players)}")
    
    await websocket.send(json.dumps({
        "type": "init", 
        "id": player_id,
        "x": players[player_id]["x"], 
        "y": players[player_id]["y"],
        "health": players[player_id]["health"],
        "leaderboard": [{"id": pid, "score": p["score"], "name": p.get("name", f"Player{pid}")} 
                        for pid, p in sorted(players.items(), key=lambda x: x[1]["score"], reverse=True)[:10]]
    }))

    try:
        async for message in websocket:
            data = json.loads(message)
            
            if data["type"] == "move":
                # Ghosts can still move around
                if not players[player_id].get("dead", False) or players[player_id].get("ghost", False):
                    players[player_id]["x"] = data["x"]
                    players[player_id]["y"] = data["y"]
                    players[player_id]["angle"] = data["angle"]
                else:
                    await websocket.send(json.dumps({
                        "type": "position_correction",
                        "x": players[player_id]["x"],
                        "y": players[player_id]["y"]
                    }))
            
            elif data["type"] == "set_name":
                players[player_id]["name"] = data["name"][:15]
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
                # Ghosts cannot shoot
                if not players[player_id].get("ghost", False) and not players[player_id].get("dead", False):
                    bullet = data["bullet"]
                    bullet["owner"] = player_id
                    bullet["createdAt"] = time.time()
                    bullets.append(bullet)
                
            elif data["type"] == "spawn_enemy":
                enemies.append(data["enemy"])
                
            elif data["type"] == "request_respawn":
                if player_id in players and players[player_id].get("ghost", False):
                    # Respawn the player
                    players[player_id]["x"] = random.randint(100, 1900)
                    players[player_id]["y"] = random.randint(100, 1900)
                    players[player_id]["health"] = 100
                    players[player_id]["dead"] = False
                    players[player_id]["ghost"] = False
                    players[player_id]["score"] = max(0, players[player_id].get("score", 0) - 50)
                    
                    print(f"🔄 Player {player_id} respawned")
                    
                    # Broadcast respawn to all clients
                    respawn_msg = json.dumps({
                        "type": "respawn",
                        "playerId": player_id,
                        "x": players[player_id]["x"],
                        "y": players[player_id]["y"],
                        "health": 100
                    })
                    await asyncio.gather(*(client.send(respawn_msg) for client in clients), return_exceptions=True)
                    await broadcast_leaderboard()
                    
            elif data["type"] == "ghost_mode":
                if player_id in players:
                    players[player_id]["ghost"] = data["ghost"]
                    print(f"Player {player_id} ghost mode: {data['ghost']}")
            
    except websockets.exceptions.ConnectionClosed:
        print(f"Player {player_id} disconnected")
        await broadcast_leaderboard()
    finally:
        if player_id in players:
            del players[player_id]
        clients.remove(websocket)
        # Remove player's bullets
        bullets[:] = [b for b in bullets if b.get("owner") != player_id]

async def broadcast_updates():
    while True:
        await asyncio.sleep(BROADCAST_RATE)
        
        if clients:
            broadcast_players = {}
            for pid, p in players.items():
                broadcast_players[pid] = {
                    "x": p["x"],
                    "y": p["y"],
                    "angle": p["angle"],
                    "health": p["health"],
                    "score": p["score"], 
                    "ghost": p.get("ghost", False),
                    "dead": p.get("dead", False),
                    "name": p.get("name", f"Player{pid}")
                }
            
            game_update = json.dumps({
                "type": "update",
                "players": broadcast_players,
                "enemies": enemies,
                "bullets": bullets,
                "enemy_bullets": enemy_bullets
            })
            await asyncio.gather(*(client.send(game_update) for client in clients), return_exceptions=True)

async def main():
    port = int(os.environ.get('PORT', 8080))
    
    print(f"🚀 Starting server on port {port}...")
    print(f"   Enemy update rate: {1/ENEMY_UPDATE_RATE:.0f} FPS")
    print(f"   Bullet update rate: {1/BULLET_UPDATE_RATE:.0f} FPS")
    print(f"   Broadcast rate: {1/BROADCAST_RATE:.0f} FPS")
    
    asyncio.create_task(move_enemies())
    asyncio.create_task(move_bullets())
    asyncio.create_task(wave_manager())
    asyncio.create_task(boss_attacks())
    asyncio.create_task(enemy_shooters())
    asyncio.create_task(broadcast_updates())
    asyncio.create_task(move_enemy_bullets())
    
    async with websockets.serve(handle_client, "0.0.0.0", port):
        print(f"✅ WebSocket server started on port {port}")
        await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())

