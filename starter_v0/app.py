import streamlit as st
import json
from pathlib import Path

from chat import run_model_tool_loop
from env_loader import load_lab_env
from providers import make_provider
from versioning import build_artifact_version
from tools import load_tool_declarations, to_openai_tools

# --- Setup ---
ROOT = Path(__file__).parent
load_lab_env(ROOT)

st.set_page_config(page_title="Northstar IT Helpdesk", page_icon="🎧")
st.title("Northstar IT Helpdesk Agent")

# Sidebar configs
with st.sidebar:
    st.header("Config")
    provider_name = st.selectbox("Provider", ["openai", "openrouter", "gemini"])
    version = st.text_input("Version (e.g. v0, v5)", value="v5")
    max_rounds = st.slider("Max Tool Rounds", 1, 10, 5)

# Initialize Session State
if "messages" not in st.session_state:
    st.session_state.messages = []

# Load artifacts
try:
    versioned = build_artifact_version(ROOT / "artifacts", version)
    system_prompt = versioned["system_prompt.md"]
    tool_declarations = versioned["tools.yaml"]["tools"]
    openai_tools = to_openai_tools(tool_declarations)
    provider = make_provider(provider_name)
except Exception as e:
    st.error(f"Error loading config: {e}")
    st.stop()

# Build base messages
base_messages = [{"role": "system", "content": system_prompt}]
for m in st.session_state.messages:
    base_messages.append(m)

# Display chat history
for msg in st.session_state.messages:
    if msg["role"] == "user":
        st.chat_message("user").write(msg["content"])
    elif msg["role"] == "assistant":
        st.chat_message("assistant").write(msg["content"])

# Chat input
if prompt := st.chat_input("Nhập vấn đề của bạn..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    st.chat_message("user").write(prompt)

    base_messages.append({"role": "user", "content": prompt})

    with st.spinner("Agent đang xử lý..."):
        try:
            result = run_model_tool_loop(
                provider=provider,
                messages=base_messages,
                tools=openai_tools,
                model=None,
                max_tool_rounds=max_rounds
            )
            
            # The final response should be in the last turn
            final_turn = result.get("rounds", [])[-1]
            if "final_text" in final_turn:
                # Try to parse the final JSON if it's JSON
                try:
                    final_json = json.loads(final_turn["final_text"])
                    reply = final_json.get("reply", final_turn["final_text"])
                except:
                    reply = final_turn["final_text"]
                    
                st.session_state.messages.append({"role": "assistant", "content": reply})
                st.chat_message("assistant").write(reply)
                
                # Show tool calls
                if result.get("tool_events"):
                    with st.expander("🛠 Xem chi tiết tool calls"):
                        for event in result["tool_events"]:
                            st.write(f"**{event.get('name')}**")
                            st.json(event.get('args'))
                            st.write("*Result:*", event.get('result'))
        except Exception as e:
            st.error(f"Error during execution: {e}")
