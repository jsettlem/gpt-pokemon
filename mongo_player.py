import base64
import json
import os
import time

import pyjson5
import textwrap

import pymongo
from pyboy import PyBoy, WindowEvent
from rich.pretty import pprint
import requests

from openai import OpenAI

client = OpenAI()


def encode_image(image_path):
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode("utf-8")


def loose_parse_json(json_string: str):
    json_substring = json_string[json_string.find("{") : json_string.rfind("}") + 1]

    return pyjson5.loads(json_substring)


def get_gpt_response(prompt):
    pprint(prompt)

    completion = client.chat.completions.create(
        model="gpt-4o",
        messages=prompt,
        max_tokens=1024,
        response_format={"type": "json_object"},
    )

    pprint(completion)
    return completion.choices[0].message.content

    # for now, return dummy json
    # return json.dumps(
    #     {
    #         "thoughts": "No thoughts so far, just placeholders.",
    #         "memory": {"head": "empty"},
    #         "buttons": ["A", "A"],
    #     }
    # )


def get_commentary(thoughts, turn_number, suffix):
    commentary_path = f"commentary{suffix}/thoughts{turn_number:09}.mp3"

    response = client.audio.speech.create(model="tts-1", voice="echo", input=thoughts)

    response.stream_to_file(commentary_path)

    # for now, just copy dummy mp3 to commentary folder
    # with open(commentary_path, "wb") as f:
    #     f.write(open("speech.mp3", "rb").read())

    return commentary_path


def main(suffix=""):
    # connect to local mongo
    client = pymongo.MongoClient("localhost", 27017)
    # grab 10 most recent turns from the database
    turns = (
        client["pokemon" + suffix]
        .turns.find()
        .sort("turn", pymongo.DESCENDING)
        .limit(5)
    )

    turns = list(turns)

    most_recent_turn = turns[0]
    current_memory = most_recent_turn["memory"]
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
        "buttons": A sequence of button presses you want to input into the game. These will be entered one second apart so you can safely navigate entire tiles or select menu options. To be efficient, try to plan ahead and input as many button presses in sequence as you can. The only valid button inputs are "A", "B", "UP", "DOWN", "LEFT", "RIGHT", and "START".
        
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
            for turn in turns[::-1]
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

    gpt_response = loose_parse_json(get_gpt_response(prompt))

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

    # execute button presses
    pyboy = PyBoy("pokemon-crystal.gbc", window_type="headless")
    pyboy.set_emulation_speed(3)

    if "savestate" in most_recent_turn:
        pyboy.load_state(open(most_recent_turn["savestate"], "rb"))

    for button in new_buttons:
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
            if next_turn["turn"] >= 29:
                for _ in range(5):
                    pyboy.tick()
            pyboy.send_input(WindowEvent.RELEASE_ARROW_UP)
            pyboy.tick()
        elif button.upper().startswith("DOWN"):
            pyboy.send_input(WindowEvent.PRESS_ARROW_DOWN)
            pyboy.tick()
            pyboy.tick()
            pyboy.tick()
            if next_turn["turn"] >= 29:
                for _ in range(8):
                    pyboy.tick()
            pyboy.send_input(WindowEvent.RELEASE_ARROW_DOWN)
            pyboy.tick()
        elif button.upper().startswith("LEFT"):
            pyboy.send_input(WindowEvent.PRESS_ARROW_LEFT)
            pyboy.tick()
            pyboy.tick()
            pyboy.tick()
            if next_turn["turn"] >= 29:
                for _ in range(8):
                    pyboy.tick()
            pyboy.send_input(WindowEvent.RELEASE_ARROW_LEFT)
            pyboy.tick()
        elif button.upper().startswith("RIGHT"):
            pyboy.send_input(WindowEvent.PRESS_ARROW_RIGHT)
            pyboy.tick()
            pyboy.tick()
            pyboy.tick()
            if next_turn["turn"] >= 29:
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
        for i in range(1_000):
            pyboy.tick()

        pil_image = pyboy.screen_image()
        screenshot_path = (
            f"screenshots{suffix}/screenshot_{current_screenshot_index:07}.png"
        )
        pil_image.save(screenshot_path)
        current_screenshot_index += 1

        next_turn["screenshots"].append(screenshot_path)

    savestate_path = f"savestates{suffix}/state_{most_recent_turn['turn'] + 1:07}.save"
    pyboy.save_state(open(savestate_path, "wb"))
    next_turn["savestate"] = savestate_path

    client["pokemon" + suffix].turns.insert_one(next_turn)

    commentary_file = get_commentary(next_turn["thoughts"], next_turn["turn"], suffix)

    # Discord webhook
    webhook_url = os.environ.get("WEBHOOK_URL")

    data = {
        "content": f"""Turn {next_turn['turn']}: {next_turn['thoughts']}
Buttons: {",".join("`" + button + "`" for button in next_turn['buttons'])}
Memory: 
```json
{json.dumps(next_turn['memory'], indent=2)}
```
        """,
    }

    requests.post(
        webhook_url,
        files={
            "payload_json": (None, json.dumps(data), "application/json"),
            **{
                f"file{i}": (f"file{i}.png", open(screenshot_path, "rb"), "image/png")
                for i, screenshot_path in enumerate(next_turn["screenshots"][-8:])
            },
            "commentary": (
                commentary_file.split("/")[-1],
                open(commentary_file, "rb"),
                "audio/mpeg",
            ),
        },
    )


if __name__ == "__main__":
    for i in range(5):
        try:
            main(suffix="-o1")
        except Exception as e:
            print(f"Exception occurred on turn {i}: {e}")

        print(f"Turn {i} complete. Waiting 5 seconds...")
        time.sleep(15)
