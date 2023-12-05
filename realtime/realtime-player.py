import base64
import json
from typing import List, Any, Optional

import pyjson5
import textwrap

import pymongo
from SimpleWebSocketServer import SimpleWebSocketServer, WebSocket
from pyboy import PyBoy, WindowEvent
from rich.pretty import pprint
from openai import OpenAI


DB_NAME = "pokemon_test_1"


def encode_image(image_path):
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode("utf-8")


def loose_parse_json(json_string: str):
    json_substring = json_string[json_string.find("{") : json_string.rfind("}") + 1]

    return pyjson5.loads(json_substring)


def get_gpt_response(prompt):
    # pprint(prompt)

    completion = OpenAI().chat.completions.create(
        model="gpt-4-vision-preview",
        messages=prompt,
        max_tokens=1024,
        # response_format={"type": "json_object"},
    )

    pprint(completion)
    return completion.choices[0].message.content

    # for now, return dummy json with randomly sampled buttons
    # return json.dumps(
    #     {
    #         "thoughts": f"No thoughts so far, just placeholders. {random.random()}",
    #         "memory": {"head": "empty", "random_number": random.random()},
    #         "buttons": random.choices(
    #             ["A", "B", "UP", "DOWN", "LEFT", "RIGHT", "START"],
    #             k=5,
    #         ),
    #     }
    # )


def get_commentary(thoughts, turn_number):
    commentary_path = f"commentary/thoughts{turn_number:09}.mp3"

    response = OpenAI().audio.speech.create(model="tts-1", voice="echo", input=thoughts)

    response.stream_to_file(commentary_path)

    # for now, just copy dummy mp3 to commentary folder
    # with open(commentary_path, "wb") as f:
    #     f.write(open("speech.mp3", "rb").read())

    return commentary_path


def press_button(pyboy: PyBoy, button_down: WindowEvent, button_up: WindowEvent):
    print(f"Pressing button {button_down}...")
    pyboy.send_input(button_down)
    for _ in range(10):
        pyboy.tick()
    pyboy.send_input(button_up)


def press_button_string(pyboy: PyBoy, button: str, screenshot_index=None):
    if button.upper().startswith("A"):
        press_button(pyboy, WindowEvent.PRESS_BUTTON_A, WindowEvent.RELEASE_BUTTON_A)
    elif button.upper().startswith("B"):
        press_button(pyboy, WindowEvent.PRESS_BUTTON_B, WindowEvent.RELEASE_BUTTON_B)
    elif button.upper().startswith("UP"):
        press_button(pyboy, WindowEvent.PRESS_ARROW_UP, WindowEvent.RELEASE_ARROW_UP)
    elif button.upper().startswith("DOWN"):
        press_button(
            pyboy, WindowEvent.PRESS_ARROW_DOWN, WindowEvent.RELEASE_ARROW_DOWN
        )
    elif button.upper().startswith("LEFT"):
        press_button(
            pyboy, WindowEvent.PRESS_ARROW_LEFT, WindowEvent.RELEASE_ARROW_LEFT
        )
    elif button.upper().startswith("RIGHT"):
        press_button(
            pyboy, WindowEvent.PRESS_ARROW_RIGHT, WindowEvent.RELEASE_ARROW_RIGHT
        )
    elif button.upper().startswith("START"):
        press_button(
            pyboy, WindowEvent.PRESS_BUTTON_START, WindowEvent.RELEASE_BUTTON_START
        )
    else:
        print("Invalid button input")

    for _ in range(60 * 5):
        pyboy.tick()

    if screenshot_index is not None:
        pil_image = pyboy.screen_image()
        screenshot_path = f"screenshots/screenshot_{screenshot_index:07}.png"
        pil_image.save(screenshot_path)


from multiprocessing import Process, Queue


