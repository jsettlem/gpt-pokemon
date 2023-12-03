import React, {useEffect, useState} from 'react';
import logo from './logo.svg';
import './App.scss';
import {JSONTree} from "react-json-tree";
import useWebSocket from "react-use-websocket";

function App() {
    const colorScheme = {
        scheme: 'grayscale',
        author: 'alexandre gavioli (https://github.com/alexx2/)',
        base00: '#101010',
        base01: '#252525',
        base02: '#464646',
        base03: '#525252',
        base04: '#ababab',
        base05: '#b9b9b9',
        base06: '#e3e3e3',
        base07: '#f7f7f7',
        base08: '#7c7c7c',
        base09: '#999999',
        base0A: '#a0a0a0',
        base0B: '#8e8e8e',
        base0C: '#868686',
        base0D: '#686868',
        base0E: '#747474',
        base0F: '#5e5e5e'
    };

    let [internalMemory, setInternalMemory] = useState({
        head: "empty"
    } as any);
    let [currentTurn, setCurrentTurn] = useState(0);
    let [currentThoughts, setCurrentThoughts] = useState("No thoughts so far, only placeholders");
    let [buttonHistory, setButtonHistory] = useState([] as any[]);
    let [audioSrc, setAudioSrc] = useState("http://localhost:8000/thoughts000000001.mp3");

    const { sendMessage, lastMessage, readyState } = useWebSocket("ws://localhost:8001/", {
        shouldReconnect: (closeEvent) => true,
    });

    useEffect(() => {
        if (lastMessage != null) {
            let message = JSON.parse(lastMessage.data);
            if (message["type"] === "thoughts") {
                setCurrentThoughts(message["payload"]);
            } else if (message["type"] === "memory") {
                setInternalMemory(message["payload"]);
            } else if (message["type"] === "turn") {
                setCurrentTurn(message["payload"]);
                setAudioSrc(`http://localhost:8000/thoughts${message["payload"].toString().padStart(9, "0")}.mp3`)
            } else if (message["type"] === "button") {
                setButtonHistory(old => {
                    let last_button_key = old[old.length - 1]?.key ?? 0;
                    return [...old.slice(-100),
                        {button: message["payload"], key: last_button_key + 1}];
                });
            }
        }
    }, [lastMessage, setCurrentThoughts]);


    return (
        <div className={"main-container"}>
            <div className={"turn-display"}>
                <h1>Current turn: {currentTurn}</h1>
            </div>
            <div className={"button-log"}>
                <h2>Button presses:</h2>
                <div className={"button-container"}>
                    {
                        //@ts-ignore
                        buttonHistory.map((button, index) =>
                            <div className={"button-wrapper"} key={button.key}>
                                <div  className={"button"}>{button.button}</div>

                            </div>
                        )
                    }

                </div>
            </div>
            <div className={"internal-thoughts-log"}>
                <h2>Internal thoughts:</h2>
                <span className={"internal-thoughts-message"} key={currentThoughts}>{currentThoughts}</span>
            </div>

            <audio controls src={audioSrc} key={audioSrc} autoPlay={true} />

            {/*<button onClick={() => setButtonHistory(old => [...old, {button: "Down", key: old.length}])}>Add a button!</button>*/}
            <div className={"memory-display"}>
                <h2>Internal memory:</h2>
                <div className={"memory-tree"}>
                    <JSONTree data={internalMemory}
                              shouldExpandNodeInitially={_ => true}
                              theme={colorScheme}
                              invertTheme={true}
                    />
                </div>

            </div>
        </div>


  );
}

export default App;
