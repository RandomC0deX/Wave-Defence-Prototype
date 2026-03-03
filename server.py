#for later: import struct
import websockets
import asyncio
import json
import os

# Player data
players = {}
next_player_id = 1
clients = set()

# Game world (empty for now)
game_state = {
    "enemies": [],
    "projectiles": [],
    "walls": []
}

async def handle_client(websocket):
    global next_player_id
    player_id = next_player_id
    next_player_id += 1
    clients.add(websocket)
    
    # Player starts at center
    players[player_id] = {
        "x": 400,
        "y": 300,
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
            
            if data["type"] == "chat":
                print(f"📨 Chat from player {player_id}: {data['message']}")
                
                chat_message = json.dumps({
                    "type": "chat",
                    "playerId": player_id,
                    "message": data["message"]
                })
                
                await asyncio.gather(*(client.send(chat_message) for client in clients))
                print(f"✅ Chat broadcast complete")
            
            # Broadcast game state
            game_update = json.dumps({
                "type": "update",
                "players": players,
                "game": game_state
            })
            await asyncio.gather(*(client.send(game_update) for client in clients))
            
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
    async with websockets.serve(handle_client, "0.0.0.0", port):
        print(f"✅ WebSocket server started on port {port}")
        print("🌐 Connect at: wss://project-rts.onrender.com")
        await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())