def prepare_next_turn(
    turn_list: List[Any], result_queue: Queue, websocket_message_queue: Queue
):
    most_recent_turn = turn_list[0]
    current_memory = most_recent_turn["memory"]

    next_turn_progress = {
        "turnToPrepare": most_recent_turn["turn"] + 1,
        "chatGPTResponse": "pending",
        "buttonPresses": "pending",
        "commentary": "pending",
    }

    def update_status():
        websocket_message_queue.put(
            {"type": "nextTurnProgress", "payload": next_turn_progress}
        )

    print(f"Preparing turn {most_recent_turn['turn'] + 1}")

    prompt = [
        {
            "role": "system",
            "content": textwrap.dedent(
                """\
        You are ChatGPT and you are currently playing Pokémon Crystal. You should output a JSON object containing the following keys:
        `ts
        type output = {
          thoughts: string;
          memory: any;
          buttons: ("A" | "B" | "UP" | "DOWN" | "LEFT" | "RIGHT" | "START")[];
        };
        `
        "thoughts": A short string in which you should analyze the current situation and think step-by-step about what to do next. This will also serve as live commentary, read out to the YouTube audience.
        "memory": Arbitrary JSON containing notes to your future self. This should include both short and long term goals and important information you learn. This is the only information that will be passed to your future self, so you should include anything from the previous session that you still want to remember including any important lessons that you've learned while removing anything no longer relevant to save on token cost. For example, if something you've tried to achieve a goal has not worked many times in a row, you might want to record it in your memory for future reference.
        "buttons": A sequence of button presses you want to input into the game. These will be entered one second apart so you can safely navigate entire tiles or select menu options. To be efficient, try to plan ahead and input as many button presses in sequence as you can.
        
        Only output JSON. Do not include a Markdown block around it.
					"""
            ),
        },
        {
            "role": "user",
            "content": f"""Here is your current working memory in JSON: {json.dumps(current_memory)}""",
        },
        {
            "role": "user",
            "content": f"Next is the summary of your most recent turns. Study them closely. What did you intend to do? Did you succeed? What went wrong? What did you learn, and what should you do next?",
        },
        *[
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": f"Turn {turn['turn']}. Internal thoughts: {turn['thoughts']}; Button presses: {json.dumps(turn['buttons'])}. Screenshots:",
                    },
                    *[
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{encode_image(screenshot_path)}",
                                "detail": "low",
                            },
                        }
                        for screenshot_path in turn["screenshots"]
                    ],
                ],
            }
            for turn in turn_list[::-1]
        ],
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": f"The last screenshot above is the current in-game situation. Respond accordingly.",
                }
            ],
        },
    ]

    next_turn_progress["chatGPTResponse"] = "in progress"
    update_status()

    gpt_response = loose_parse_json(get_gpt_response(prompt))

    next_turn_progress["chatGPTResponse"] = "completed"
    update_status()

    print("got gpt response!", gpt_response)

    new_thoughts = gpt_response["thoughts"]
    new_memory = gpt_response["memory"]
    new_buttons: list[str] = gpt_response["buttons"]

    current_screenshot_index = most_recent_turn["screenshot_index"]

    current_screenshot_index += 1

    next_turn = {
        "turn": most_recent_turn["turn"] + 1,
        "thoughts": new_thoughts,
        "memory": new_memory,
        "buttons": new_buttons,
        "screenshot_index": current_screenshot_index + len(new_buttons),
        "screenshots": [],
        "savestate": "",
    }

    next_turn_progress["buttonPresses"] = f"Pressed 0 out of {len(new_buttons)}"
    update_status()

    # execute button presses
    pyboy = PyBoy("pokemon-crystal.gbc", window_type="headless")
    pyboy.set_emulation_speed(0)

    if "savestate" in most_recent_turn:
        pyboy.load_state(open(most_recent_turn["savestate"], "rb"))

    for i, button in enumerate(new_buttons):
        press_button_string(pyboy, button, screenshot_index=current_screenshot_index)

        next_turn_progress[
            "buttonPresses"
        ] = f"Pressed {i + 1} out of {len(new_buttons)}"
        update_status()

        next_turn["screenshots"].append(
            f"screenshots/screenshot_{current_screenshot_index:07}.png"
        )

        current_screenshot_index += 1

    savestate_path = f"savestates/state_{most_recent_turn['turn'] + 1:07}.save"
    with open(savestate_path, "wb") as f:
        pyboy.save_state(f)
    next_turn["savestate"] = savestate_path

    next_turn_progress["commentary"] = f"In progress"
    update_status()

    get_commentary(next_turn["thoughts"], next_turn["turn"])

    next_turn_progress["commentary"] = f"Completed"
    update_status()

    result_queue.put(next_turn)


