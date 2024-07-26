import base64
import json
import os
import time
import traceback

import numpy as np
import pyjson5
import textwrap

import pymongo
from PIL import Image
from pyboy import PyBoy, WindowEvent
from rich.pretty import pprint
import requests

from openai import OpenAI
import anthropic


client = anthropic.Anthropic()

json_prefix_prompt = """{
  "thoughts": \""""


def encode_image(image_path):
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode("utf-8")


def loose_parse_json(json_string: str):
    json_substring = json_string[json_string.find("{") : json_string.rfind("}") + 1]

    return pyjson5.loads(json_substring)


def get_gpt_response(prompt):
    pprint(prompt)
    completion = client.messages.create(
        system=textwrap.dedent(
            """\
    You are Claude and you are currently playing Pokémon Crystal. You should output a JSON object containing the following keys:
    `ts
    type output = {
      thoughts: string;
      memory: any;
      buttons: ("A" | "B" | "UP" | "DOWN" | "LEFT" | "RIGHT" | "START")[];
    };
    `
    "thoughts": A short string in which you should analyze the current situation and think step-by-step about what to do next. This will also serve as live commentary, read out to the YouTube audience. Limit this to ~50 words.
    "memory": Arbitrary JSON containing notes to your future self. This should include both short and long term goals and important information you learn. This is the only information that will be passed to your future self, so you should include anything from the previous session that you still want to remember including any important lessons that you've learned while removing anything no longer relevant to save on token cost. For example, if something you've tried to achieve a goal has not worked many times in a row, you might want to record it in your memory for future reference.
    "buttons": The sequence of button presses you want to input into the game, as an array. The only valid button inputs are "A", "B", "UP", "DOWN", "LEFT", "RIGHT", and "START". For example, if you need to select a menu option in the game, you must turn-by-turn use the direction buttons to navigate to that option, followed by "A" to select it.
    
    Only output JSON. Do not include a Markdown block around it.
                """
        ),
        model="claude-3-5-sonnet-20240620",
        messages=prompt,
        max_tokens=1024,
    )

    pprint(completion)
    return json_prefix_prompt + completion.content[0].text

    # for now, return dummy json
    # return json.dumps(
    #     {
    #         "thoughts": "No thoughts so far, just placeholders.",
    #         "memory": {"head": "empty"},
    #         "buttons": ["A", "A"],
    #     }
    # )


# def get_commentary(thoughts, turn_number, suffix):
#     commentary_path = f"commentary{suffix}/thoughts{turn_number:09}.mp3"
#
#     response = client.audio.speech.create(model="tts-1", voice="echo", input=thoughts)
#
#     response.stream_to_file(commentary_path)
#
#     # for now, just copy dummy mp3 to commentary folder
#     # with open(commentary_path, "wb") as f:
#     #     f.write(open("speech.mp3", "rb").read())
#
#     return commentary_path


