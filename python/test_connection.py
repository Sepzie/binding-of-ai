"""Quick test client to verify TCP communication with the Isaac mod."""

import json
import socket
import time

HOST = "127.0.0.1"
PORT = 9999

def main():
    print(f"Connecting to {HOST}:{PORT}...")
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(10.0)
    sock.connect((HOST, PORT))
    sockf = sock.makefile("r")
    print("Connected!\n")

    # 1. Receive initial state
    print("--- Waiting for state from game ---")
    line = sockf.readline()
    state = json.loads(line)
    print(f"Tick: {state.get('tick')}")
    print(f"Player: {json.dumps(state.get('player', {}), indent=2)}")
    print(f"Enemies: {state.get('enemy_count', 0)}")
    print(f"Room cleared: {state.get('room_cleared')}")
    print(f"Grid shape: {len(state.get('grid', []))} channels")
    if state.get("grid"):
        ch = state["grid"][0]
        print(f"  Channel 0: {len(ch)} rows x {len(ch[0]) if ch else 0} cols")
    print()

    # 2. Send a few actions and observe
    actions = [
        ("Move right + shoot left", {"move": 4, "shoot": 3}),
        ("Move up + shoot down", {"move": 1, "shoot": 2}),
        ("Stand still + shoot right", {"move": 0, "shoot": 4}),
    ]

    for desc, action in actions:
        msg = json.dumps({"command": "step", "action": action}) + "\n"
        print(f"--- Sending: {desc} ---")
        sock.sendall(msg.encode())

        line = sockf.readline()
        if not line:
            print("Connection closed by game")
            break
        state = json.loads(line)
        print(f"Tick: {state.get('tick')}, "
              f"Player pos: {state.get('player', {}).get('position')}, "
              f"Enemies: {state.get('enemy_count')}, "
              f"Cleared: {state.get('room_cleared')}")
        print()

    # 3. Test reset
    print("--- Sending reset ---")
    sock.sendall((json.dumps({"command": "reset"}) + "\n").encode())
    print("Reset sent. Waiting for post-reset state...")
    line = sockf.readline()
    if line:
        state = json.loads(line)
        print(f"Post-reset tick: {state.get('tick')}, "
              f"Enemies: {state.get('enemy_count')}")

    print("\nTest complete!")
    sock.close()


if __name__ == "__main__":
    main()
