// import React, { useState } from "react";
// import reactLogo from "./assets/react.svg";
// // import { invoke } from "@tauri-apps/api/core";
// // import { listen } from "@tauri-apps/api/event"
// // import { getCurrentWebviewWindow } from "@tauri-apps/api/webviewWindow"
// import { pyInvoke } from "tauri-plugin-pytauri-api";
// import { Task } from "@/types"
import "./App.css";
// import { useTaskEvents } from "./hooks";

import { TaskManagerDashboard } from "@/components";

// function App() {
//   // const [greetMsg, setGreetMsg] = useState("");
//   // const [name, setName] = useState("");

//   const [, setImportResult] = useState("");
//   const [url, setUrl] = useState("https://wtr-lab.com/en/novel/53992/lord-god-tier-attribute-recruits-fallen-angels-of-original-sin");

//   // const appWindow = getCurrentWebviewWindow();



//   // async function greet() {
//   //   // Learn more about Tauri commands at https://tauri.app/develop/calling-rust/
//   //   const rsGreeting = await invoke<string>("greet", { name });
//   //   // Learn more about PyTauri commands at https://pytauri.github.io/pytauri/latest/usage/concepts/ipc/
//   //   // const pyGreeting = await pyInvoke<string>("greet", { name });
//   //   // setGreetMsg(rsGreeting + "\n" + pyGreeting);
//   // }

//   async function importNovel() {
//     const importResult = await pyInvoke<string>("scrape_novel", { source_url: url, novel_id: Math.random().toString() })
//     setImportResult(importResult)
//   }


//   // const tasks = useTaskEvents((event) => {
//   //   if (event.payload.kind === 'novel_discovery') return event.payload
//   // })

//   // console.log("Tasks", tasks)

//   const TaskRow = React.memo(function TaskRow({ task }: { task: Task }) {
//     return <div><em>{task.state}</em> - {task.message} — {Math.round(task.progress * 100)}%</div>;
//   });

//   function ProgressPanel() {
//     const { tasks } = useTaskEvents(["novel_discovery"]);
//     console.log("Task Event", [...tasks.values()])
//     return <>{[...tasks.values()].map((t) => <TaskRow key={t.id} task={t} />)}</>;
//   }



//   // useEffect(() => {
//   //   let unlisten: (() => void) | undefined;
//   //   let unlistenReady: (() => void) | undefined;

//   //   async function setupListener() {
//   //     // Listen for the event emitted from Rust
//   //     unlisten = await listen<Task>("task-update", (event) => {
//   //       const task = event.payload
//   //       switch (task.kind) {
//   //         case 'novel_discovery':
//   //           console.log("Novel discovery event:", task);
//   //           break;

//   //         default:
//   //           break;
//   //       }
//   //     });

//   //     // Listen to the Tauri ready event
//   //     unlistenReady = await appWindow.once('on_webview_ready', async () => {
//   //       console.log("App is ready! Triggering Python function...");

//   //       try {
//   //         const response = await pyInvoke("on_app_ready");
//   //         console.log(response);
//   //       } catch (error) {
//   //         console.error("Failed to call Python command:", error);
//   //       }
//   //     });
//   //   }

//   //   setupListener();

//   //   // Clean up the listener when the component unmounts
//   //   return () => {
//   //     if (unlisten) unlisten();
//   //     if (unlistenReady) unlistenReady();
//   //   };
//   // }, []);

//   return (
//     <main className="container">
//       <h1>Welcome to PyTauri</h1>
//       <a href="https://pytauri.github.io/pytauri/latest/" target="_blank">
//         <img src="/pytauri.svg" className="logo pytauri" alt="PyTauri logo" />
//       </a>
//       <div className="row">
//         <a href="https://vitejs.dev" target="_blank">
//           <img src="/vite.svg" className="logo vite" alt="Vite logo" />
//         </a>
//         <a href="https://tauri.app" target="_blank">
//           <img src="/tauri.svg" className="logo tauri" alt="Tauri logo" />
//         </a>
//         <a href="https://react.dev/" target="_blank">
//           <img src={reactLogo} className="logo react" alt="React logo" />
//         </a>
//         <a href="https://python.org" target="_blank">
//           <img src="/python.svg" className="logo python" alt="Python logo" />
//         </a>
//       </div>
//       <p>Click on any logo to learn more.</p>

//       <form
//         className="row"
//         onSubmit={async (e) => {
//           e.preventDefault();
//           // await greet();

//           await Promise.all([importNovel()])

//         }}
//       >
//         {/* <input
//           id="greet-input"
//           onChange={(e) => setName(e.currentTarget.value)}
//           placeholder="Enter a name..."
//         /> */}
//         <input
//           id="import-input"
//           defaultValue={url}
//           onChange={(e) => setUrl(e.currentTarget.value)}
//           placeholder="Enter web novel url..."
//         />
//         <button type="submit">Greet</button>
//       </form>
//       {/* <p id="greet-msg">{greetMsg}</p> */}
//       {/* <p id="import-msg">
//         <pre>{JSON.stringify(importResult)}</pre>
//       </p> */}
//       <ProgressPanel />
//     </main>
//   );
// }

// export default App;

function App() {


  return <TaskManagerDashboard />
}

export default App