def main(suffix=""):
    # connect to local mongo
    client = pymongo.MongoClient("localhost", 27017)

    # check if db exists
    if "pokemon" + suffix not in client.list_database_names():
        client["pokemon" + suffix].create_collection("turns")
        # copy inital turn from "pokemon" db
        client["pokemon" + suffix].turns.insert_one(client["pokemon"].turns.find_one())
        # make screenshot and savestate foldes
        os.makedirs(f"screenshots{suffix}")
        os.makedirs(f"savestates{suffix}")

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

    turn_list = []
    for turn in turns[::-1]:
        if all(
            button in ["A", "B", "UP", "DOWN", "LEFT", "RIGHT", "START"]
            for button in turn["buttons"]
        ):
            turn_list.append(
                {
                    "type": "text",
                    "text": f"Turn {turn['turn']}.\nInternal thoughts: {turn['thoughts']}\nButton sequence: {json.dumps(turn['buttons'])}\nScreenshot:",
                }
            )

            for screenshot_path in turn["screenshots"]:
                turn_list.append(
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": encode_image(screenshot_path),
                        },
                    }
                )
        else:
            turn_list.append(
                {
                    "type": "text",
                    "text": f'Turn {turn["turn"]}.\nInternal thoughts: {turn["thoughts"]}\nButton sequence: {json.dumps(turn["buttons"])}. This is an invalid button sequence. The only valid button presses are "A", "B", "UP", "DOWN", "LEFT", "RIGHT", and "START".',
                }
            )

    prompt = [
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": textwrap.dedent(
                        f"""
                    Here is your current working memory in JSON: {json.dumps(current_memory)}
                 Next is the summary of your most recent turns. Pay attention to the buttons you pressed and the effect they had on the subsequent screenshots. Are you achieving your goals successfully? If not, think about what changes should you make to your strategy.
                 """
                    ),
                },
                *turn_list,
                {
                    "type": "text",
                    "text": "The last screenshot above is the current in-game situation. Respond accordingly.",
                },
            ],
        },
        {
            "role": "assistant",
            "content": [{"type": "text", "text": json_prefix_prompt}],
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
            for _ in range(8):
                pyboy.tick()
            pyboy.send_input(WindowEvent.RELEASE_ARROW_UP)
            pyboy.tick()
        elif button.upper().startswith("DOWN"):
            pyboy.send_input(WindowEvent.PRESS_ARROW_DOWN)
            pyboy.tick()
            pyboy.tick()
            pyboy.tick()
            for _ in range(8):
                pyboy.tick()
            pyboy.send_input(WindowEvent.RELEASE_ARROW_DOWN)
            pyboy.tick()
        elif button.upper().startswith("LEFT"):
            pyboy.send_input(WindowEvent.PRESS_ARROW_LEFT)
            pyboy.tick()
            pyboy.tick()
            pyboy.tick()
            for _ in range(8):
                pyboy.tick()
            pyboy.send_input(WindowEvent.RELEASE_ARROW_LEFT)
            pyboy.tick()
        elif button.upper().startswith("RIGHT"):
            pyboy.send_input(WindowEvent.PRESS_ARROW_RIGHT)
            pyboy.tick()
            pyboy.tick()
            pyboy.tick()
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
        pil_images = []
        for i in range(5):
            pyboy.tick()
            pil_images.append(pyboy.screen_image())
        averaged_image = np.mean(np.array(pil_images), axis=0)
        screenshot_path = (
            f"screenshots{suffix}/screenshot_{current_screenshot_index:07}.png"
        )

        # convert averaged_image to PIL image
        averaged_image = Image.fromarray(averaged_image.astype(np.uint8))
        averaged_image.save(screenshot_path)
        current_screenshot_index += 1

        next_turn["screenshots"].append(screenshot_path)

    savestate_path = f"savestates{suffix}/state_{most_recent_turn['turn'] + 1:07}.save"
    pyboy.save_state(open(savestate_path, "wb"))
    next_turn["savestate"] = savestate_path

    client["pokemon" + suffix].turns.insert_one(next_turn)

    # commentary_file = get_commentary(next_turn["thoughts"], next_turn["turn"], suffix)

    # Discord webhook
    webhook_url = os.environ.get("WEBHOOK_URL")

    data = {
        "content": f"""Turn {next_turn['turn']}: {next_turn['thoughts']}
Buttons: `{json.dumps(next_turn['buttons'])}`
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
        },
    )


def dump_to_markdown(suffix=""):
    # connect to local mongo
    client = pymongo.MongoClient("localhost", 27017)
    # grab entire turn collection
    turns = list(client["pokemon" + suffix].turns.find())
    # convert the sequence of turns to markdown
    markdown = ""
    for turn in turns:
        markdown += f"## Turn {turn['turn']}\n"
        markdown += f"Thoughts:\n>{turn['thoughts']}\n\n"
        markdown += f"Buttons:  \n`{json.dumps(turn['buttons'])}`\n\n"
        markdown += f"""Memory:
```json
{json.dumps(turn['memory'], indent=2)}
```

"""
        markdown += "Screenshots:\n\n"
        for screenshot in turn["screenshots"]:
            markdown += f"![screenshot]({screenshot}) "
        markdown += "\n\n"

    with open(f"pokemon{suffix}.md", "w", encoding="utf-8") as f:
        f.write(markdown)


if __name__ == "__main__":
    dump_to_markdown("")
    # for i in range(15):
    #     try:
    #         main(suffix="-sonnet1")
    #     except Exception as e:
    #         print(f"Exception occurred on turn {i}: {traceback.format_exc()}")
    #
    #     print(f"Turn {i} complete. Waiting 5 seconds...")
    #     time.sleep(15)
