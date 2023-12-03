import json
import time

import pymongo
from SimpleWebSocketServer import SimpleWebSocketServer, WebSocket
from pyboy import PyBoy, WindowEvent
from rich.pretty import pprint

from mutagen.mp3 import MP3

clients = []


class SimpleServer(WebSocket):
    def handleConnected(self):
        print(self.address, "connected")
        clients.append(self)

    def handleClose(self):
        clients.remove(self)


client = pymongo.MongoClient("localhost", 27017)
turns = list(client["pokemon"].turns.find())

server = SimpleWebSocketServer("", 8001, SimpleServer)

pyboy = PyBoy(
    "pokemon-crystal.gbc",
    # sound=True,
)
pyboy.set_emulation_speed(0)

for i in range(240):
    pyboy.tick()

server.serveonce()

count = 0
for turn_index, turn in list(enumerate(turns)):
    narration_duration = (
        MP3(f"commentary/thoughts{turn['turn']:09}.mp3").info.length + 0.5
    )
    print("narration dureation", narration_duration)
    input_sequence_duration = len(turn["buttons"]) * 1011 / 60

    desired_stop_time = time.time() + narration_duration

    pyboy.set_emulation_speed(max(1, input_sequence_duration // narration_duration))

    if turn_index > 0:
        pyboy.load_state(open(turns[turn_index - 1]["savestate"], "rb"))
        pyboy.tick()
        pyboy.load_state(open(turns[turn_index - 1]["savestate"], "rb"))

    pprint(turn)
    for client in clients:
        client.sendMessage(json.dumps({"type": "turn", "payload": turn["turn"]}))
        client.sendMessage(
            json.dumps({"type": "thoughts", "payload": turn["thoughts"]})
        )
        client.sendMessage(json.dumps({"type": "memory", "payload": turn["memory"]}))
    server.serveonce()

    for button in turn["buttons"]:
        for client in clients:
            client.sendMessage(json.dumps({"type": "button", "payload": button}))
        server.serveonce()
        if button.upper().startswith("A"):
            pyboy.send_input(WindowEvent.PRESS_BUTTON_A)
            pyboy.tick()
            pyboy.tick()
            pyboy.tick()
            pyboy.send_input(WindowEvent.RELEASE_BUTTON_A)
            pyboy.tick()
        elif button.upper().startswith("B"):
            pyboy.send_input(WindowEvent.PRESS_BUTTON_B)
            pyboy.tick()
            pyboy.tick()
            pyboy.tick()
            pyboy.send_input(WindowEvent.RELEASE_BUTTON_B)
            pyboy.tick()
        elif button.upper().startswith("UP"):
            pyboy.send_input(WindowEvent.PRESS_ARROW_UP)
            pyboy.tick()
            pyboy.tick()
            pyboy.tick()
            if turn["turn"] >= 29:
                for _ in range(5):
                    pyboy.tick()
            pyboy.send_input(WindowEvent.RELEASE_ARROW_UP)
            pyboy.tick()
        elif button.upper().startswith("DOWN"):
            pyboy.send_input(WindowEvent.PRESS_ARROW_DOWN)
            pyboy.tick()
            pyboy.tick()
            pyboy.tick()
            if turn["turn"] >= 29:
                for _ in range(8):
                    pyboy.tick()
            pyboy.send_input(WindowEvent.RELEASE_ARROW_DOWN)
            pyboy.tick()
        elif button.upper().startswith("LEFT"):
            pyboy.send_input(WindowEvent.PRESS_ARROW_LEFT)
            pyboy.tick()
            pyboy.tick()
            pyboy.tick()
            if turn["turn"] >= 29 or True:
                for _ in range(8):
                    pyboy.tick()
            pyboy.send_input(WindowEvent.RELEASE_ARROW_LEFT)
            pyboy.tick()
        elif button.upper().startswith("RIGHT"):
            pyboy.send_input(WindowEvent.PRESS_ARROW_RIGHT)
            pyboy.tick()
            pyboy.tick()
            pyboy.tick()
            if turn["turn"] >= 29 or True:
                for _ in range(8):
                    pyboy.tick()
            pyboy.send_input(WindowEvent.RELEASE_ARROW_RIGHT)
            pyboy.tick()
        elif button.upper().startswith("START"):
            pyboy.send_input(WindowEvent.PRESS_BUTTON_START)
            pyboy.tick()
            pyboy.tick()
            pyboy.tick()
            pyboy.send_input(WindowEvent.RELEASE_BUTTON_START)
            pyboy.tick()
        else:
            print("Invalid button input")
        for turn_index in range(1_000):
            pyboy.tick()

    if time.time() < desired_stop_time:
        time.sleep(desired_stop_time - time.time())
