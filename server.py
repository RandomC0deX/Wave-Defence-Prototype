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
enemy_shoot_states = {}

WAVE_CONFIG = {
    1: [
        {"count": 2, "threshold": 0, "type": "mercenary"},
        {"count": 2, "threshold": 1, "type": "fast"}        
    ],
    2: [
        {"count": 3, "threshold": 0, "type": "normal"},
        {"count": 1, "threshold": 2, "type": "tank"}        
    ],
    3: [
        {"count": 3, "threshold": 0, "type": "fast"},
        {"count": 2, "threshold": 1, "type": "explosive"},
        {"count": 3, "threshold": 0, "type": "normal"}        
    ],
    4: [
        {"count": 1, "threshold": 0, "type": "tank"},
        {"count": 2, "threshold": 1, "type": "normal"},
        {"count": 3, "threshold": 0, "type": "fast"}        
    ],
    5: [
        {"count": 3, "threshold": 0, "type": "shooter"},
        {"count": 2, "threshold": 2, "type": "explosive"},
        {"count": 1, "threshold": 0, "type": "mercenary"}   
    ]
}

# Enemy Types
ENEMY_TYPES = {
    "normal": 
       {"health": 15, 
        "size": 18, 
        "speed": 100, 
        "color": 
        "#8B0000", 
        "score": 10, 
        "damage": 12
        },

    "fast": 
        {"health": 5,
          "size": 15, 
          "speed": 180, 
          "color": "#FF6600",
          "score": 15,
          "damage": 8
          },

    "tank": 
        {"health": 50, 
         "size": 25, 
         "speed": 60, 
         "color": "#800080", 
         "score": 25, 
         "damage": 25
         },

    "explosive": 
        {"health": 1, 
        "size": 20, 
        "speed": 200, 
        "color": "#FF4444", 
        "score": 20, 
        "damage": 30
        },

    "shooter": 
        {"health": 15, 
        "size": 20, 
        "speed": 80, 
        "color": "#00FFFF", 
        "score": 25, 
        "damage": 8, 
        "shoot_cooldown": 2.0, 
        "bullet_speed": 150,
        "shoot_pattern": "rapid",
        "burst_count": 3,
        "burst_delay": 0.25,
        "bullet_color": "#00FFFF",
        "bullet_size": 8  
        },
    "orbiter": {
        "health": 25, "size": 22, "speed": 50, "color": "#00FFFF", 
        "score": 35, "damage": 15,
        "category": "ranged",
        "shoot_pattern": "orbit_lock",
        "orbit_bullets": 4,
        "orbit_radius": 70,
        "orbit_speed": 2.0,
        "charge_time": 2.0,
        "bullet_speed": 200,
        "bullet_size": 8,
        "bullet_color": "#00FFFF",
        "recharge_time": 3.0
    },
    "mercenary": {
        "health": 400, 
        "size": 45, 
        "speed": 40, 
        "color": "#FFD700", 
        "score": 150, 
        "damage": 25,
        "max_health": 400,
        "boss": True
    },
    
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
    x, y = enemy["x"], enemy["y"]
    center_cell = get_grid_cell(x, y)
    nearby = []
    
    for dx in [-1, 0, 1]:
        for dy in [-1, 0, 1]:
            cell = (center_cell[0] + dx, center_cell[1] + dy)
            if cell in grid:
                for other in grid[cell]:
                    if other != enemy:
                        nearby.append(other)
    return nearby

async def handle_enemy_shooting():
    """Main handler for all enemy shooting patterns"""
    while True:
        await asyncio.sleep(0.016) 
        current_time = time.time()
        
        for enemy in enemies[:]:
            enemy_type = enemy.get("type", "")
            
            if enemy_type not in ENEMY_TYPES:
                continue
                
            pattern = ENEMY_TYPES[enemy_type].get("shoot_pattern")
            if not pattern:
                continue
            
            enemy_id = enemy["id"]
            if enemy_id not in enemy_shoot_states:
                enemy_shoot_states[enemy_id] = {
                    "pattern": pattern,
                    "last_shot_time": 0,
                    "phase": "idle",
                    "bullets": [],
                    "target": None,
                    "aim_start_time": 0
                }
            
            state = enemy_shoot_states[enemy_id]
            
            if pattern == "orbit_lock":
                await handle_orbit_pattern(enemy, state, current_time)
            elif pattern == "arc":
                await handle_arc_pattern(enemy, state, current_time)
            elif pattern == "rapid":
                await handle_rapid_pattern(enemy, state, current_time)
            elif pattern == "spread":
                await handle_spread_pattern(enemy, state, current_time)
            elif pattern == "laser":
                await handle_laser_pattern(enemy, state, current_time)
            elif pattern == "mortar":
                await handle_mortar_pattern(enemy, state, current_time)
            elif pattern == "homing":
                await handle_homing_pattern(enemy, state, current_time)
            elif pattern == "wave":
                await handle_wave_pattern(enemy, state, current_time)
            elif pattern == "boomerang":
                await handle_boomerang_pattern(enemy, state, current_time)

async def handle_orbit_pattern(enemy, state, current_time):
    """Orbiter: Bullets orbit then lock on"""
    config = ENEMY_TYPES["orbiter"]
    
    if state["phase"] == "idle":
        state["phase"] = "charging"
        state["charge_start"] = current_time
        state["orbit_angle"] = random.uniform(0, math.pi * 2)
        
        state["bullets"] = []
        for i in range(config["orbit_bullets"]):
            state["bullets"].append({
                "id": f"orbit_{enemy['id']}_{i}",
                "index": i,
                "active": True,
                "damage": config["damage"],
                "size": config["bullet_size"],
                "color": config["bullet_color"]
            })
    
    elif state["phase"] == "charging":
        state["orbit_angle"] += config["orbit_speed"] * 0.016
        
        if current_time - state["charge_start"] >= config["charge_time"]:
            target = find_closest_player(enemy["x"], enemy["y"])
            if target:
                state["target"] = target
                state["phase"] = "locked"
                state["lock_time"] = current_time
            
                for i, bullet in enumerate(state["bullets"]):
                    dx = target["x"] - enemy["x"]
                    dy = target["y"] - enemy["y"]
                    dist = math.hypot(dx, dy)
                    if dist > 0:
                        spread = (i - config["orbit_bullets"]/2) * 0.1
                        angle = math.atan2(dy, dx) + spread
                        bullet["vx"] = math.cos(angle) * config["bullet_speed"]
                        bullet["vy"] = math.sin(angle) * config["bullet_speed"]
            else:
                state["phase"] = "idle"
    
    elif state["phase"] == "locked":
        if current_time - state["lock_time"] >= 0.2:
            state["phase"] = "firing"
            state["fire_index"] = 0
            state["last_fire"] = current_time
    
    elif state["phase"] == "firing":
        if state["fire_index"] < len(state["bullets"]):
            if current_time - state["last_fire"] >= 0.1:
                bullet = state["bullets"][state["fire_index"]]
                
                enemy_bullets.append({
                    "id": f"enemy_bullet_{current_time}_{random.randint(1000,9999)}",
                    "x": enemy["x"],
                    "y": enemy["y"],
                    "vx": bullet["vx"],
                    "vy": bullet["vy"],
                    "damage": config["damage"],
                    "created_at": current_time,
                    "owner": "enemy",
                    "color": config["bullet_color"],
                    "size": config["bullet_size"],
                    "pattern": "orbit"
                })
                
                state["fire_index"] += 1
                state["last_fire"] = current_time
        else:
            state["phase"] = "recharge"
            state["recharge_start"] = current_time
    
    elif state["phase"] == "recharge":
        if current_time - state["recharge_start"] >= config["recharge_time"]:
            state["phase"] = "idle"
            state["bullets"] = []

async def handle_arc_pattern(enemy, state, current_time):
    """Thrower: Arcing projectiles"""
    config = ENEMY_TYPES["thrower"]
    
    if current_time - state.get("last_shot_time", 0) >= config["shoot_cooldown"]:
        target = find_closest_player(enemy["x"], enemy["y"])
        if target:
            dx = target["x"] - enemy["x"]
            dy = target["y"] - enemy["y"]
            dist = math.hypot(dx, dy)
            
            if dist > 0:
                travel_time = dist / config["bullet_speed"]
                target_x = target["x"] + target.get("vx", 0) * travel_time * config["prediction"]
                target_y = target["y"] + target.get("vy", 0) * travel_time * config["prediction"]
                
                dx = target_x - enemy["x"]
                dy = target_y - enemy["y"]
                dist = math.hypot(dx, dy)
                
                angle = math.atan2(dy, dx)
                
                enemy_bullets.append({
                    "id": f"arc_{current_time}_{random.randint(1000,9999)}",
                    "x": enemy["x"],
                    "y": enemy["y"],
                    "vx": math.cos(angle) * config["bullet_speed"],
                    "vy": math.sin(angle) * config["bullet_speed"],
                    "arc_height": config["arc_height"],
                    "damage": config["damage"],
                    "created_at": current_time,
                    "owner": "enemy",
                    "color": config["bullet_color"],
                    "size": config["bullet_size"],
                    "pattern": "arc",
                    "start_x": enemy["x"],
                    "start_y": enemy["y"],
                    "target_x": target_x,
                    "target_y": target_y
                })
                
                state["last_shot_time"] = current_time

async def handle_rapid_pattern(enemy, state, current_time):
    enemy_type = enemy.get("type", "")
    config = ENEMY_TYPES[enemy_type]
    
    if state["phase"] == "idle":
        if current_time - state.get("last_shot_time", 0) >= config["shoot_cooldown"]:
            target = find_closest_player(enemy["x"], enemy["y"])
            if target:
                state["phase"] = "bursting"
                state["burst_count"] = 0
                state["burst_start"] = current_time
                state["target_x"] = target["x"]
                state["target_y"] = target["y"]
    
    elif state["phase"] == "bursting":
        if state["burst_count"] < config["burst_count"]:
            if current_time - state.get("last_burst_time", 0) >= config["burst_delay"]:
                dx = state["target_x"] - enemy["x"]
                dy = state["target_y"] - enemy["y"]
                dist = math.hypot(dx, dy)
                
                if dist > 0:
                    inaccuracy = random.uniform(-0.1, 0.1)
                    angle = math.atan2(dy, dx) + inaccuracy
                    
                    bullet_id = f"rapid_{current_time}_{enemy['id']}_{state['burst_count']}"

                    enemy_bullets.append({
                        "id": bullet_id,
                        "x": enemy["x"],
                        "y": enemy["y"],
                        "vx": math.cos(angle) * config["bullet_speed"],
                        "vy": math.sin(angle) * config["bullet_speed"],
                        "damage": config["damage"],
                        "created_at": current_time,
                        "owner": "enemy",
                        "color": config["bullet_color"],
                        "size": config["bullet_size"],
                        "pattern": "rapid",
                        "source_enemy": enemy["id"]
                    })
                    
                    state["burst_count"] += 1
                    state["last_burst_time"] = current_time
        else:
            state["phase"] = "idle"
            state["last_shot_time"] = current_time

async def handle_spread_pattern(enemy, state, current_time):
    config = ENEMY_TYPES["sprayer"]
    
    if current_time - state.get("last_shot_time", 0) >= config["shoot_cooldown"]:
        target = find_closest_player(enemy["x"], enemy["y"])
        if target:
            dx = target["x"] - enemy["x"]
            dy = target["y"] - enemy["y"]
            base_angle = math.atan2(dy, dx)
            
            for i in range(config["spread_count"]):
                spread = (i - config["spread_count"]/2) * config["spread_angle"] / config["spread_count"]
                angle = base_angle + spread
                
                enemy_bullets.append({
                    "id": f"spread_{current_time}_{i}",
                    "x": enemy["x"],
                    "y": enemy["y"],
                    "vx": math.cos(angle) * config["bullet_speed"],
                    "vy": math.sin(angle) * config["bullet_speed"],
                    "damage": config["damage"],
                    "created_at": current_time,
                    "owner": "enemy",
                    "color": config["bullet_color"],
                    "size": config["bullet_size"],
                    "pattern": "spread"
                })
            
            state["last_shot_time"] = current_time

async def handle_mortar_pattern(enemy, state, current_time):
    """Mortar: Area denial explosions"""
    config = ENEMY_TYPES.get("mortar", {
        "shoot_cooldown": 3.5,
        "bullet_speed": 100,
        "bullet_size": 15,
        "bullet_color": "#8B4513",
        "damage": 25,
        "explosion_radius": 60,
        "aim_time": 1.5
    })
    
    if state["phase"] == "idle":
        if current_time - state.get("last_shot_time", 0) >= config["shoot_cooldown"]:
            target = find_closest_player(enemy["x"], enemy["y"])
            if target:
                state["phase"] = "aiming"
                state["aim_start"] = current_time
                state["target_x"] = target["x"]
                state["target_y"] = target["y"]
    
    elif state["phase"] == "aiming":
        if current_time - state["aim_start"] >= config["aim_time"]:
            dx = state["target_x"] - enemy["x"]
            dy = state["target_y"] - enemy["y"]
            dist = math.hypot(dx, dy)
            
            if dist > 0:
                enemy_bullets.append({
                    "id": f"mortar_{current_time}_{random.randint(1000,9999)}",
                    "x": enemy["x"],
                    "y": enemy["y"],
                    "vx": (dx / dist) * config["bullet_speed"],
                    "vy": (dy / dist) * config["bullet_speed"],
                    "damage": config["damage"],
                    "created_at": current_time,
                    "owner": "enemy",
                    "color": config["bullet_color"],
                    "size": config["bullet_size"],
                    "pattern": "mortar",
                    "explosion_radius": config["explosion_radius"],
                    "target_x": state["target_x"],
                    "target_y": state["target_y"]
                })
            
            state["phase"] = "idle"
            state["last_shot_time"] = current_time

async def handle_laser_pattern(enemy, state, current_time):
    """Sniper: Laser-like precise shots"""
    config = ENEMY_TYPES.get("sniper", {
        "shoot_cooldown": 4.0,
        "bullet_speed": 400,
        "bullet_size": 4,
        "bullet_color": "#FF1493",
        "damage": 35,
        "charge_up": 1.0,
        "laser_width": 3
    })
    
    if state["phase"] == "idle":
        if current_time - state.get("last_shot_time", 0) >= config["shoot_cooldown"]:
            target = find_closest_player(enemy["x"], enemy["y"])
            if target:
                state["phase"] = "charging"
                state["charge_start"] = current_time
                state["target"] = target
 
                dx = target["x"] - enemy["x"]
                dy = target["y"] - enemy["y"]
                state["laser_angle"] = math.atan2(dy, dx)
    
    elif state["phase"] == "charging":
        if current_time - state["charge_start"] >= config["charge_up"]:
            dx = state["target"]["x"] - enemy["x"]
            dy = state["target"]["y"] - enemy["y"]
            dist = math.hypot(dx, dy)
            
            if dist > 0:
                enemy_bullets.append({
                    "id": f"laser_{current_time}_{random.randint(1000,9999)}",
                    "x": enemy["x"],
                    "y": enemy["y"],
                    "vx": (dx / dist) * config["bullet_speed"],
                    "vy": (dy / dist) * config["bullet_speed"],
                    "damage": config["damage"],
                    "created_at": current_time,
                    "owner": "enemy",
                    "color": config["bullet_color"],
                    "size": config["bullet_size"],
                    "pattern": "laser",
                    "laser_width": config["laser_width"]
                })
            
            state["phase"] = "idle"
            state["last_shot_time"] = current_time

async def handle_homing_pattern(enemy, state, current_time):
    config = ENEMY_TYPES["seeker"]
    
    if current_time - state.get("last_shot_time", 0) >= config["shoot_cooldown"]:
        target = find_closest_player(enemy["x"], enemy["y"])
        if target:
            dx = target["x"] - enemy["x"]
            dy = target["y"] - enemy["y"]
            dist = math.hypot(dx, dy)
            
            if dist > 0:
                enemy_bullets.append({
                    "id": f"homing_{current_time}_{random.randint(1000,9999)}",
                    "x": enemy["x"],
                    "y": enemy["y"],
                    "vx": (dx / dist) * config["bullet_speed"],
                    "vy": (dy / dist) * config["bullet_speed"],
                    "damage": config["damage"],
                    "created_at": current_time,
                    "owner": "enemy",
                    "color": config["bullet_color"],
                    "size": config["bullet_size"],
                    "pattern": "homing",
                    "homing_strength": config["homing_strength"],
                    "max_turn_rate": config["max_turn_rate"],
                    "target_id": id(target) 
                })
                
                state["last_shot_time"] = current_time

async def handle_wave_pattern(enemy, state, current_time):
    config = ENEMY_TYPES["waver"]
    
    if current_time - state.get("last_shot_time", 0) >= config["shoot_cooldown"]:
        target = find_closest_player(enemy["x"], enemy["y"])
        if target:
            dx = target["x"] - enemy["x"]
            dy = target["y"] - enemy["y"]
            base_angle = math.atan2(dy, dx)
            
            for i in range(config["bullets_per_shot"]):
                offset = (i - config["bullets_per_shot"]/2) * 0.2
                angle = base_angle + offset
                
                enemy_bullets.append({
                    "id": f"wave_{current_time}_{i}",
                    "x": enemy["x"],
                    "y": enemy["y"],
                    "vx": math.cos(angle) * config["bullet_speed"],
                    "vy": math.sin(angle) * config["bullet_speed"],
                    "damage": config["damage"],
                    "created_at": current_time,
                    "owner": "enemy",
                    "color": config["bullet_color"],
                    "size": config["bullet_size"],
                    "pattern": "wave",
                    "wave_amplitude": config["wave_amplitude"],
                    "wave_frequency": config["wave_frequency"],
                    "wave_time": 0,
                    "base_angle": angle
                })
            
            state["last_shot_time"] = current_time

async def handle_boomerang_pattern(enemy, state, current_time):
    config = ENEMY_TYPES["boomerang"]
    
    if current_time - state.get("last_shot_time", 0) >= config["shoot_cooldown"]:
        target = find_closest_player(enemy["x"], enemy["y"])
        if target:
            dx = target["x"] - enemy["x"]
            dy = target["y"] - enemy["y"]
            dist = math.hypot(dx, dy)
            
            if dist > 0:
                enemy_bullets.append({
                    "id": f"boomerang_{current_time}",
                    "x": enemy["x"],
                    "y": enemy["y"],
                    "vx": (dx / dist) * config["bullet_speed"],
                    "vy": (dy / dist) * config["bullet_speed"],
                    "damage": config["damage"],
                    "created_at": current_time,
                    "owner": "enemy",
                    "color": config["bullet_color"],
                    "size": config["bullet_size"],
                    "pattern": "boomerang",
                    "return_time": current_time + config["return_time"],
                    "start_x": enemy["x"],
                    "start_y": enemy["y"],
                    "enemy_id": enemy["id"]
                })
                
                state["last_shot_time"] = current_time

def find_closest_player(x, y):
    closest = None
    closest_dist = float('inf')
    
    for player in players.values():
        if player.get("ghost", False) or player.get("dead", False):
            continue
        dist = math.hypot(x - player["x"], y - player["y"])
        if dist < closest_dist:
            closest_dist = dist
            closest = player
    
    return closest

async def move_enemy_bullets():
    last_time = time.time()
    BULLET_LIFETIME = 5
    
    while True:
        await asyncio.sleep(0.016)
        current_time = time.time()
        delta_time = current_time - last_time
        last_time = current_time
        
        for bullet in enemy_bullets[:]:
            pattern = bullet.get("pattern")
            
            bullet["x"] += bullet["vx"] * delta_time
            bullet["y"] += bullet["vy"] * delta_time
            
            if not bullet.get("infinite_range", False):
                if (bullet["x"] < 0 or bullet["x"] > 2000 or
                    bullet["y"] < 0 or bullet["y"] > 2000):
                    enemy_bullets.remove(bullet)
                    continue
            else:
                if (bullet["x"] < 0 or bullet["x"] > 2000 or
                    bullet["y"] < 0 or bullet["y"] > 2000):
                    enemy_bullets.remove(bullet)
                    continue
            
            if not bullet.get("infinite_range", False):
                if current_time - bullet["created_at"] > BULLET_LIFETIME:
                    enemy_bullets.remove(bullet)
                    continue

            for player_id, player in list(players.items()):
                if player.get("ghost", False) or player.get("dead", False):
                    continue
                
                bullet_size = bullet.get("size", 8)
                hitbox_radius = bullet_size + 10 
                
                if bullet.get("pattern") == "giant":
                    hitbox_radius = bullet_size * 1.5
                
                dist = math.hypot(bullet["x"] - player["x"], bullet["y"] - player["y"])
                if dist < hitbox_radius: 
                    player["health"] -= bullet["damage"]
                    if bullet in enemy_bullets:
                        enemy_bullets.remove(bullet)
                    
                    if player["health"] <= 0:
                        print(f"💀 Player {player_id} killed by Mercenary!")
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
    while True:
        await asyncio.sleep(0.5)
        current_time = time.time()
        
        for enemy in enemies[:]:
            boss_type = enemy.get("type")

            if boss_type not in ["mercenary"]:
                continue
            
            boss_health = enemy["health"]
            max_health = enemy["max_health"]
            health_percent = boss_health / max_health
            
            # BOSS 1: Mercenary 
            if boss_type == "mercenary":
                if health_percent > 0.66:
                    # PHASE 1
                    enemy["color"] = "#FFD700" 
                    
                    if current_time - enemy.get("last_giant_shot", 0) > 4:
                        target = find_closest_player(enemy["x"], enemy["y"])
                        if target:
                            target_x = target["x"]
                            target_y = target["y"]
                            
                            dx = target_x - enemy["x"]
                            dy = target_y - enemy["y"]
                            dist = math.hypot(dx, dy)
                            
                            if dist > 0:
                                bullet = {
                                    "id": f"giant_bullet_{current_time}_{enemy['id']}", 
                                    "x": enemy["x"],
                                    "y": enemy["y"],
                                    "vx": (dx / dist) * 250,
                                    "vy": (dy / dist) * 250,
                                    "damage": 30,
                                    "created_at": current_time,
                                    "owner": "enemy",
                                    "color": "#FFD700",
                                    "size": 25,
                                    "pattern": "giant",
                                    "infinite_range": True,
                                    "boss_phase": 1,
                                    "shrinkStart": None
                                }
                                enemy_bullets.append(bullet)
                                enemy["last_giant_shot"] = current_time
                                print(f"💥 Mercenary {enemy['id']} fired GIANT bullet!")

                elif health_percent > 0.33:
                    # PHASE 2
                    enemy["color"] = "#FF8C00" 
                    
                    if current_time - enemy.get("last_rotation_time", 0) > 3:
                        if "rotation_angle" not in enemy:
                            enemy["rotation_angle"] = 0
                        
                        for i in range(8):
                            angle = enemy["rotation_angle"] + (i / 8) * math.pi * 2
                            bullet = {
                                "id": f"rotating_{current_time}_{enemy['id']}_{i}", 
                                "x": enemy["x"],
                                "y": enemy["y"],
                                "vx": math.cos(angle) * 150,
                                "vy": math.sin(angle) * 150,
                                "damage": 15,
                                "created_at": current_time,
                                "owner": "enemy",
                                "color": "#FF8C00",
                                "size": 10,
                                "pattern": "rotating",
                                "rotation_speed": 0.1,
                                "current_angle": angle,
                                "boss_phase": 2,
                                "shrinkStart": 0.8,
                                "maxLifetime": 4000
                            }
                            enemy_bullets.append(bullet)

                    if current_time - enemy.get("last_giant_shot_phase3", 0) > 3:
                        target = find_closest_player(enemy["x"], enemy["y"])
                        if target:
                            target_x = target["x"]
                            target_y = target["y"]
                            
                            dx = target_x - enemy["x"]
                            dy = target_y - enemy["y"]
                            dist = math.hypot(dx, dy)
                            
                            if dist > 0:
                                bullet = {
                                    "id": f"giant_bullet_phase2_{current_time}_{enemy['id']}",
                                    "x": enemy["x"],
                                    "y": enemy["y"],
                                    "vx": (dx / dist) * 300,
                                    "vy": (dy / dist) * 300,
                                    "damage": 35,
                                    "created_at": current_time,
                                    "owner": "enemy",
                                    "color": "#FF8C00",
                                    "size": 27,
                                    "pattern": "giant",
                                    "infinite_range": True,
                                    "boss_phase": 2,
                                    "shrinkStart": None
                                }
                                enemy_bullets.append(bullet)
                                enemy["last_giant_shot_phase3"] = current_time
                        
                        enemy["rotation_angle"] += 0.5
                        enemy["last_rotation_time"] = current_time
                        print(f"🔄 Mercenary {enemy['id']} fired rotating pattern!")
                
                else:
                    # PHASE 3
                    enemy["color"] = "#FF0000" 
                    enemy["speed"] = 80

                    if current_time - enemy.get("last_giant_shot_phase3", 0) > 2.5:
                        target = find_closest_player(enemy["x"], enemy["y"])
                        if target:
                            # Store target position, not the object
                            target_x = target["x"]
                            target_y = target["y"]
                            
                            dx = target_x - enemy["x"]
                            dy = target_y - enemy["y"]
                            dist = math.hypot(dx, dy)
                            
                            if dist > 0:
                                bullet = {
                                    "id": f"giant_bullet_phase3_{current_time}_{enemy['id']}",
                                    "x": enemy["x"],
                                    "y": enemy["y"],
                                    "vx": (dx / dist) * 300,
                                    "vy": (dy / dist) * 300,
                                    "damage": 35,
                                    "created_at": current_time,
                                    "owner": "enemy",
                                    "color": "#FF4444",
                                    "size": 30,
                                    "pattern": "giant",
                                    "infinite_range": True,
                                    "boss_phase": 3,
                                    "shrinkStart": None
                                }
                                enemy_bullets.append(bullet)
                                enemy["last_giant_shot_phase3"] = current_time
                    
                    if current_time - enemy.get("last_rotation_time_phase3", 0) > 1.5:
                        if "rotation_angle" not in enemy:
                            enemy["rotation_angle"] = 0
                        
                        for i in range(12):
                            angle = enemy["rotation_angle"] + (i / 12) * math.pi * 2
                            bullet = {
                                "id": f"rotating_phase3_{current_time}_{enemy['id']}_{i}",  # Include enemy ID
                                "x": enemy["x"],
                                "y": enemy["y"],
                                "vx": math.cos(angle) * 180,
                                "vy": math.sin(angle) * 180,
                                "damage": 18,
                                "created_at": current_time,
                                "owner": "enemy",
                                "color": "#FF4444",
                                "size": 12,
                                "pattern": "rotating",
                                "rotation_speed": 0.15,
                                "current_angle": angle,
                                "boss_phase": 3,
                                "shrinkStart": 0.8,
                                "maxLifetime": 4000
                            }
                            enemy_bullets.append(bullet)
                        
                        enemy["rotation_angle"] += 0.8
                        enemy["last_rotation_time_phase3"] = current_time
                        print(f"💢 Mercenary {enemy['id']} ENRAGED!")

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
        
        for bullet in bullets[:]:
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

        grid = build_spatial_grid()
        
        # Handle enemy-to-enemy collisions
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
        
        # Check player-enemy collisions
        for enemy in enemies[:]:
            enemy_size = enemy.get("size", 18)
            enemy_type = enemy.get("type", "normal")
            last_damage_time = enemy.get("last_damage_time", 0)
            damage_cooldown = 0.5
            
            for player_id, player in list(players.items()):
                # Skip ghosts and dead players
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
    
    # Don't add to players dict yet - wait for spawn
    print(f"Player {player_id} connected (waiting for spawn). Total connections: {len(clients)}")
    
    # Send ONLY menu init - no player creation yet
    await websocket.send(json.dumps({
        "type": "init_menu",
        "id": player_id,
        "leaderboard": [{"id": pid, "score": p["score"], "name": p.get("name", f"Player{pid}")} 
                        for pid, p in sorted(players.items(), key=lambda x: x[1]["score"], reverse=True)[:10]]
    }))

    try:
        async for message in websocket:
            data = json.loads(message)
            
            if data["type"] == "spawn_player":
                players[player_id] = {
                    "x": random.randint(100, 1900),
                    "y": random.randint(100, 1900),
                    "angle": 0,
                    "health": 100,
                    "score": 0,
                    "dead": False,
                    "ghost": False,
                    "name": data.get("name", f"Player{player_id}"),
                    "spawned": True
                }
                
                print(f"✅ Player {player_id} spawned at ({players[player_id]['x']}, {players[player_id]['y']})")
                
                await websocket.send(json.dumps({
                    "type": "init",
                    "id": player_id,
                    "x": players[player_id]["x"],
                    "y": players[player_id]["y"],
                    "health": 100,
                    "leaderboard": [{"id": pid, "score": p["score"], "name": p.get("name", f"Player{pid}")} 
                                    for pid, p in sorted(players.items(), key=lambda x: x[1]["score"], reverse=True)[:10]]
                }))
                
                await broadcast_leaderboard()
                
            elif data["type"] == "move":
                if player_id in players and players[player_id].get("spawned", False):
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
                if player_id in players:
                    players[player_id]["name"] = data["name"][:15]
                await broadcast_leaderboard()
            
            elif data["type"] == "chat":
                print(f"📨 Chat from player {player_id}: {data['message']}")
                
                chat_message = json.dumps({
                    "type": "chat",
                    "playerId": player_id,
                    "playerName": players[player_id].get("name", f"Player{player_id}") if player_id in players else f"Player{player_id}",
                    "message": data["message"]
                })
                
                await asyncio.gather(*(client.send(chat_message) for client in clients))
                
            elif data["type"] == "shoot":
                if player_id in players and not players[player_id].get("ghost", False) and not players[player_id].get("dead", False):
                    bullet = data["bullet"]
                    bullet["owner"] = player_id
                    bullet["createdAt"] = time.time()
                    bullets.append(bullet)
                
            elif data["type"] == "spawn_enemy":
                if player_id in players:
                    enemies.append(data["enemy"])
                
            elif data["type"] == "request_respawn":
                if player_id in players and players[player_id].get("ghost", False):
                    players[player_id]["x"] = random.randint(100, 1900)
                    players[player_id]["y"] = random.randint(100, 1900)
                    players[player_id]["health"] = 100
                    players[player_id]["dead"] = False
                    players[player_id]["ghost"] = False
                    players[player_id]["score"] = max(0, players[player_id].get("score", 0) - 50)
                    
                    print(f"🔄 Player {player_id} respawned")
                    
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

            elif data["type"] == "hello_menu":
                pass
            elif data["type"] == "spawn_boss":
                if player_id in players:
                    boss = data["boss"]
                    enemies.append(boss)
                    
                    boss_msg = json.dumps({
                        "type": "boss_spawn",
                        "wave": wave_number
                    })
                    await asyncio.gather(*(client.send(boss_msg) for client in clients), return_exceptions=True)
                    
                    print(f"👑 Player {player_id} spawned a boss!")
            
    except websockets.exceptions.ConnectionClosed:
        print(f"Player {player_id} disconnected")
        if player_id in players:
            del players[player_id]
        await broadcast_leaderboard()
    finally:
        clients.remove(websocket)
        if player_id in players:
            del players[player_id]
            print(f"✅ Player {player_id} removed from game")

        bullets[:] = [b for b in bullets if b.get("owner") != player_id]

        await broadcast_leaderboard()

        player_count_msg = json.dumps({
            "type": "player_count",
            "count": len(players)
        })
        await asyncio.gather(*(client.send(player_count_msg) for client in clients), return_exceptions=True)

async def broadcast_player_count():
    while True:
        await asyncio.sleep(1)
        if clients:
            player_count_msg = json.dumps({
                "type": "player_count",
                "count": len(players)
            })
            await asyncio.gather(*(client.send(player_count_msg) for client in clients), return_exceptions=True)

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
                "enemy_bullets": enemy_bullets,
                "is_menu_preview": True 
            })
            await asyncio.gather(*(client.send(game_update) for client in clients), return_exceptions=True)

async def main():
    port = int(os.environ.get('PORT', 10000))
    
    print(f"🚀 Starting server on port {port}...")
    print(f"   Enemy update rate: {1/ENEMY_UPDATE_RATE:.0f} FPS")
    print(f"   Bullet update rate: {1/BULLET_UPDATE_RATE:.0f} FPS")
    print(f"   Broadcast rate: {1/BROADCAST_RATE:.0f} FPS")
    
    asyncio.create_task(move_enemies())
    asyncio.create_task(move_bullets())
    asyncio.create_task(wave_manager())
    asyncio.create_task(boss_attacks())
    asyncio.create_task(broadcast_updates())
    asyncio.create_task(move_enemy_bullets())
    asyncio.create_task(broadcast_player_count())
    asyncio.create_task(handle_enemy_shooting())
    
    async with websockets.serve(handle_client, "0.0.0.0", port):
        print(f"✅ WebSocket server started on port {port}")
        await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())