def websocket_server_daemon(message_queue: Queue):
    websocket_clients = []
    message_history = {}

    class SimpleServer(WebSocket):
        def handleConnected(self):
            print(self.address, "connected")
            websocket_clients.append(self)

            for message in message_history.values():
                self.sendMessage(json.dumps(message))

        def handleClose(self):
            websocket_clients.remove(self)

    websocket_server = SimpleWebSocketServer("", 8001, SimpleServer)
    websocket_server.serveonce()

    def send_websocket_message(message):
        pprint("Sending websocket message")
        pprint(message)
        json_message = json.dumps(message)
        for client in websocket_clients:
            client.sendMessage(json_message)
        websocket_server.serveonce()

    while True:
        next_message = message_queue.get()
        message_history[next_message["type"]] = next_message
        send_websocket_message(next_message)


def orchestrator():
    websocket_message_queue = Queue()
    websocket_process = Process(
        target=websocket_server_daemon,
        args=(websocket_message_queue,),
    )
    try:
        websocket_process.start()

        mongo_client = pymongo.MongoClient("localhost", 27017)
        pyboy = PyBoy(
            "pokemon-crystal.gbc",
            # sound=True,
        )
        pyboy.tick()

        latest_turns: Optional[List] = None

        for _ in range(10):
            # grab highest turn
            if latest_turns is None:
                latest_turns = list(
                    mongo_client[DB_NAME]
                    .turns.find()
                    .sort("turn", pymongo.DESCENDING)
                    .limit(3)
                )
            current_turn = latest_turns[0]
            print(f"current turn is {current_turn['turn']}")

            if len(latest_turns) > 1:
                with open(latest_turns[1]["savestate"], "rb") as f:
                    pyboy.load_state(f)

            print("calling prepare task in a process")

            results_queue = Queue()
            next_turn_process = Process(
                target=prepare_next_turn,
                args=(latest_turns, results_queue, websocket_message_queue),
            )
            next_turn_process.start()

            websocket_message_queue.put(
                {"type": "turn", "payload": current_turn["turn"]}
            )
            websocket_message_queue.put(
                {"type": "thoughts", "payload": current_turn["thoughts"]}
            )
            websocket_message_queue.put(
                {"type": "memory", "payload": current_turn["memory"]}
            )

            websocket_message_queue.put(
                {
                    "type": "buttons",
                    "payload": {
                        "buttons": current_turn["buttons"],
                        "current_button": -1,
                    },
                }
            )

            print("Playing back button sequence")
            for i, button in enumerate(current_turn["buttons"]):
                websocket_message_queue.put(
                    {
                        "type": "buttons",
                        "payload": {
                            "buttons": current_turn["buttons"],
                            "current_button": i,
                        },
                    }
                )
                press_button_string(pyboy, button)
            print(f"waiting for prepare task to finish")

            if results_queue.empty():
                print("Queue is empty, waiting...")

            next_turn_result = results_queue.get()
            mongo_client[DB_NAME].turns.insert_one(next_turn_result)
            next_turn_process.join()

            latest_turns.pop()
            latest_turns.insert(0, next_turn_result)
    finally:
        websocket_process.kill()


def main():
    orchestrator()


if __name__ == "__main__":
    main()
